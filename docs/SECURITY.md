# Security and data handling

## Data and credentials

- Do not commit `GROQ_API_KEY`, `.env`, `.pem`, database files, Kaggle downloads or local evaluation traces. The `.gitignore` covers common names; inspect before staging.
- The original Olist dataset and locally derived SQLite database are deliberately not bundled in this repository. Reconstruct them from the source dataset as described in README.
- Use only public, synthetic or properly authorized datasets. The prototype does not provide policy enforcement for confidential corporate information.

## Execution controls

- Queries use a read-only SQLite connection and parameter binding. User-selected breakdowns are restricted to predefined dimensions.
- `execute_tool` permits only named analytical tools; direct arbitrary SQL, file writes, data mutations, refunds, and contact-detail retrieval are unsupported.
- LLM instructions are **not** a security boundary by themselves. Code-side allowlists and database read-only access are needed regardless of prompt.

## Deployment boundaries

The sample API has **no authentication, per-user authorization, rate limiting, workload isolation or multi-tenant protections**. Run it on a local or otherwise controlled network only. Do not expose port 8000 directly to the public internet.

Provider error messages, tool traces and model prompts may contain user-supplied text. Avoid processing sensitive data and review logging and response handling before using the system beyond a controlled demonstration.

## Responsible disclosure

If you find a security problem in a hosted derivative, contact its operator privately rather than submitting credentials or private data in a public issue.
