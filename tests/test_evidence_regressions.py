from app.agent import (
    Investigation,
    NumericClaim,
    TraceEvent,
    check_claims,
    reconcile_narrative_numbers,
)


def make_answer(summary, claims=None):
    return Investigation(
        summary=summary,
        evidence=[],
        possible_explanations=[],
        next_checks=[],
        limitations=[],
        numeric_claims=claims or [],
    )


def test_evidence_paths():
    trace = [
        TraceEvent(
            id="T1",
            tool="breakdown",
            arguments={},
            output={"rows": [{"late_count": 100}]},
        )
    ]

    claims = [
        NumericClaim(evidence_id="T1", path="rows[0].late_count", value=100),
        NumericClaim(evidence_id="T1", path="data.rows[0].late_count", value=100),
        NumericClaim(evidence_id="T1", path="rows[0].late_count", value=999),
    ]

    valid, rejected = check_claims(claims, trace)

    assert len(valid) == 2
    assert rejected == 1


def test_thousands_separator():
    claims = [
        NumericClaim(evidence_id="T1", path="result.delivered_orders", value=6156),
        NumericClaim(evidence_id="T1", path="result.late_orders", value=208),
        NumericClaim(evidence_id="T1", path="result.late_rate_pct", value=3.38),
    ]

    answer = make_answer(
        "In July 2018, 208 out of 6,156 deliveries were late (3.38%).",
        claims,
    )

    removed = reconcile_narrative_numbers(
        answer, "What was the late-delivery rate in July 2018?"
    )

    assert removed == 0
    assert "6,156" in answer.summary


def test_metadata_year_range():
    trace = [
        TraceEvent(
            id="T1",
            tool="schema_info",
            arguments={},
            output={"dataset": "Olist E-Commerce (2016–2018)"},
        )
    ]

    valid = make_answer("The dataset covers 2016, 2017, and 2018.")
    invalid = make_answer("The dataset covers 2019.")

    assert reconcile_narrative_numbers(
        valid, "What years are covered?", trace
    ) == 0

    assert reconcile_narrative_numbers(
        invalid, "What years are covered?", trace
    ) == 1

    assert invalid.summary.startswith("Numerical narrative withheld")

def test_narrow_space_thousands_separator():
    claims = [
        NumericClaim(
            evidence_id="T1",
            path="result.delivered_orders",
            value=2712,
        ),
        NumericClaim(
            evidence_id="T1",
            path="result.late_rate_pct",
            value=3.69,
        ),
    ]

    answer = make_answer(
        "In July 2018, 2\u202f712 delivered orders had a 3.69% late rate.",
        claims,
    )

    removed = reconcile_narrative_numbers(
        answer,
        "How many delivered orders were there in July 2018?",
    )

    assert removed == 0

def test_tool_metric_missing_from_numeric_claims():
    trace = [
        TraceEvent(
            id="T1",
            tool="delivery_kpis",
            arguments={"limit": 999},
            output={
                "result": {
                    "delivered_orders": 644,
                    "late_orders": 8,
                    "late_rate_pct": 1.24,
                }
            },
        )
    ]

    claims = [
        NumericClaim(
            evidence_id="T1",
            path="result.late_rate_pct",
            value=1.24,
        )
    ]

    # 644 exists in SQL output but is absent from numeric_claims.
    valid = make_answer(
        "In July 2018, 8 out of 644 delivered orders were late (1.24%).",
        claims,
    )

    assert reconcile_narrative_numbers(
        valid, "What was the late rate in July 2018?", trace
    ) == 0

    # 999 appears only in tool arguments, not verified results.
    invalid = make_answer(
        "In July 2018, 999 delivered orders were late."
    )

    assert reconcile_narrative_numbers(
        invalid, "What was the late rate in July 2018?", trace
    ) == 1

def test_no_data_evidence_recovery():
    from app.agent import recover_no_data_evidence

    answer = make_answer("No eligible deliveries found.")

    trace = [
        TraceEvent(
            id="T1",
            tool="delivery_kpis",
            arguments={},
            output={"result": {"delivered_orders": 0}},
        )
    ]

    recover_no_data_evidence(answer, trace)

    assert len(answer.evidence) == 1
    assert answer.evidence[0].startswith("[T1]")

    # A refusal without executed tools must not invent evidence.
    refusal = make_answer("Request refused.")
    recover_no_data_evidence(refusal, [])

    assert refusal.evidence == []