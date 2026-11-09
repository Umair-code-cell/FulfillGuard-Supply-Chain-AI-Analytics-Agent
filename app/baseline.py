
"""Deterministic, offline investigation baseline (no LLM)."""

from __future__ import annotations

import calendar
import re
import time

from .agent import AgentResult, Investigation, NumericClaim, TraceEvent
from .tools import execute_tool


# Convert English month names to their month numbers.
MONTHS = {
    name.lower(): number
    for number, name in enumerate(calendar.month_name)
    if name
}
MONTHS.update({
    name.lower(): number
    for number, name in enumerate(calendar.month_abbr)
    if name
})


def _month_period(month: int, year: int):
    """Return the first and last date of a calendar month."""
    start = f"{year:04d}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    end = f"{year:04d}-{month:02d}-{last_day:02d}"
    return start, end


def _months(question: str):
    """Extract month/year pairs such as July 2018."""
    q = question.lower()
    results = []

    names = "|".join(sorted(MONTHS, key=len, reverse=True))
    pattern = rf"\b({names})\s+(20\d{{2}})\b"

    for match in re.finditer(pattern, q):
        month = MONTHS[match.group(1)]
        year = int(match.group(2))
        results.append((month, year))

    # Handle a month mentioned separately from a single year.
    if not results:
        year_match = re.search(r"\b(20\d{2})\b", q)

        if year_match:
            year = int(year_match.group(1))

            for match in re.finditer(rf"\b({names})\b", q):
                results.append((MONTHS[match.group(1)], year))

    return results


def _num(evidence_id: str, path: str, value):
    """Turn a tool metric into a traceable numerical claim."""
    if value is None:
        return []

    return [
        NumericClaim(
            evidence_id=evidence_id,
            path=path,
            value=float(value),
        )
    ]


def investigate_offline(question: str) -> AgentResult:
    """Answer supported historical questions using SQL tools only."""
    if not isinstance(question, str) or not 5 <= len(question) <= 1500:
        raise ValueError("Question length must be between 5 and 1500 characters")

    started = time.perf_counter()
    q = question.lower()

    limitations = [
        "Deterministic offline baseline: no language model was called.",
        "Historical data; associations do not establish causation.",
    ]

    def finish(answer, trace=None, verified=0):
        return AgentResult(
            answer=answer,
            trace=trace or [],
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            model="deterministic-baseline",
            numeric_claims_verified=verified,
        )

    # Refuse requests to change data or trigger actions.
    if re.search(r"\b(drop|delete|update|insert|refund|send|modify|write)\b", q):
        return finish(
            Investigation(
                summary="Action refused: this system has no data-modification tools.",
                limitations=limitations,
            )
        )

    periods = _months(question)

    state_match = re.search(
        r"\b(SP|RJ|MG|RS|PR|SC|BA|DF|GO|ES|PE|CE|PA|MT|MS|MA|PB|RN|PI|AL|SE|TO|RO|AM|AC|AP|RR)\b",
        question.upper(),
    )
    state = state_match.group(1) if state_match else None

    # No SQL call for live or unsupported questions.
    if re.search(r"\b(live|today|2026)\b", q) or not periods:
        return finish(
            Investigation(
                summary="Cannot provide a supported calculation for this period or request.",
                next_checks=[
                    "Specify one or two historical purchase months, such as July 2018."
                ],
                limitations=limitations,
            )
        )

    trace = []
    claims = []
    evidence = []
    next_checks = []

    def call(tool, arguments):
        """Execute an allowlisted SQL tool and preserve its output."""
        output = execute_tool(tool, arguments)
        evidence_id = f"T{len(trace) + 1}"

        trace.append(
            TraceEvent(
                id=evidence_id,
                tool=tool,
                arguments=arguments,
                output=output,
            )
        )
        return evidence_id, output

    # ROUTE 1: Compare two periods.
    is_comparison = any(
        word in q
        for word in ("compar", "versus", "vs", "between", "change")
    )

    if is_comparison and len(periods) >= 2:
        previous = _month_period(*periods[0])
        current = _month_period(*periods[1])

        tid, data = call(
            "compare_periods",
            {
                "previous_start": previous[0],
                "previous_end": previous[1],
                "current_start": current[0],
                "current_end": current[1],
                "state": state,
            },
        )

        prev = data["previous"]["result"]
        cur = data["current"]["result"]
        delta = data["late_rate_delta_pp"]

        claims += _num(tid, "previous.result.late_rate_pct", prev["late_rate_pct"])
        claims += _num(tid, "current.result.late_rate_pct", cur["late_rate_pct"])
        claims += _num(tid, "late_rate_delta_pp", delta)

        if delta is None:
            summary = "Cannot compare rates: at least one cohort has no eligible orders."
        else:
            summary = (
                f"Late delivery rate: {prev['late_rate_pct']:.2f}% in "
                f"{periods[0][0]:02d}/{periods[0][1]}, "
                f"{cur['late_rate_pct']:.2f}% in "
                f"{periods[1][0]:02d}/{periods[1][1]}; "
                f"change {delta:+.2f} percentage points"
                + (f" for {state}" if state else "")
                + "."
            )

        evidence.append(f"[{tid}] Same KPI definition applied to both periods.")
        next_checks.append("Investigate differences across customer or seller states.")

    else:
        start, end = _month_period(*periods[0])

        # ROUTE 2: State-level breakdown.
        if any(
            word in q
            for word in ("segment", "state", "breakdown", "seller", "region", "contribut")
        ):
            dimension = "seller_state" if "seller" in q else "customer_state"

            tid, data = call(
                "breakdown",
                {
                    "start": start,
                    "end": end,
                    "state": state,
                    "dimension": dimension,
                    "limit": 10,
                },
            )

            rows = data["rows"]

            if rows:
                top = rows[0]
                summary = (
                    f"Largest displayed segment by late-order count: {top['segment']} "
                    f"({top['late_count']} late out of {top['delivered_count']} "
                    f"delivered {data['unit']} observations)."
                )
                claims += _num(tid, "rows[0].late_count", top["late_count"])
                claims += _num(tid, "rows[0].delivered_count", top["delivered_count"])
            else:
                summary = "No eligible delivered records found for this breakdown."

            evidence.append(
                f"[{tid}] Segments ranked by late-order count; unit: {data['unit']}."
            )
            next_checks.append(
                "Compare late counts and rates to distinguish volume from risk."
            )

        # ROUTE 3: Regular monthly KPIs.
        else:
            tid, data = call(
                "delivery_kpis",
                {"start": start, "end": end, "state": state},
            )

            result = data["result"]
            rate = result["late_rate_pct"]

            claims += _num(tid, "result.delivered_orders", result["delivered_orders"])
            claims += _num(tid, "result.late_orders", result["late_orders"])
            claims += _num(tid, "result.late_rate_pct", rate)

            if rate is None:
                summary = "No eligible delivered orders in this cohort."
            else:
                summary = (
                    f"Late delivery rate: {rate:.2f}% "
                    f"({result['late_orders']}/{result['delivered_orders']} eligible orders)."
                )

            evidence.append(
                f"[{tid}] Calculated from delivered orders with known delivery dates."
            )
            next_checks.append("Compare with another month to assess the change.")

    answer = Investigation(
        summary=summary,
        evidence=evidence,
        next_checks=next_checks,
        limitations=limitations,
        numeric_claims=claims,
    )

    return finish(answer, trace, verified=len(claims))
