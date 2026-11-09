# Evaluation: observed results and limitations

## What was measured

| Evaluation | Recorded outcome | Meaning |
|---|---|---|
| Python tests | **43/43 passed** locally on 2026-11-09 | SQL tools, fake-client agent flow, validation, API, safety regression tests |
| Deterministic baseline on imported Olist | **22/22** scenarios passed | Baseline's selected SQL calculations/routing matched an independent aggregate oracle |
| Live Groq LLM, 28 scenarios, recorded 2026-11-08/09 | **23/28** completed without exception | Requests that returned a completed result rather than an exception |
| Live expected-tool coverage | **60.7%** | Fraction matching prescribed tool routes in the historical run |
| Live evidence-reference validity | **67.9%** | Fraction passing the evaluator's evidence citation validity check |

These numbers are derived from the original local `eval/live_report.json` and `eval/baseline_olist_report.json` and the owner's 43-test terminal result. The generated per-run JSON reports are intentionally excluded from the GitHub source package; rerun locally to generate new reports. The scoring rules were subsequently revised, so **these historical numbers must not be represented as current post-change performance**.

**None of these percentages measure end-to-end factual answer accuracy.** The expected-tool benchmark is limited; the LLM model's actual response quality must be judged against separately computed ground truth. The scripted offline baseline is not a valid measure of LLM intelligence.

## Real-world failure discovered

A user asked: **“How did the number of orders change between 2016 and 2018?”** The LLM invoked the delivered-order `compare_periods` tool, which did not answer the requested total-order-volume trend. The numeric checker subsequently withheld the narrative. This demonstrated two weaknesses: limited analytical tool coverage and the verifier's inability to validate metric *meaning*, not just value.

Other observed weaknesses included inconsistent refusal formatting, unsupported numbers in generated narratives, tool-route mismatches, and rate-limit/provider response handling. These are the reason the project remains a scoped prototype.

## Repeat tests

```bash
python -m pytest tests/ -q
python -m scripts.make_fixture
FG_DB_PATH=data/demo.db python -m scripts.eval_baseline --output eval/baseline_report.json
```

After importing the external Olist dataset, the real-data deterministic baseline can be run with:

```bash
FG_DB_PATH=data/olist.db python -m scripts.eval_baseline --output eval/baseline_olist_report.json
```

Live evaluation requires an API key and the imported historical database. It makes multiple paid-or-quota-bounded external inference requests and includes deliberate delays to reduce rate-limit errors:

```bash
FG_DB_PATH=data/olist.db python -m scripts.run_evals --cases eval/cases.json --output eval/live_report.json
```

The strict `scripts/release_gate.py` checks live-model quality thresholds and requires **local, generated** reports; it is not expected to pass in a fresh public clone that intentionally excludes those files. It had **not cleared** at the last recorded evaluation. A clean GitHub source release and a mature production release are different milestones.

## Future evaluation

The follow-on generalized agent project will need unseen datasets, held-out questions, independent SQL oracles, adversarial paraphrases and spelling variations, multi-turn scenario scoring, and explicit semantic-metric correctness criteria. This repository retains the existing bounded V1 system rather than claiming those capabilities are already present.
