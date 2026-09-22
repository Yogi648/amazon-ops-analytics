# Amazon Ops Analytics

Goal: build an Amazon Seller Central analytics system for sales, profit, returns,
reimbursement recovery, inventory, traffic and ASIN decisions.

Stack: Python 3.11+, DuckDB, Pandas, Streamlit, SQL.

Rules:
- Raw Amazon reports go under data/raw/<report_type>/.
- Never commit customer PII, credentials, tokens or raw reports.
- Loaders must be idempotent and must not duplicate rows on rerun.
- Keep raw source data separate from cleaned analytical tables.
- SKU is the primary product join key; use Order ID for transaction matching.
- Never hardcode credentials.
- Every metric must be traceable to source data.
- Verify one test month against Seller Central before trusting the dashboard.
