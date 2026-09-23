import sys
from pathlib import Path
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from db import connect, init_db
from ingest import ingest_report

try:
    import plotly.express as px
    import plotly.graph_objects as go
    PLOTLY_OK = True
except Exception:
    PLOTLY_OK = False

st.set_page_config(page_title="Amazon Ops Analytics Pro", page_icon="📦", layout="wide", initial_sidebar_state="expanded")
init_db()

# -----------------------------
# Professional UI
# -----------------------------
st.markdown(r"""
<style>
:root{--navy:#102746;--blue:#1476e8;--muted:#718096;--border:#e5eaf1;--bg:#f6f8fb}
.stApp{background:#f7f9fc;color:#152238}
.block-container{padding:0 1.4rem 2rem;max-width:100%}
section[data-testid="stSidebar"]{background:linear-gradient(180deg,#0e2340 0%,#142f50 100%);border-right:0}
section[data-testid="stSidebar"] *{color:#e9f1fb!important}
section[data-testid="stSidebar"] .stRadio label{padding:8px 10px;border-radius:9px;margin:2px 0}
section[data-testid="stSidebar"] .stRadio label:hover{background:rgba(255,255,255,.08)}
.brand{padding:16px 8px 18px;border-bottom:1px solid rgba(255,255,255,.12);margin-bottom:14px}
.brand-row{display:flex;align-items:center;gap:10px}.brand-logo{width:42px;height:42px;border-radius:12px;background:linear-gradient(135deg,#1685ef,#62b2ff);display:flex;align-items:center;justify-content:center;font-size:24px;box-shadow:0 6px 20px rgba(0,0,0,.18)}
.brand-title{font-size:18px;font-weight:800;line-height:1.05}.brand-sub{font-size:11px;opacity:.75;margin-top:3px}
.topbar{height:66px;background:white;border:1px solid var(--border);border-radius:0 0 14px 14px;padding:10px 16px;margin:0 -1.4rem 18px;box-shadow:0 3px 16px rgba(30,55,90,.06)}
.hero{background:linear-gradient(105deg,#eef7ff 0%,#ffffff 62%,#d9edff 100%);border:1px solid #d9e8f7;border-radius:16px;padding:22px 28px;margin-bottom:16px;overflow:hidden}
.hero h1{font-size:30px;margin:0;color:#122744;font-weight:800}.hero p{margin:5px 0 0;color:#60738d;font-size:14px}
.section-title{font-size:19px;font-weight:800;color:#18283f;margin:18px 0 10px}
.kpi{background:#fff;border:1px solid var(--border);border-radius:14px;padding:16px 17px;min-height:122px;box-shadow:0 3px 12px rgba(35,57,85,.045)}
.kpi-top{display:flex;align-items:center;gap:10px}.kpi-icon{width:40px;height:40px;border-radius:11px;display:flex;align-items:center;justify-content:center;font-size:20px}.kpi-label{font-size:12px;color:#64748b}.kpi-value{font-size:25px;font-weight:800;color:#13253e;margin-top:7px}.kpi-note{font-size:11px;color:#8a98aa;margin-top:4px}.good{color:#0ca678!important}.bad{color:#ef4444!important}
.card{background:#fff;border:1px solid var(--border);border-radius:14px;padding:15px 16px;box-shadow:0 3px 12px rgba(35,57,85,.045)}
.small-title{font-size:15px;font-weight:800;color:#17263d;margin-bottom:8px}
div[data-testid="stMetric"]{background:#fff;border:1px solid var(--border);border-radius:12px;padding:10px}
button[data-baseweb="tab"]{font-weight:600}
[data-testid="stDataFrame"]{border-radius:10px}
.stButton>button{border-radius:9px;font-weight:700}
hr{border-color:#e8edf3}
</style>
""", unsafe_allow_html=True)


def qdf(sql, params=None):
    con=connect()
    try:
        return pd.read_sql_query(sql, con, params=params or [])
    finally:
        con.close()


def scalar(sql, params=None):
    con=connect()
    try:
        row=con.execute(sql, params or []).fetchone()
        return row[0] if row and row[0] is not None else 0
    finally:
        con.close()


def cols(table):
    con=connect()
    try:
        return [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    finally:
        con.close()


def find_column(table, candidates):
    available=cols(table); low={c.lower():c for c in available}
    for c in candidates:
        if c.lower() in low: return low[c.lower()]
    return None


def ensure_return_analytics_columns():
    """Upgrade an existing database without deleting any return data."""
    con=connect()
    try:
        existing={r[1] for r in con.execute("PRAGMA table_info(returns)").fetchall()}
        upgrades={
            "return_request_status":"TEXT",
            "refunded_amount":"REAL",
            "safet_claim_id":"TEXT",
            "safet_claim_state":"TEXT",
            "safet_claim_reimbursement_amount":"REAL",
        }
        for name,typ in upgrades.items():
            if name not in existing:
                con.execute(f"ALTER TABLE returns ADD COLUMN {name} {typ}")
        con.commit()
    finally:
        con.close()


ensure_return_analytics_columns()

ORDERS_COLS=cols("orders")
ITEM_COLS=cols("order_items")
RET_COLS=cols("returns")
STATUS_COL=find_column("orders",["order_status","status","order_state"])
ORDER_DATE_COL=find_column("orders",["order_date","purchase_date","order_created_date"])
ACTIVE=f"COALESCE(LOWER(TRIM(o.{STATUS_COL})), '') NOT LIKE '%cancel%'" if STATUS_COL else "1=1"


def summary():
    rev=scalar(f"SELECT COALESCE(SUM(COALESCE(oi.item_price,0)),0) FROM order_items oi JOIN orders o ON o.order_id=oi.order_id WHERE {ACTIVE}")
    orders=scalar(f"SELECT COUNT(DISTINCT o.order_id) FROM orders o WHERE {ACTIVE}")
    units=scalar(f"SELECT COALESCE(SUM(oi.quantity),0) FROM order_items oi JOIN orders o ON o.order_id=oi.order_id WHERE {ACTIVE}")
    rs=return_summary()
    returns=int(rs.iloc[0]["return_units"]) if not rs.empty else 0
    cancelled=scalar(f"SELECT COUNT(*) FROM orders o WHERE COALESCE(LOWER(TRIM(o.{STATUS_COL or 'order_status'})),'') LIKE '%cancel%'") if STATUS_COL or 'order_status' in ORDERS_COLS else 0
    return float(rev),int(orders),int(units),int(returns),int(cancelled)


def sales_daily():
    if not ORDER_DATE_COL: return pd.DataFrame()
    return qdf(f"""SELECT o.{ORDER_DATE_COL} order_date, COUNT(DISTINCT o.order_id) orders, COALESCE(SUM(oi.quantity),0) units, COALESCE(SUM(oi.item_price),0) revenue FROM orders o JOIN order_items oi ON o.order_id=oi.order_id WHERE {ACTIVE} GROUP BY o.{ORDER_DATE_COL} ORDER BY o.{ORDER_DATE_COL}""")


def asin_sales():
    return qdf(f"""SELECT oi.asin, oi.sku, COALESCE(SUM(oi.quantity),0) units, COALESCE(SUM(oi.item_price),0) revenue FROM order_items oi JOIN orders o ON o.order_id=oi.order_id WHERE {ACTIVE} GROUP BY oi.asin,oi.sku ORDER BY revenue DESC""")


def return_status_condition(alias="r"):
    status_col=find_column("returns",["return_request_status","return_status","status"])
    if not status_col:
        return "1=1"
    return f"COALESCE(LOWER(TRIM({alias}.{status_col})),'') NOT LIKE '%closed%'"


def return_cte():
    """Build the duplicate-safe return dataset used by every return analysis.

    Rules:
      * same Order ID + ASIN = one return
      * closed return requests are excluded
      * if duplicate rows exist, a non-zero refund is preferred and counted once
      * Safe-T reimbursement is counted separately, once per Order ID + ASIN
    """
    refund_col=find_column("returns",["refunded_amount","refund_amount","refunded"])
    safet_col=find_column("returns",["safet_claim_reimbursement_amount","safe_t_claim_reimbursement_amount","safet_reimbursement_amount"])
    refund_expr=f"COALESCE(r.{refund_col},0)" if refund_col else "0"
    safet_expr=f"COALESCE(r.{safet_col},0)" if safet_col else "0"
    return f"""
    WITH base AS (
        SELECT
            r.rowid AS _rowid,
            r.*,
            COALESCE({refund_expr},0) AS _refund,
            COALESCE({safet_expr},0) AS _safet
        FROM returns r
        WHERE {return_status_condition('r')}
    ), ranked AS (
        SELECT
            base.*,
            ROW_NUMBER() OVER (
                PARTITION BY COALESCE(order_id,''), COALESCE(asin,'')
                ORDER BY
                    CASE WHEN _refund > 0 THEN 0 ELSE 1 END,
                    CASE WHEN _safet > 0 THEN 0 ELSE 1 END,
                    CASE WHEN return_date IS NULL OR return_date='' THEN 1 ELSE 0 END,
                    return_date DESC,
                    _rowid DESC
            ) AS _rn,
            MAX(_refund) OVER (
                PARTITION BY COALESCE(order_id,''), COALESCE(asin,'')
            ) AS _refund_selected,
            MAX(_safet) OVER (
                PARTITION BY COALESCE(order_id,''), COALESCE(asin,'')
            ) AS _safet_selected
        FROM base
    )
    """


def return_asin():
    return qdf(return_cte()+"""
        SELECT
            COALESCE(asin,'') AS asin,
            MAX(COALESCE(sku,'')) AS sku,
            COUNT(*) AS return_units,
            COALESCE(SUM(_refund_selected),0) AS refunded_amount,
            COALESCE(SUM(_safet_selected),0) AS safet_claim_amount
        FROM ranked
        WHERE _rn=1
        GROUP BY COALESCE(asin,'')
        ORDER BY return_units DESC, refunded_amount DESC
    """)


def return_summary():
    return qdf(return_cte()+"""
        SELECT
            COUNT(*) AS return_units,
            COUNT(DISTINCT order_id) AS return_orders,
            COALESCE(SUM(_refund_selected),0) AS refunded_amount,
            COALESCE(SUM(_safet_selected),0) AS safet_claim_amount
        FROM ranked
        WHERE _rn=1
    """)


def safet_claims_by_asin():
    return qdf(return_cte()+"""
        SELECT
            COALESCE(asin,'') AS asin,
            MAX(COALESCE(sku,'')) AS sku,
            COUNT(*) AS claim_returns,
            COALESCE(SUM(_safet_selected),0) AS safet_claim_amount
        FROM ranked
        WHERE _rn=1 AND _safet_selected > 0
        GROUP BY COALESCE(asin,'')
        ORDER BY safet_claim_amount DESC
    """)


def return_reasons(asin=None):
    reason_col=find_column("returns",["reason","return_reason"])
    if not reason_col: return pd.DataFrame()
    sql=return_cte()+f"""
        SELECT COALESCE(NULLIF(TRIM({reason_col}),''),'Unknown') AS reason,
               COUNT(*) AS return_units
        FROM ranked
        WHERE _rn=1
    """
    params=[]
    if asin:
        sql+=" AND UPPER(COALESCE(asin,''))=UPPER(?)"; params=[str(asin)]
    sql+=" GROUP BY COALESCE(NULLIF(TRIM("+reason_col+"),''),'Unknown') ORDER BY return_units DESC"
    return qdf(sql,params)


def locations():
    pc=find_column("orders",["ship_postal_code","ship_pincode","ship_pin_code","postal_code","pincode","pin_code","zip"])
    city=find_column("orders",["ship_city","shipping_city","city"])
    if not pc:return pd.DataFrame(),None
    if city:
        sql=return_cte()+f"""
            SELECT COALESCE(NULLIF(TRIM(o.{city}),''),'Unknown') city,
                   COALESCE(NULLIF(TRIM(o.{pc}),''),'Unknown') pincode,
                   COUNT(*) return_units
            FROM ranked r JOIN orders o ON o.order_id=r.order_id
            WHERE r._rn=1
            GROUP BY COALESCE(NULLIF(TRIM(o.{city}),''),'Unknown'),COALESCE(NULLIF(TRIM(o.{pc}),''),'Unknown')
            ORDER BY return_units DESC LIMIT 30
        """
    else:
        sql=return_cte()+f"""
            SELECT COALESCE(NULLIF(TRIM(o.{pc}),''),'Unknown') pincode,
                   COUNT(*) return_units
            FROM ranked r JOIN orders o ON o.order_id=r.order_id
            WHERE r._rn=1
            GROUP BY COALESCE(NULLIF(TRIM(o.{pc}),''),'Unknown')
            ORDER BY return_units DESC LIMIT 30
        """
    return qdf(sql),pc


def state_returns():
    c=find_column("orders",["ship_state","shipping_state","state"])
    if not c:return pd.DataFrame()
    return qdf(return_cte()+f"""
        SELECT COALESCE(NULLIF(TRIM(o.{c}),''),'Unknown') state,
               COUNT(*) return_units
        FROM ranked r JOIN orders o ON o.order_id=r.order_id
        WHERE r._rn=1
        GROUP BY COALESCE(NULLIF(TRIM(o.{c}),''),'Unknown')
        ORDER BY return_units DESC
    """)


def city_returns():
    c=find_column("orders",["ship_city","shipping_city","city"])
    if not c:return pd.DataFrame()
    return qdf(return_cte()+f"""
        SELECT COALESCE(NULLIF(TRIM(o.{c}),''),'Unknown') city,
               COUNT(*) return_units
        FROM ranked r JOIN orders o ON o.order_id=r.order_id
        WHERE r._rn=1
        GROUP BY COALESCE(NULLIF(TRIM(o.{c}),''),'Unknown')
        ORDER BY return_units DESC LIMIT 30
    """)

def scorecard():
    s=asin_sales(); r=return_asin()
    if s.empty:return pd.DataFrame()
    # Return logic is ASIN-based because the duplicate rule is Order ID + ASIN.
    # Aggregate sales to ASIN before calculating the return rate so multiple SKUs
    # belonging to one ASIN do not split the return signal.
    s2=s.groupby("asin",dropna=False,as_index=False).agg(
        sku=("sku",lambda x: ", ".join(sorted(set(str(v) for v in x if str(v) not in ("", "nan")))[:3])),
        units=("units","sum"),
        revenue=("revenue","sum")
    )
    d=s2.merge(r.drop(columns=["sku"],errors="ignore"),on="asin",how="left")
    d["return_units"]=pd.to_numeric(d["return_units"],errors="coerce").fillna(0)
    d["refunded_amount"]=pd.to_numeric(d.get("refunded_amount",0),errors="coerce").fillna(0)
    d["safet_claim_amount"]=pd.to_numeric(d.get("safet_claim_amount",0),errors="coerce").fillna(0)
    d["return_rate"]=(d.return_units/d.units.replace(0,pd.NA)*100).fillna(0)
    d["decision"]=d.apply(lambda x:"🔴 High Return" if x.return_rate>=15 and x.return_units>=3 else ("🟡 Watch" if x.return_rate>=8 and x.return_units>=2 else "🟢 Good"),axis=1)
    return d.sort_values(["return_rate","return_units"],ascending=False)


def asin_location_data(asin):
    pc=find_column("orders",["ship_postal_code","ship_pincode","ship_pin_code","postal_code","pincode","pin_code","zip"])
    if not pc:return pd.DataFrame(),None
    return qdf(return_cte()+f"""
        SELECT COALESCE(NULLIF(TRIM(o.{pc}),''),'Unknown') pincode,
               COUNT(*) return_units
        FROM ranked r JOIN orders o ON o.order_id=r.order_id
        WHERE r._rn=1 AND UPPER(COALESCE(r.asin,''))=UPPER(?)
        GROUP BY COALESCE(NULLIF(TRIM(o.{pc}),''),'Unknown')
        ORDER BY return_units DESC LIMIT 30
    """,[str(asin)]),pc

def money(v): return f"₹{v:,.0f}"

def chart(fig):
    if PLOTLY_OK: st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})

# Sidebar
with st.sidebar:
    st.markdown('<div class="brand"><div class="brand-row"><div class="brand-logo">📦</div><div><div class="brand-title">Amazon Ops</div><div class="brand-sub">Analytics Pro</div></div></div></div>',unsafe_allow_html=True)
    page=st.radio("Module",["Dashboard","Orders","Returns","ASIN Search","Sales Intelligence","Return Intelligence","Location Analysis","ASIN Scorecard","Upload Center","Data Audit","Reports"],label_visibility="collapsed")
    st.markdown('<div style="margin-top:30px;padding:15px;border-radius:13px;background:rgba(255,255,255,.08)"><b>Keep Growing</b><br><span style="font-size:12px;opacity:.75">Data Driven<br>Better Decisions</span></div>',unsafe_allow_html=True)

# top bar
rev,orders,units,returns,cancelled=summary(); rate=returns/units*100 if units else 0
st.markdown('<div class="topbar">',unsafe_allow_html=True)
t1,t2,t3=st.columns([3.5,1.5,1])
with t1:
    global_search=st.text_input("Global search",placeholder="Search by ASIN, SKU, Order ID, Product name...",label_visibility="collapsed")
with t2:
    st.date_input("Date range",value=(pd.Timestamp("2026-08-01").date(),pd.Timestamp("2026-08-31").date()),label_visibility="collapsed")
with t3:
    st.markdown('<div style="text-align:right;padding-top:7px;font-weight:700;color:#24364f">YK &nbsp; Yogesh Kumar<br><span style="font-size:11px;color:#8492a6;font-weight:400">Admin</span></div>',unsafe_allow_html=True)
st.markdown('</div>',unsafe_allow_html=True)

if page=="Dashboard":
    st.markdown('<div class="hero"><h1>Welcome Back,</h1><h1>Amazon Ops Analytics Pro</h1><p>Sales intelligence • Return intelligence • ASIN performance • Location analysis</p></div>',unsafe_allow_html=True)
    st.markdown('<div class="section-title">Executive Overview</div>',unsafe_allow_html=True)
    vals=[("🛒","Total Revenue",money(rev),"Non-cancelled orders","blue"),("📦","Valid Orders",f"{orders:,}","Cancelled excluded","green"),("🛍️","Units Sold",f"{units:,}","Non-cancelled orders","purple"),("↩️","Return Units",f"{returns:,}","Imported returns","orange"),("%","Return Rate",f"{rate:.2f}%","Returns ÷ sold units","pink")]
    for c,(ic,l,v,n,col) in zip(st.columns(5),vals):
        with c: st.markdown(f'<div class="kpi"><div class="kpi-top"><div class="kpi-icon" style="background:#edf5ff">{ic}</div><div class="kpi-label">{l}</div></div><div class="kpi-value">{v}</div><div class="kpi-note">{n}</div></div>',unsafe_allow_html=True)
    st.markdown('<div class="section-title">Sales & Order Performance</div>',unsafe_allow_html=True)
    c1,c2=st.columns([1.65,1])
    d=sales_daily()
    with c1:
        st.markdown('<div class="card"><div class="small-title">📊 Sales Trend</div>',unsafe_allow_html=True)
        if not d.empty:
            d["order_date"]=pd.to_datetime(d.order_date,errors="coerce"); d=d.dropna(subset=["order_date"])
            if PLOTLY_OK:
                fig=px.area(d,x="order_date",y="revenue",markers=True); fig.update_traces(line_color="#1677e8",fillcolor="rgba(22,119,232,.12)"); fig.update_layout(height=320,margin=dict(l=10,r=10,t=10,b=10),paper_bgcolor="white",plot_bgcolor="white",xaxis_title=None,yaxis_title=None)
                chart(fig)
            else: st.line_chart(d.set_index("order_date").revenue)
        else: st.info("No sales trend data available.")
        st.markdown('</div>',unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="card"><div class="small-title">🍩 Order Status</div>',unsafe_allow_html=True)
        if STATUS_COL:
            os=qdf(f"SELECT CASE WHEN LOWER(TRIM({STATUS_COL})) LIKE '%cancel%' THEN 'Cancelled' WHEN LOWER(TRIM({STATUS_COL})) LIKE '%ship%' THEN 'Shipped' WHEN LOWER(TRIM({STATUS_COL})) LIKE '%return%' THEN 'Returned' ELSE 'Processing' END status,COUNT(DISTINCT order_id) orders FROM orders GROUP BY 1")
        else: os=pd.DataFrame()
        if not os.empty and PLOTLY_OK:
            fig=px.pie(os,names="status",values="orders",hole=.62); fig.update_layout(height=320,margin=dict(l=5,r=5,t=10,b=10),showlegend=True)
            chart(fig)
        else: st.dataframe(os,width="stretch",hide_index=True)
        st.markdown('</div>',unsafe_allow_html=True)
    st.markdown('<div class="section-title">Product & Return Intelligence</div>',unsafe_allow_html=True)
    a=asin_sales(); r=return_reasons();
    c1,c2=st.columns([1.65,1])
    with c1:
        st.markdown('<div class="card"><div class="small-title">🏆 Top Selling ASINs</div>',unsafe_allow_html=True)
        x=a.head(10).copy()
        if not x.empty:
            x=x.rename(columns={"asin":"ASIN","sku":"SKU","units":"Units Sold","revenue":"Revenue"}); x["Revenue"]=x["Revenue"].map(money); st.dataframe(x,width="stretch",hide_index=True)
        else: st.info("No sales data.")
        st.markdown('</div>',unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="card"><div class="small-title">↩️ Returns by Reason</div>',unsafe_allow_html=True)
        if not r.empty and PLOTLY_OK:
            fig=px.bar(r.head(8).sort_values("return_units"),x="return_units",y="reason",orientation="h"); fig.update_layout(height=310,margin=dict(l=5,r=5,t=5,b=5),xaxis_title=None,yaxis_title=None)
            chart(fig)
        else: st.dataframe(r,width="stretch",hide_index=True)
        st.markdown('</div>',unsafe_allow_html=True)
    c1,c2,c3=st.columns(3)
    for container,title,df in [(c1,"📊 Sales by Category",a.groupby(a.sku.fillna("Unknown").astype(str).str[:12]).units.sum().reset_index(name="units")),(c2,"↩️ Top Return ASINs",return_asin().head(8)),(c3,"📍 Orders by State",state_returns().head(8))]:
        with container:
            st.markdown(f'<div class="card"><div class="small-title">{title}</div>',unsafe_allow_html=True); st.dataframe(df,width="stretch",hide_index=True); st.markdown('</div>',unsafe_allow_html=True)

elif page=="ASIN Search":
    st.markdown('<div class="hero"><h1>🔎 ASIN Search & Product Analysis</h1><p>Search an ASIN and view sales, returns, reasons and location hotspots.</p></div>',unsafe_allow_html=True)
    q=st.text_input("Enter ASIN",value=global_search if global_search and global_search.upper().startswith("B") else "",placeholder="B0XXXXXXXX")
    if q:
        s=asin_sales(); m=s[s.asin.astype(str).str.upper()==q.strip().upper()] if not s.empty else pd.DataFrame()
        if m.empty: st.error(f"No sales record found for ASIN: {q}")
        else:
            asin=m.iloc[0].asin; u=int(m.units.sum()); rv=float(m.revenue.sum()); rr=return_asin(); rr=rr[rr.asin.astype(str)==str(asin)]; ru=int(rr.return_units.sum()) if not rr.empty else 0; rate2=ru/u*100 if u else 0
            st.markdown('<div class="section-title">Product Overview</div>',unsafe_allow_html=True)
            for c,(l,v) in zip(st.columns(4),[("ASIN",asin),("Units Sold",f"{u:,}"),("Revenue",money(rv)),("Return Rate",f"{rate2:.2f}%")]): c.metric(l,v)
            t1,t2,t3=st.tabs(["Sales","Return Reasons","Return Pincodes"])
            with t1: st.dataframe(m,width="stretch",hide_index=True)
            with t2:
                z=return_reasons(asin)
                if not z.empty and PLOTLY_OK: chart(px.bar(z.sort_values("return_units"),x="return_units",y="reason",orientation="h"))
                else: st.dataframe(z,width="stretch",hide_index=True)
            with t3:
                z,pc=asin_location_data(asin)
                if not z.empty and PLOTLY_OK: chart(px.bar(z.head(15).sort_values("return_units"),x="return_units",y="pincode",orientation="h"))
                st.dataframe(z,width="stretch",hide_index=True)
    else: st.info("Enter an ASIN to start the analysis.")

elif page=="Sales Intelligence":
    st.markdown('<div class="hero"><h1>Sales Intelligence</h1><p>Amazon item-price is used as Sale Price. Item tax is not added to Sale Price.</p></div>',unsafe_allow_html=True)
    d=asin_sales(); search=st.text_input("Search ASIN / SKU",value=global_search)
    if search and not d.empty: d=d[d.astype(str).apply(lambda col: col.str.contains(search,case=False,na=False)).any(axis=1)]
    st.dataframe(d,width="stretch",hide_index=True); st.download_button("Download Sales CSV",d.to_csv(index=False).encode(),"sales_analysis.csv","text/csv")

elif page=="Return Intelligence":
    st.markdown('<div class="hero"><h1>Return Intelligence</h1><p>Duplicate-safe returns, refunds and Safe-T reimbursement analysis.</p></div>',unsafe_allow_html=True)
    rs=return_summary(); rr=return_reasons(); a=return_asin(); sc=safet_claims_by_asin()
    total_returns=int(rs.iloc[0]["return_units"]) if not rs.empty else 0
    total_refund=float(rs.iloc[0]["refunded_amount"]) if not rs.empty else 0
    total_safet=float(rs.iloc[0]["safet_claim_amount"]) if not rs.empty else 0
    c1,c2,c3=st.columns(3)
    c1.metric("Unique Returns",f"{total_returns:,}")
    c2.metric("Refunded Amount",money(total_refund))
    c3.metric("Safe-T Claim Amount",money(total_safet))
    st.info("Rule applied: same Order ID + ASIN = one return. Closed return requests are excluded. For duplicate rows, a non-zero refund is preferred and counted once. Safe-T reimbursement is tracked separately and counted once per Order ID + ASIN.")
    c1,c2=st.columns(2)
    with c1:
        st.markdown('<div class="card"><div class="small-title">Returns by Reason</div>',unsafe_allow_html=True)
        if not rr.empty and PLOTLY_OK: chart(px.pie(rr.head(12),names="reason",values="return_units",hole=.45))
        st.dataframe(rr,width="stretch",hide_index=True); st.markdown('</div>',unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="card"><div class="small-title">Top Return ASINs</div>',unsafe_allow_html=True)
        if not a.empty and PLOTLY_OK: chart(px.bar(a.head(12).sort_values("return_units"),x="return_units",y="asin",orientation="h"))
        st.dataframe(a,width="stretch",hide_index=True); st.markdown('</div>',unsafe_allow_html=True)
    st.subheader("Safe-T Claims by ASIN")
    st.dataframe(sc,width="stretch",hide_index=True)
    st.subheader("ASIN Return Decision Scorecard"); st.dataframe(scorecard(),width="stretch",hide_index=True)

elif page=="Location Analysis":
    st.markdown('<div class="hero"><h1>📍 Location Intelligence</h1><p>Identify states, cities and pincodes with higher return activity.</p></div>',unsafe_allow_html=True)
    p,pc=locations(); sr=state_returns(); cr=city_returns(); c1,c2=st.columns(2)
    with c1:
        st.markdown('<div class="card"><div class="small-title">Returns by State</div>',unsafe_allow_html=True)
        if not sr.empty and PLOTLY_OK: chart(px.bar(sr.head(15).sort_values("return_units"),x="return_units",y="state",orientation="h"))
        st.dataframe(sr.head(20),width="stretch",hide_index=True); st.markdown('</div>',unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="card"><div class="small-title">Returns by City</div>',unsafe_allow_html=True)
        if not cr.empty and PLOTLY_OK: chart(px.bar(cr.head(15).sort_values("return_units"),x="return_units",y="city",orientation="h"))
        st.dataframe(cr.head(20),width="stretch",hide_index=True); st.markdown('</div>',unsafe_allow_html=True)
    st.subheader("Top Return Pincodes / Cities"); st.dataframe(p,width="stretch",hide_index=True)

elif page=="ASIN Scorecard":
    st.markdown('<div class="hero"><h1>🏆 ASIN Product Decision Scorecard</h1><p>Prioritize products using sales volume and return-rate signals.</p></div>',unsafe_allow_html=True)
    s=scorecard();
    if s.empty: st.info("No sales/return data available.")
    else:
        a,b,c=st.columns(3); a.metric("High Return ASINs",int((s.decision=="🔴 High Return").sum())); b.metric("Watch ASINs",int((s.decision=="🟡 Watch").sum())); c.metric("Good ASINs",int((s.decision=="🟢 Good").sum())); st.dataframe(s,width="stretch",hide_index=True)

elif page=="Upload Center":
    st.markdown('<div class="hero"><h1>☁ Upload Center</h1><p>Import Amazon Orders and Returns reports into the analytics database.</p></div>',unsafe_allow_html=True)
    typ=st.selectbox("Report Type",["Orders","Returns"]); f=st.file_uploader("Choose Amazon report",type=["txt","tsv","csv","xlsx","xls"])
    if f and st.button("Validate & Import",type="primary"):
        try:
            result=ingest_report(f,typ); st.success(result.get("message","Import completed.")); st.json(result); st.rerun()
        except Exception as e: st.error(f"Import failed: {e}")

elif page=="Data Audit":
    st.markdown('<div class="hero"><h1>Data Audit</h1><p>Database quality and import controls.</p></div>',unsafe_allow_html=True)
    audit=pd.DataFrame([{"All Orders":scalar("SELECT COUNT(*) FROM orders"),"Active Orders":scalar(f"SELECT COUNT(*) FROM orders o WHERE {ACTIVE}"),"Cancelled Orders":cancelled,"Order Items":scalar("SELECT COUNT(*) FROM order_items"),"Returns":scalar("SELECT COUNT(*) FROM returns")}])
    st.dataframe(audit,width="stretch",hide_index=True); st.info("Cancelled orders remain available for audit but are excluded from sales analytics.")
    st.subheader("Database Columns"); st.json({"orders":ORDERS_COLS,"order_items":ITEM_COLS,"returns":RET_COLS})

elif page=="Orders":
    st.markdown('<div class="hero"><h1>Orders</h1><p>Order-level operational view. Cancelled orders are retained for audit.</p></div>',unsafe_allow_html=True)
    order_id=find_column("orders",["order_id"])
    df=qdf("SELECT * FROM orders ORDER BY rowid DESC LIMIT 1000")
    if global_search and not df.empty: df=df[df.astype(str).apply(lambda x:x.str.contains(global_search,case=False,na=False)).any(axis=1)]
    st.dataframe(df,width="stretch",hide_index=True)

elif page=="Returns":
    st.markdown('<div class="hero"><h1>Returns</h1><p>Duplicate-safe return report. Same Order ID + ASIN is treated as one return.</p></div>',unsafe_allow_html=True)
    df=qdf(return_cte()+"""
        SELECT order_id, asin, MAX(COALESCE(sku,'')) sku,
               1 AS return_count,
               MAX(COALESCE(quantity,1)) source_quantity,
               MAX(COALESCE(reason,'')) reason,
               MAX(COALESCE(return_request_status,'')) return_request_status,
               MAX(_refund_selected) refunded_amount,
               MAX(_safet_selected) safet_claim_reimbursement_amount
        FROM ranked
        WHERE _rn=1
        GROUP BY order_id, asin
        ORDER BY MAX(_rowid) DESC
        LIMIT 2000
    """)
    if global_search and not df.empty: df=df[df.astype(str).apply(lambda x:x.str.contains(global_search,case=False,na=False)).any(axis=1)]
    st.dataframe(df,width="stretch",hide_index=True)
    st.caption("Closed return requests are excluded. Refund and Safe-T amounts are not double-counted when Amazon provides duplicate rows for the same Order ID + ASIN.")

else:
    st.markdown('<div class="hero"><h1>Reports</h1><p>Export operational analysis for management review.</p></div>',unsafe_allow_html=True)
    s=scorecard(); loc,_=locations(); a=asin_sales()
    for name,df in [("ASIN Scorecard",s),("Sales by ASIN",a),("Return Locations",loc)]:
        st.subheader(name); st.download_button(f"Download {name} CSV",df.to_csv(index=False).encode(),name.lower().replace(" ","_")+".csv","text/csv"); st.dataframe(df.head(100),width="stretch",hide_index=True)
