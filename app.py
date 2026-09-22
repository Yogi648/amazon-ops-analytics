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
    PLOTLY_OK = True
except Exception:
    PLOTLY_OK = False

st.set_page_config(
    page_title="Amazon Ops Analytics Pro",
    page_icon="📊",
    layout="wide"
)

init_db()

st.markdown("""
<style>
.block-container{padding-top:1.2rem}
.hero{padding:22px 26px;border-radius:16px;background:linear-gradient(135deg,#111827,#26354d);color:white;margin-bottom:20px}
.hero h1{margin:0;font-size:34px}.hero p{margin:6px 0 0;opacity:.82}
.kpi{border:1px solid #e5e7eb;border-radius:14px;padding:16px;background:white;min-height:105px}
.kpi-label{font-size:13px;color:#6b7280}.kpi-value{font-size:27px;font-weight:700;margin-top:5px}.kpi-note{font-size:12px;color:#6b7280}
</style>
""", unsafe_allow_html=True)


def qdf(sql, params=None):
    con = connect()
    try:
        return pd.read_sql_query(sql, con, params=params or [])
    finally:
        con.close()


def scalar(sql, params=None):
    con = connect()
    try:
        row = con.execute(sql, params or []).fetchone()
        return row[0] if row and row[0] is not None else 0
    finally:
        con.close()


def cols(table):
    con = connect()
    try:
        return [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    finally:
        con.close()


# Cancelled orders are retained in the database for audit,
# but excluded from sales analytics.
ACTIVE = """
COALESCE(LOWER(TRIM(o.order_status)), '') NOT LIKE '%cancel%'
"""


def find_column(table, candidates):
    available = cols(table)
    lower_map = {c.lower(): c for c in available}

    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]

    return None


def summary():
    rev = scalar(f"""
        SELECT COALESCE(
            SUM(COALESCE(oi.item_price,0)), 0
        )
        FROM order_items oi
        JOIN orders o ON o.order_id = oi.order_id
        WHERE {ACTIVE}
    """)

    orders = scalar(f"""
        SELECT COUNT(DISTINCT o.order_id)
        FROM orders o
        WHERE {ACTIVE}
    """)

    units = scalar(f"""
        SELECT COALESCE(SUM(oi.quantity),0)
        FROM order_items oi
        JOIN orders o ON o.order_id = oi.order_id
        WHERE {ACTIVE}
    """)

    returns = scalar("""
        SELECT COALESCE(SUM(quantity),0)
        FROM returns
    """)

    return float(rev), int(orders), int(units), int(returns)


def sales_daily():
    return qdf(f"""
        SELECT
            o.order_date,
            COUNT(DISTINCT o.order_id) AS orders,
            SUM(oi.quantity) AS units,
            SUM(COALESCE(oi.item_price,0)) AS revenue
        FROM orders o
        JOIN order_items oi ON o.order_id = oi.order_id
        WHERE {ACTIVE}
        GROUP BY o.order_date
        ORDER BY o.order_date
    """)


def asin_sales():
    return qdf(f"""
        SELECT
            oi.asin,
            oi.sku,
            SUM(oi.quantity) AS units,
            SUM(COALESCE(oi.item_price,0)) AS revenue
        FROM order_items oi
        JOIN orders o ON o.order_id = oi.order_id
        WHERE {ACTIVE}
        GROUP BY oi.asin, oi.sku
        ORDER BY revenue DESC
    """)


def return_asin():
    return qdf("""
        SELECT
            asin,
            sku,
            SUM(quantity) AS return_units
        FROM returns
        GROUP BY asin, sku
        ORDER BY SUM(quantity) DESC
    """)


def return_reasons():
    if "reason" not in cols("returns"):
        return pd.DataFrame()

    return qdf("""
        SELECT
            COALESCE(NULLIF(TRIM(reason),''),'Unknown') AS reason,
            SUM(quantity) AS return_units
        FROM returns
        GROUP BY COALESCE(NULLIF(TRIM(reason),''),'Unknown')
        ORDER BY SUM(quantity) DESC
    """)


def locations():
    """
    Return hotspots using the shipping fields imported from the Amazon
    order report: ship-city and ship-postal-code.
    """
    oc = cols("orders")

    pc = find_column(
        "orders",
        [
            "ship_postal_code",
            "ship_pincode",
            "ship_pin_code",
            "postal_code",
            "pincode",
            "pin_code",
            "zip"
        ]
    )

    city_col = find_column(
        "orders",
        ["ship_city", "shipping_city", "city"]
    )

    if not pc:
        return pd.DataFrame(), None

    if city_col:
        result = qdf(f"""
            SELECT
                COALESCE(NULLIF(TRIM(o.{city_col}),''),'Unknown') AS city,
                COALESCE(NULLIF(TRIM(o.{pc}),''),'Unknown') AS pincode,
                SUM(r.quantity) AS return_units
            FROM returns r
            JOIN orders o ON o.order_id = r.order_id
            GROUP BY
                COALESCE(NULLIF(TRIM(o.{city_col}),''),'Unknown'),
                COALESCE(NULLIF(TRIM(o.{pc}),''),'Unknown')
            ORDER BY SUM(r.quantity) DESC
            LIMIT 30
        """)
    else:
        result = qdf(f"""
            SELECT
                COALESCE(NULLIF(TRIM(o.{pc}),''),'Unknown') AS pincode,
                SUM(r.quantity) AS return_units
            FROM returns r
            JOIN orders o ON o.order_id = r.order_id
            GROUP BY COALESCE(NULLIF(TRIM(o.{pc}),''),'Unknown')
            ORDER BY SUM(r.quantity) DESC
            LIMIT 30
        """)

    return result, pc


def state_returns():

    state_col = find_column(
        "orders",
        ["ship_state", "shipping_state", "state"]
    )

    if not state_col:
        return pd.DataFrame()

    return qdf(f"""
        SELECT
            COALESCE(NULLIF(TRIM(o.{state_col}), ''), 'Unknown') AS state,
            SUM(r.quantity) AS return_units
        FROM returns r
        JOIN orders o ON o.order_id = r.order_id
        GROUP BY COALESCE(NULLIF(TRIM(o.{state_col}), ''), 'Unknown')
        ORDER BY SUM(r.quantity) DESC
    """)


def city_returns():
    city_col = find_column(
        "orders",
        ["ship_city", "shipping_city", "city"]
    )

    if not city_col:
        return pd.DataFrame()

    return qdf(f"""
        SELECT
            COALESCE(NULLIF(TRIM(o.{city_col}), ''), 'Unknown') AS city,
            SUM(r.quantity) AS return_units
        FROM returns r
        JOIN orders o ON o.order_id = r.order_id
        GROUP BY COALESCE(NULLIF(TRIM(o.{city_col}), ''), 'Unknown')
        ORDER BY SUM(r.quantity) DESC
        LIMIT 30
    """)


def scorecard():
    s = asin_sales()
    r = return_asin()

    if s.empty:
        return pd.DataFrame()

    d = s.merge(
        r,
        on=["asin", "sku"],
        how="left"
    )

    d["return_units"] = pd.to_numeric(
        d["return_units"],
        errors="coerce"
    ).fillna(0)

    d["return_rate"] = (
        d["return_units"] /
        d["units"].replace(0, pd.NA) *
        100
    ).fillna(0)

    def decision(row):
        if row["return_rate"] >= 15 and row["return_units"] >= 3:
            return "🔴 High Return"
        if row["return_rate"] >= 8 and row["return_units"] >= 2:
            return "🟡 Watch"
        return "🟢 Good"

    d["decision"] = d.apply(decision, axis=1)

    return d.sort_values(
        ["return_rate", "return_units"],
        ascending=False
    )


def asin_location_data(asin_value):
    pc = find_column(
        "orders",
        [
            "pincode",
            "pin_code",
            "postal_code",
            "ship_postal_code",
            "ship_pincode",
            "ship_pin_code",
            "zip"
        ]
    )

    if not pc:
        return pd.DataFrame(), None

    df = qdf(f"""
        SELECT
            COALESCE(NULLIF(TRIM(o.{pc}),''),'Unknown') AS pincode,
            SUM(r.quantity) AS return_units
        FROM returns r
        JOIN orders o ON o.order_id = r.order_id
        WHERE UPPER(COALESCE(r.asin,'')) = UPPER(?)
        GROUP BY COALESCE(NULLIF(TRIM(o.{pc}),''),'Unknown')
        ORDER BY SUM(r.quantity) DESC
        LIMIT 30
    """, [str(asin_value)])

    return df, pc


st.markdown(
    '<div class="hero">'
    '<h1>Amazon Ops Analytics Pro</h1>'
    '<p>Sales intelligence • Return intelligence • ASIN performance • Location analysis</p>'
    '</div>',
    unsafe_allow_html=True
)

with st.sidebar:
    page = st.radio(
        "Module",
        [
            "Executive Dashboard",
            "🔎 ASIN Search",
            "Sales Intelligence",
            "Return Intelligence",
            "Location Intelligence",
            "ASIN Scorecard",
            "Upload Center",
            "Data Audit"
        ]
    )

revenue, orders, units, returns = summary()
rate = returns / units * 100 if units else 0


if page == "Executive Dashboard":

    st.subheader("Executive Overview")

    for c, (a, b, n) in zip(
        st.columns(5),
        [
            ("Revenue", f"₹{revenue:,.0f}", "Non-cancelled orders"),
            ("Valid Orders", f"{orders:,}", "Cancelled excluded"),
            ("Units Sold", f"{units:,}", "Non-cancelled orders"),
            ("Return Units", f"{returns:,}", "Imported returns"),
            ("Return Rate", f"{rate:.2f}%", "Returns ÷ sold units")
        ]
    ):
        with c:
            st.markdown(
                f'<div class="kpi">'
                f'<div class="kpi-label">{a}</div>'
                f'<div class="kpi-value">{b}</div>'
                f'<div class="kpi-note">{n}</div>'
                f'</div>',
                unsafe_allow_html=True
            )

    d = sales_daily()

    if not d.empty:
        st.subheader("Sales Trend")
        d["order_date"] = pd.to_datetime(
            d["order_date"],
            errors="coerce"
        )

        if PLOTLY_OK:
            st.plotly_chart(
                px.line(
                    d,
                    x="order_date",
                    y="revenue",
                    markers=True,
                    title="Daily Revenue"
                ),
                width="stretch"
            )
        else:
            st.line_chart(
                d.set_index("order_date")["revenue"]
            )

    a = asin_sales()

    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Top ASINs by Revenue")
        x = a.head(10)

        if PLOTLY_OK and not x.empty:
            st.plotly_chart(
                px.bar(
                    x.sort_values("revenue"),
                    x="revenue",
                    y="asin",
                    orientation="h"
                ),
                width="stretch"
            )
        else:
            st.dataframe(
                x,
                width="stretch",
                hide_index=True
            )

    with c2:
        st.subheader("Top ASINs by Units")
        x = a.sort_values(
            "units",
            ascending=False
        ).head(10)

        if PLOTLY_OK and not x.empty:
            st.plotly_chart(
                px.bar(
                    x.sort_values("units"),
                    x="units",
                    y="asin",
                    orientation="h"
                ),
                width="stretch"
            )
        else:
            st.dataframe(
                x,
                width="stretch",
                hide_index=True
            )


elif page == "🔎 ASIN Search":

    st.subheader("🔎 ASIN Search & Product Analysis")
    st.caption(
        "Search one ASIN and view its complete sales, "
        "return, reason and location profile."
    )

    asin_query = st.text_input(
        "Enter ASIN",
        placeholder="Example: B0XXXXXXXX",
        key="asin_search"
    ).strip()

    if not asin_query:
        st.info(
            "Enter an ASIN above to view the complete product analysis."
        )

    else:
        sales = asin_sales()

        if sales.empty:
            st.warning("No sales data is available.")

        else:
            matches = sales[
                sales["asin"]
                .astype(str)
                .str.upper() == asin_query.upper()
            ].copy()

            if matches.empty:
                matches = sales[
                    sales["asin"]
                    .astype(str)
                    .str.contains(
                        asin_query,
                        case=False,
                        na=False
                    )
                ].copy()

            if matches.empty:
                st.error(
                    f"No sales record found for ASIN: {asin_query}"
                )

            else:
                selected = matches.iloc[0]["asin"]
                product = matches[
                    matches["asin"].astype(str) == str(selected)
                ]

                total_units = int(product["units"].sum())
                total_revenue = float(product["revenue"].sum())

                skus = ", ".join(
                    product["sku"]
                    .dropna()
                    .astype(str)
                    .unique()
                )

                r = return_asin()

                rr = (
                    r[r["asin"].astype(str) == str(selected)]
                    if not r.empty
                    else pd.DataFrame()
                )

                return_units = (
                    int(rr["return_units"].sum())
                    if not rr.empty and
                    "return_units" in rr.columns
                    else 0
                )

                product_return_rate = (
                    return_units / total_units * 100
                    if total_units else 0
                )

                if (
                    product_return_rate >= 15
                    and return_units >= 3
                ):
                    status = "🔴 High Return"
                elif (
                    product_return_rate >= 8
                    and return_units >= 2
                ):
                    status = "🟡 Watch"
                else:
                    status = "🟢 Good"

                st.markdown(
                    f"### ASIN: `{selected}`"
                )

                if skus:
                    st.caption(f"SKU: {skus}")

                c1, c2, c3, c4, c5 = st.columns(5)

                c1.metric(
                    "Units Sold",
                    f"{total_units:,}"
                )
                c2.metric(
                    "Sales",
                    f"₹{total_revenue:,.0f}"
                )
                c3.metric(
                    "Return Units",
                    f"{return_units:,}"
                )
                c4.metric(
                    "Return Rate",
                    f"{product_return_rate:.2f}%"
                )
                c5.metric(
                    "Status",
                    status
                )

                tab1, tab2, tab3, tab4 = st.tabs(
                    [
                        "Sales",
                        "Returns",
                        "Reasons",
                        "Locations"
                    ]
                )

                with tab1:
                    d = qdf(f"""
                        SELECT
                            o.order_date,
                            SUM(oi.quantity) AS units,
                            SUM(COALESCE(oi.item_price,0)) AS revenue
                        FROM order_items oi
                        JOIN orders o
                            ON o.order_id = oi.order_id
                        WHERE {ACTIVE}
                          AND UPPER(COALESCE(oi.asin,'')) = UPPER(?)
                        GROUP BY o.order_date
                        ORDER BY o.order_date
                    """, [str(selected)])

                    if not d.empty:
                        d["order_date"] = pd.to_datetime(
                            d["order_date"],
                            errors="coerce"
                        )

                        if PLOTLY_OK:
                            st.plotly_chart(
                                px.line(
                                    d,
                                    x="order_date",
                                    y="revenue",
                                    markers=True,
                                    title="ASIN Sales Trend"
                                ),
                                width="stretch"
                            )

                            st.plotly_chart(
                                px.bar(
                                    d,
                                    x="order_date",
                                    y="units",
                                    title="Units Sold by Date"
                                ),
                                width="stretch"
                            )

                        st.dataframe(
                            d,
                            width="stretch",
                            hide_index=True
                        )

                    else:
                        st.info(
                            "No sales trend data found."
                        )

                with tab2:
                    # Build the return-detail query only from columns that exist.
                    return_cols = cols("returns")
                    lower_returns = {c.lower(): c for c in return_cols}

                    def rc(*names):
                        for name in names:
                            if name.lower() in lower_returns:
                                return lower_returns[name.lower()]
                        return None

                    date_col = rc(
                        "return_date", "return_request_date",
                        "return_creation_date", "return_creation_timestamp",
                        "return_date_time", "date", "authorization_date"
                    )
                    order_col = rc("order_id")
                    sku_col = rc("sku", "merchant_sku")
                    qty_col = rc("quantity", "return_quantity")
                    reason_col = rc("reason", "return_reason")
                    comment_col = rc("customer_comment", "customer_comments", "comment")
                    disposition_col = rc("disposition", "resolution")

                    select_parts = []
                    for col, alias, fallback in [
                        (date_col, "return_date", "NULL"),
                        (order_col, "order_id", "NULL"),
                        (sku_col, "sku", "NULL"),
                        (qty_col, "quantity", "0"),
                        (reason_col, "reason", "NULL"),
                        (comment_col, "customer_comment", "NULL"),
                        (disposition_col, "disposition", "NULL"),
                    ]:
                        select_parts.append(
                            f'"{col}" AS {alias}' if col else f'{fallback} AS {alias}'
                        )

                    order_sql = f' ORDER BY "{date_col}" DESC' if date_col else ''
                    rd = qdf(
                        "SELECT " + ", ".join(select_parts) +
                        " FROM returns WHERE UPPER(COALESCE(asin,'')) = UPPER(?)" +
                        order_sql,
                        [str(selected)]
                    )

                    if rd.empty:
                        st.success(
                            "No returns found for this ASIN."
                        )
                    else:
                        st.dataframe(
                            rd,
                            width="stretch",
                            hide_index=True
                        )

                        st.download_button(
                            "Download ASIN Returns CSV",
                            rd.to_csv(index=False).encode("utf-8"),
                            f"{selected}_returns.csv",
                            "text/csv"
                        )

                with tab3:
                    reasons = qdf("""
                        SELECT
                            COALESCE(
                                NULLIF(TRIM(reason),''),
                                'Unknown'
                            ) AS reason,
                            SUM(quantity) AS return_units
                        FROM returns
                        WHERE UPPER(COALESCE(asin,'')) = UPPER(?)
                        GROUP BY
                            COALESCE(
                                NULLIF(TRIM(reason),''),
                                'Unknown'
                            )
                        ORDER BY SUM(quantity) DESC
                    """, [str(selected)])

                    if reasons.empty:
                        st.info(
                            "No return reasons found."
                        )
                    else:
                        c1, c2 = st.columns(
                            [1.2, 1]
                        )

                        with c1:
                            if PLOTLY_OK:
                                st.plotly_chart(
                                    px.bar(
                                        reasons,
                                        x="return_units",
                                        y="reason",
                                        orientation="h",
                                        title="Return Reasons"
                                    ),
                                    width="stretch"
                                )

                        with c2:
                            st.dataframe(
                                reasons,
                                width="stretch",
                                hide_index=True
                            )

                with tab4:
                    loc, pc = asin_location_data(
                        selected
                    )

                    if pc:
                        if not loc.empty:
                            st.dataframe(
                                loc,
                                width="stretch",
                                hide_index=True
                            )

                            if PLOTLY_OK:
                                st.plotly_chart(
                                    px.bar(
                                        loc.head(15)
                                        .sort_values(
                                            "return_units"
                                        ),
                                        x="return_units",
                                        y="pincode",
                                        orientation="h",
                                        title="Top Return Pincodes"
                                    ),
                                    width="stretch"
                                )
                        else:
                            st.info(
                                "No pincode return data found "
                                "for this ASIN."
                            )
                    else:
                        st.warning(
                            "Pincode is not stored in the current "
                            "orders table. Once pincode is added to "
                            "the database/import, this section will "
                            "show return hotspots."
                        )


elif page == "Sales Intelligence":

    st.subheader("Sales Intelligence")
    st.caption("Sale Price = Amazon item-price only. item-tax is stored separately and is NOT added to Sale Price.")

    d = asin_sales()

    search = st.text_input(
        "Search ASIN / SKU"
    )

    if search:
        d = d[
            d.astype(str)
            .apply(
                lambda x: x.str.contains(
                    search,
                    case=False,
                    na=False
                )
            )
            .any(axis=1)
        ]

    st.dataframe(
        d,
        width="stretch",
        hide_index=True
    )

    st.download_button(
        "Download Sales CSV",
        d.to_csv(index=False).encode(),
        "sales_analysis.csv",
        "text/csv"
    )


elif page == "Return Intelligence":

    st.subheader("Return Intelligence")

    r = return_reasons()
    a = return_asin()

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("### Return Reasons")

        if not r.empty and PLOTLY_OK:
            st.plotly_chart(
                px.pie(
                    r.head(12),
                    names="reason",
                    values="return_units",
                    hole=.45
                ),
                width="stretch"
            )
        else:
            st.dataframe(
                r,
                width="stretch",
                hide_index=True
            )

    with c2:
        st.markdown("### Top Return ASINs")

        if not a.empty and PLOTLY_OK:
            st.plotly_chart(
                px.bar(
                    a.head(12).sort_values(
                        "return_units"
                    ),
                    x="return_units",
                    y="asin",
                    orientation="h"
                ),
                width="stretch"
            )
        else:
            st.dataframe(
                a,
                width="stretch",
                hide_index=True
            )

    s = scorecard()

    st.markdown("### Return Rate by ASIN")

    st.dataframe(
        s,
        width="stretch",
        hide_index=True
    )


elif page == "Location Intelligence":

    st.subheader("Location Intelligence")

    p, pc = locations()

    if pc:
        st.caption(
            f"Return hotspots based on shipping pincode: orders.{pc}. Shipping city is shown when available."
        )
    else:
        st.caption(
            "Pincode is shown when it exists in the orders database."
        )

    c1, c2 = st.columns(2)

    sr = state_returns()
    cr = city_returns()

    with c1:
        st.markdown("### Returns by State")

        if not sr.empty and PLOTLY_OK:
            st.plotly_chart(
                px.bar(
                    sr.head(15).sort_values(
                        "return_units"
                    ),
                    x="return_units",
                    y="state",
                    orientation="h"
                ),
                width="stretch"
            )
        else:
            st.dataframe(
                sr,
                width="stretch",
                hide_index=True
            )

    with c2:
        st.markdown("### Returns by City")

        if not cr.empty and PLOTLY_OK:
            st.plotly_chart(
                px.bar(
                    cr.head(15).sort_values(
                        "return_units"
                    ),
                    x="return_units",
                    y="city",
                    orientation="h"
                ),
                width="stretch"
            )
        else:
            st.dataframe(
                cr,
                width="stretch",
                hide_index=True
            )

    st.markdown("### Top Return Pincodes / Cities")

    if p.empty:
        st.warning(
            "Pincode is not stored in the orders table yet."
        )
    else:
        st.dataframe(
            p,
            width="stretch",
            hide_index=True
        )


elif page == "ASIN Scorecard":

    st.subheader(
        "ASIN Product Decision Scorecard"
    )

    s = scorecard()

    if s.empty:
        st.info(
            "No sales/return data available."
        )
    else:
        c1, c2, c3 = st.columns(3)

        c1.metric(
            "High Return ASINs",
            int(
                (s["decision"] == "🔴 High Return").sum()
            )
        )

        c2.metric(
            "Watch ASINs",
            int(
                (s["decision"] == "🟡 Watch").sum()
            )
        )

        c3.metric(
            "Good ASINs",
            int(
                (s["decision"] == "🟢 Good").sum()
            )
        )

        st.dataframe(
            s,
            width="stretch",
            hide_index=True
        )


elif page == "Upload Center":

    st.subheader(
        "Amazon Report Upload Center"
    )

    typ = st.selectbox(
        "Report Type",
        ["Orders", "Returns"]
    )

    f = st.file_uploader(
        "Upload Amazon report",
        type=["txt", "tsv", "csv", "xlsx", "xls"]
    )

    if f and st.button(
        "Import Report",
        type="primary"
    ):
        try:
            result = ingest_report(
                f,
                typ
            )

            st.success(
                result["message"]
            )

            st.json(result)

            st.rerun()

        except Exception as e:
            st.error(
                f"Import failed: {e}"
            )


else:

    st.subheader("Data Audit")

    st.dataframe(
        pd.DataFrame(
            [{
                "All Orders": scalar(
                    "SELECT COUNT(*) FROM orders"
                ),
                "Active Orders": scalar(
                    f"SELECT COUNT(*) FROM orders o WHERE {ACTIVE}"
                ),
                "Cancelled Orders": scalar(
                    """
                    SELECT COUNT(*)
                    FROM orders o
                    WHERE COALESCE(
                        LOWER(TRIM(o.order_status)),
                        ''
                    ) LIKE '%cancel%'
                    """
                ),
                "Order Items": scalar(
                    "SELECT COUNT(*) FROM order_items"
                ),
                "Returns": scalar(
                    "SELECT COUNT(*) FROM returns"
                )
            }]
        ),
        width="stretch",
        hide_index=True
    )

    st.info(
        "Cancelled orders remain available for audit "
        "but are excluded from sales analytics."
    )
