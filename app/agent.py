"""Bounded, tool-calling delivery analytics agent with evidence verification."""
from __future__ import annotations
import json
import math
import os
from openai import OpenAI
import re
import time
from typing import Any
from pydantic import BaseModel, Field
from .tools import TOOL_SPECS, execute_tool, ToolInputError
from .tools import TOOL_FUNCTIONS

# The runtime policy is sent to the LLM; only allowlisted tools can execute.
SYSTEM = 'You are FulfillGuard. Only report metrics supported by allowed tools.'

SYSTEM += """
Tool-use and refusal policy:

- For supported historical delivery metrics, use the appropriate
  analytical tool before making factual claims.
- For requests to delete or modify data, issue refunds, execute
  arbitrary SQL, or disclose private customer information, refuse
  without calling tools.
- If a question lacks a necessary year or refers to a relative
  period that cannot be resolved against historical data,
  request clarification. Do not invent dates.
- Do not claim access to live Amazon operational data.
- Never claim that observational relationships prove causation.
- If a request is unsupported, explain the limitation without
  inventing tool results or numerical evidence.
- When no tool was executed, leave the evidence and
  numeric_claims arrays empty.
"""

class NumericClaim(BaseModel):
    evidence_id: str
    path: str
    value: float


class Investigation(BaseModel):
    summary: str
    evidence: list[str] = Field(default_factory=list)
    possible_explanations: list[str] = Field(default_factory=list)
    next_checks: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    numeric_claims: list[NumericClaim] = Field(default_factory=list)


class TraceEvent(BaseModel):
    id: str
    tool: str
    arguments: dict[str, Any]
    output: dict[str, Any]


class AgentResult(BaseModel):
    answer: Investigation
    trace: list[TraceEvent]
    elapsed_ms: int
    tokens_in: int | None = None
    tokens_out: int | None = None
    model: str
    numeric_claims_verified: int = 0
    numeric_claims_rejected: int = 0
    narrative_numeric_issues: int = 0


def check_claims(claims: list[NumericClaim], trace: list[TraceEvent]) -> tuple[list[NumericClaim], int]:
    events = {
        event.id: event.output
        for event in trace
        if "error" not in event.output
    }

    valid = []

    for claim in claims:
        value = events.get(claim.evidence_id)

        path = claim.path.removeprefix("data.")
        for part in re.sub(r"\[(\d+)\]", r".\1", path).split("."):
            if isinstance(value, dict):
                value = value.get(part)

            elif isinstance(value, list) and part.isdigit():
                index = int(part)
                value = value[index] if index < len(value) else None

            else:
                value = None
                break

        if (
            type(value) in (int, float)
            and math.isfinite(value)
            and math.isfinite(claim.value)
            and math.isclose(value, claim.value, rel_tol=0, abs_tol=1e-6)
        ):
            valid.append(claim)

    return valid, len(claims) - len(valid)

def reconcile_narrative_numbers(
    answer: Investigation,
    question: str,
    trace: list[TraceEvent] | None = None
) -> int:

    allowed = {float(c.value) for c in answer.numeric_claims}

    allowed.update(
        float(y) for y in re.findall(r"\b\d{4}\b", question)
    )


    # Extract supported years from successful metadata tools
    for event in trace or []:
        if event.tool != "schema_info" or "error" in event.output:
            continue

        metadata = event.output.get("dataset", "")

        if not isinstance(metadata, str):
            continue

        years = {
            int(y)
            for y in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", metadata)
        }

        # Expand ranges such as 2016–2018 to 2016, 2017, 2018
        ranges = re.findall(
            r"((?:19|20)\d{2})\s*[-\u2010-\u2015]\s*((?:19|20)\d{2})",
            metadata
        )

        for start_year, end_year in ranges:
            start_year = int(start_year)
            end_year = int(end_year)

            if start_year <= end_year and end_year - start_year <= 20:
                years.update(range(start_year, end_year + 1))

        allowed.update(float(year) for year in years)

    # Allow actual metric values from successful tool results.
    # Do not trust tool arguments, filters, errors, or arbitrary numbers.
    metric_fields = {
        "delivered_orders",
        "late_orders",
        "late_rate_pct",
        "avg_delivery_days",
        "delivered_count",
        "late_count",
        "late_rate_delta_pp",
    }

    def collect_metrics(data):
        if isinstance(data, dict):
            for key, value in data.items():
                if key in metric_fields and type(value) in (int, float):
                    allowed.add(float(value))
                elif isinstance(value, (dict, list)):
                    collect_metrics(value)

        elif isinstance(data, list):
            for value in data:
                collect_metrics(value)

    for event in trace or []:
        if "error" not in event.output:
            collect_metrics(event.output)


    pattern = re.compile(
        r"(?<![\w.])-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\w)"
    )
    removed = 0

    for field in ("summary", "evidence", "possible_explanations", "next_checks"):
        original = getattr(answer, field)
        items = [original] if isinstance(original, str) else original
        cleaned = []

        for item in items:
            # Normalize special thousands-separator spaces between digits.
            normalized = re.sub(
                r"(?<=\d)[\u00a0\u202f](?=\d{3}(?:\D|$))",
                "",
                item,
            )

            numbers = [
                float(m.group().replace(",", ""))
                for m in pattern.finditer(normalized)
            ]

            unsupported = [
                n for n in numbers
                if not any(
                    math.isclose(n, a, abs_tol=0.01, rel_tol=0)
                    for a in allowed
                )
            ]

            if any(
                not any(math.isclose(n, a, abs_tol=0.01, rel_tol=0)
                        for a in allowed)
                for n in numbers
            ):
                removed += 1
                if field == "summary":
                    cleaned.append("Numerical narrative withheld: unsupported by tool evidence.")
            else:
                cleaned.append(item)

        setattr(answer, field, cleaned[0] if isinstance(original, str) else cleaned)

    if removed:
        answer.limitations.append(
            f"{removed} narrative field(s) withheld due to unverified numbers."
        )

    return removed


def recover_no_data_evidence(
    answer: Investigation,
    trace: list[TraceEvent],
) -> None:
    """Cite successful tools that explicitly returned no matching data."""

    if answer.evidence:
        return

    for event in trace:
        if "error" in event.output:
            continue

        if event.tool == "delivery_kpis":
            result = event.output.get("result")

            if isinstance(result, dict) and result.get("delivered_orders") == 0:
                answer.evidence.append(
                    f"[{event.id}] delivery_kpis found 0 eligible delivered orders."
                )

        elif event.tool == "inspect_order":
            if "order" in event.output and event.output["order"] is None:
                answer.evidence.append(
                    f"[{event.id}] inspect_order found no matching order."
                )

def investigate(question: str, client=None, model: str | None = None,
                max_steps: int | None = None) -> AgentResult:
    """Run a bounded tool-calling investigation using Groq or a supplied test client.

    Supports approved historical delivery queries and structured evidence checks.
    This is a scoped research prototype, not an unrestricted text-to-SQL agent.
    """
    if not isinstance(question, str) or not 5 <= len(question.strip()) <= 1500:
        raise ValueError("Question must be 5–1500 characters")

    max_steps = 5 if max_steps is None else max_steps

    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or not 1 <= max_steps <= 10:
        raise ValueError("max_steps must be between 1 and 10")

    # Use the injected client for tests; otherwise connect to the configured provider.
    if client is None:
        if not os.getenv("GROQ_API_KEY"):
            raise RuntimeError("GROQ_API_KEY is missing")

        client = OpenAI(
            api_key=os.getenv("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1",
            timeout=25,
            max_retries=3
        )

    # 2. Select the model
    model = model or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    # 3. Prepare the conversation
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": question}
    ]

    # 4. Prepare tracking variables
    trace = []
    tokens_in = tokens_out = 0
    started = time.perf_counter()

    final = None

    for _ in range(max_steps):

        # 1. Ask the LLM what to do next
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOL_SPECS,
            tool_choice= "auto",
        )

        # 2. Track token usage
        if response.usage:
            tokens_in += response.usage.prompt_tokens or 0
            tokens_out += response.usage.completion_tokens or 0

        msg = response.choices[0].message
        # Handle responses with no tool calls safely.

        if not msg.tool_calls and not trace:
            try:
                final = Investigation.model_validate_json(msg.content or "")

            except (ValueError, TypeError):
                q = question.lower()

                # 1. Private customer information
                if re.search(r"\b(email|emails|address|addresses|phone)\b", q):
                    summary = (
                        "I cannot provide private customer contact details "
                        "or street addresses. I can analyze aggregate delivery metrics."
                    )

                # 2. Requests to modify data
                elif re.search(
                    r"\b(delete|drop|update|insert|modify|mark|refund|cancel)\b", q
                ):
                    summary = (
                        "Request refused: FulfillGuard is read-only. "
                        "No data were changed."
                    )

                # 3. Quarter mentioned without a year
                elif (
                    re.search(r"\bq[1-4]\b", q)
                    and not re.search(r"\b(?:19|20)\d{2}\b", q)
                ):
                    summary = (
                        "Which year are you referring to? "
                        "Please specify a year for the quarterly comparison."
                    )

                # 4. Other unsupported or unclear questions
                else:
                    summary = (
                        "I couldn't produce a verified analysis without an "
                        "analytical tool result. Please clarify your delivery question."
                    )

                final = Investigation(
                    summary=summary,
                    limitations=[
                        "No analytical tool was executed; "
                        "no numerical evidence was verified."
                    ],
                )

            break

        # 3. If no tool is requested, parse the final answer

        if not msg.tool_calls:
            try:
                final = Investigation.model_validate_json(msg.content or "{}")

            except ValueError:
                # The model returned text rather than valid JSON.
                # Make a separate request without tools to format the result.
                structured = client.chat.completions.create(
                    model=model,
                    messages=messages + [
                        {"role": "assistant", "content": msg.content or ""},
                        {
                            "role": "user",
                            "content": (
                                    "Return ONLY a valid JSON object matching this schema: "
                                    + json.dumps(Investigation.model_json_schema())
                                    + ". Base all factual claims on executed tool results. "
                                    "Do not invent evidence IDs or numerical values. "
                                    "If evidence is unavailable, acknowledge that limitation. "
                                    "Every evidence statement must begin with its tool ID, such as [T1]. "
                                    "Every numeric claim must reference the exact tool output path and value. "
                                    "Do not invent causes of delivery delays. "
                                    "Put unverified hypotheses in next_checks as investigation suggestions. "
                                    "The summary must directly answer the user's question using verified "
                                    "business metrics, not merely say that results are available. "
                                    "For breakdown questions, identify leading segments and report "
                                    "their relevant counts or rates. Distinguish absolute late counts "
                                    "from percentage late rates. For seller-state breakdowns, "
                                    "the observation unit is an order-seller pair, not a distinct order. "
                                    "Do not present possible causes as established findings."
                                )
                        }
                    ],
                    response_format={"type": "json_object"}
                )

                if structured.usage:
                    tokens_in += structured.usage.prompt_tokens or 0
                    tokens_out += structured.usage.completion_tokens or 0

                final = Investigation.model_validate_json(
                    structured.choices[0].message.content or "{}"
                )

            break

        # 4. Record the assistant's tool request
        messages.append(msg.model_dump(exclude_none=True))

        for call in msg.tool_calls:
            evidence_id = f"T{len(trace) + 1}"
            args = {}

            try:
                args = json.loads(call.function.arguments)
                output = execute_tool(call.function.name, args)

            except (ValueError, TypeError) as exc:
                output = {
                    "error": str(exc),
                    "type": "validation_error"
                }

            # 5. Save what the tool actually returned
            trace.append(TraceEvent(
                id=evidence_id,
                tool=call.function.name,
                arguments=args if isinstance(args, dict) else {},
                output=output
            ))

            # 6. Send the tool result back to the LLM
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps({
                    "evidence_id": evidence_id,
                    "data": output
                })
            })

    # 7. Handle an investigation without a final response
    if final is None:
        final = Investigation(
            summary="Investigation stopped before a final answer.",
            limitations=["Tool-call limit reached."]
        )

    # 8. Keep evidence only from successful tool executions
    allowed_ids = {t.id for t in trace if "error" not in t.output}

    final.evidence = [
        line for line in final.evidence
        if any(f"[{tid}]" in line for tid in allowed_ids)
    ]

    if trace and not allowed_ids:
        validation_errors = [
            event.output["error"]
            for event in trace
            if event.tool in TOOL_FUNCTIONS
            and event.output.get("type") == "validation_error"
            and isinstance(event.output.get("error"), str)
        ]

        if validation_errors:
            final.summary = f"Invalid input: {validation_errors[-1]}"
        else:
            final.summary = (
                "The investigation could not be completed: "
                "all tool executions failed."
            )

        final.numeric_claims = []
        final.possible_explanations = []
        final.limitations.append(
            "No successful analytical evidence was obtained."
        )

    # 9. Verify the LLM's numerical claims

    final.numeric_claims, rejected = check_claims(
        final.numeric_claims, trace
    )
    # Recover evidence descriptions from verified numerical claims.
    if not final.evidence or all(
        re.fullmatch(r"\[T\d+\]\s*", line.strip())
        for line in final.evidence
    ):
        verified_ids = {c.evidence_id for c in final.numeric_claims}

        final.evidence = [
            f"[{event.id}] Verified numerical claims against {event.tool} output."
            for event in trace
            if event.id in verified_ids and "error" not in event.output
        ]

    # Ground dataset-scope answers in successful metadata tools.
    if not final.evidence and not final.numeric_claims:
        final.evidence = [
            f"[{event.id}] Dataset metadata: {event.output['dataset']}"
            for event in trace
            if event.tool == "schema_info"
            and "error" not in event.output
            and isinstance(event.output.get("dataset"), str)
        ]
    recover_no_data_evidence(final, trace)
    removed = reconcile_narrative_numbers(final, question, trace)

    # 10. Return the investigation and engineering metrics
    return AgentResult(
        answer=final,
        trace=trace,
        elapsed_ms=round((time.perf_counter() - started) * 1000),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        model=model,
        numeric_claims_verified=len(final.numeric_claims),
        numeric_claims_rejected=rejected,
        narrative_numeric_issues=removed
    )
