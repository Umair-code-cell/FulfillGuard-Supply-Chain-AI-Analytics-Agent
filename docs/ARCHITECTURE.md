# Architecture and technical design

## Objective and non-goals

FulfillGuard V1 is a scoped delivery-operations analytics prototype. The goal is to investigate historical purchase-date delivery performance with auditable numerical evidence. It does not autonomously synthesize SQL, connect to live logistics systems, or infer causal effects.

## Data pipeline

The loader reads four Olist CSV exports (`orders`, `customers`, `order_items`, `sellers`) into an indexed SQLite database with all imported columns stored as text. Atomic replacement and a local SHA-256 manifest accompany integrity checks for duplicate order IDs, missing customer references, and missing purchase timestamps. The demo fixture is generated separately and intentionally contains synthetic data.

The SQLite connection uses URI `mode=ro` and `PRAGMA query_only=ON`; tool query parameters are bound, and the breakdown dimension maps to fixed SQL expressions rather than accepting user SQL.

## Tool boundary

| Tool | Analytical operation |
|---|---|
| `delivery_kpis` | Eligible delivered-order counts, late counts, late percentages, average delivery days |
| `compare_periods` | Two purchase-date cohorts and difference in late-rate percentage points |
| `breakdown` | Segmentation by customer state, seller state, or purchase month |
| `inspect_order` | Selected non-contact fields for an order ID |
| `schema_info` | Available tool scope and dataset metadata |

The cohort consists of `order_status='delivered'` with non-null actual and estimated delivery dates; timeliness is determined by **calendar date of actual delivery > estimated delivery date**. The cohort is filtered by **purchase date**, not actual delivery date. `seller_state` aggregates one row per distinct order–seller pair; this is not the same as one row per order.

## Agent control flow

1. FastAPI validates the question and selects `llm` or `baseline` execution.
2. LLM mode prompts a Groq-hosted model with the bounded tool catalog and safety rules.
3. Each tool call is JSON-parsed, validated, executed through an allowlist, and stored as a numbered trace event.
4. The final model response is parsed into typed Pydantic objects. A follow-up structured-output request is used in some invalid-JSON cases.
5. Numeric claims are validated against successful tool-result paths. The narrative checker screens summary and explanation fields for unsupported numbers.
6. FastAPI returns answer, evidence, limitations, trace, latency, and token counters.

The no-model **offline baseline** routes a limited set of historical questions through the same read-only tools. It is a comparator, not the AI agent.

## Design tradeoffs

- **Allowlisted tools over general text-to-SQL:** simple auditable constraints and reduced write risk, in exchange for restricted analytical coverage.
- **Read-only SQLite:** reproducible and easy to run locally, but not representative of multi-tenant production data platforms.
- **Evidence-linked numeric claims:** catches many fabricated values and paths; does not establish the full semantic correctness of prose or causal inference.
- **Single-agent orchestration:** keeps debugging and traceability straightforward; tool selection remains sensitive to phrasing.
- **Live provider as optional dependency:** tests run with fake clients; live performance depends on model behavior and free API quota.

## Security boundary

The tool allowlist does not expose writes, arbitrary SQL, refund/payment tools, or contact-detail lookups. This does **not** make the web application safe to deploy publicly: there is no authentication, user authorization layer, tenant isolation, rate limiting, or prompt-injection guarantee. Use synthetic/public data and local execution.

## Reproduction

Follow the [README](../README.md), run the synthetic test fixture first, import the Kaggle data separately for real-data checks, then run the local test suite and the recorded evaluation harness. Historical evaluation metrics are documented in [EVALUATION.md](EVALUATION.md), without claiming these scores reflect universal question-answer accuracy.
