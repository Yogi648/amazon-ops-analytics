# Amazon Ops Analytics Pro

## Run locally

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

## Upload access

Report uploads are disabled by default. To enable them for a trusted local
instance, set `$env:ALLOW_REPORT_UPLOADS = "true"` before starting Streamlit.
On Streamlit Community Cloud, the equivalent setting is
`allow_report_uploads = true` in the app's secrets. Do not enable uploads on an
anonymous public deployment.

Anyone who can open a public deployment can see its dashboard data. Use only
synthetic or sanitized data there; never upload Seller Central exports or
customer information to an anonymous app. A real seller dashboard needs
authentication and access-controlled, durable storage.
