# Amazon Ops Analytics Pro

## Run locally

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

Local development uses SQLite. For durable hosted data, configure a dedicated
Supabase Postgres project for Amazon Ops; do not reuse PriceFlow's database.
The app creates and upgrades its tables when it connects. Uploaded report rows
are stored in Postgres; the original CSV/XLS/XLSX file is parsed in memory and
discarded after import.

## Configure hosted storage and sign-in

In Supabase, create a separate project and copy its Postgres session-pooler
connection string. In Streamlit Community Cloud, open the app's **Settings >
Secrets** and add the following TOML, replacing every placeholder. Register the
Streamlit redirect URL with your OIDC provider (Google is shown here).

```toml
database_url = "postgresql://USER:PASSWORD@HOST:5432/postgres?sslmode=require"
admin_emails = ["your-admin-email@example.com"]

[auth]
redirect_uri = "https://YOUR-APP.streamlit.app/oauth2callback"
cookie_secret = "GENERATE-A-LONG-RANDOM-SECRET"
client_id = "YOUR-OIDC-CLIENT-ID"
client_secret = "YOUR-OIDC-CLIENT-SECRET"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

The signed-in OIDC email must be in `admin_emails`. Keep secrets only in
Streamlit's secret store or a local `.streamlit/secrets.toml` (already ignored
by Git); never put database credentials in source code or browser JavaScript.
Private pages and uploads stay unavailable until both Postgres and OIDC admin
configuration are present.

## Data exposure

Anonymous visitors can see only the aggregate dashboard. Order-level, return-
level, search, audit, and upload tools require an authorized admin sign-in.
Never publish raw exports or customer comments. The uploader stores normalized
rows in the private database and does not archive original report files.
