# Amazon Ops Analytics

## Setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python src\run_all.py
streamlit run dashboard\app.py
```

Load one month of Orders + Returns first and compare totals with Seller Central.
Then add settlements, reimbursements, inventory, traffic and ads.
