from pathlib import Path
import sqlite3
import pandas as pd
import streamlit as st

try:
    import plotly.express as px
    PLOTLY = True
except Exception:
    PLOTLY = False

st.set_page_config(page_title='Amazon Ops Analytics Pro', page_icon='📊', layout='wide')

st.markdown('''<style>
.stApp{background:#f6f8fb}.hero{background:linear-gradient(135deg,#14213d,#263f68);padding:28px 32px;border-radius:0 0 22px 22px;color:#fff;margin:-1rem -1rem 22px;box-shadow:0 8px 25px #0002}.hero h1{margin:0;font-size:34px}.hero p{margin:7px 0 0;color:#cbd5e1}.kpi{background:white;border:1px solid #e5e7eb;border-radius:16px;padding:18px;min-height:105px;box-shadow:0 3px 12px #0000000b}.kl{font-size:13px;color:#64748b}.kv{font-size:27px;font-weight:800;color:#172033;margin-top:8px}.kn{font-size:12px;color:#94a3b8;margin-top:4px}.stDataFrame{border-radius:12px}
</style>''', unsafe_allow_html=True)

ROOT=Path(__file__).resolve().parents[1]

def find_db():
    candidates=[ROOT/'db'/'amazon_ops.db',ROOT/'db'/'ops.db',ROOT/'db'/'database.db',ROOT/'data'/'amazon_ops.db',ROOT/'data'/'ops.db',ROOT/'data'/'database.db',ROOT/'database.db']
    for p in candidates:
        if p.exists(): return p
    for d in [ROOT/'db',ROOT/'data']:
        if d.exists():
            x=list(d.glob('*.db'))+list(d.glob('*.sqlite'))+list(d.glob('*.sqlite3'))
            if x:return x[0]
    return None

DB=find_db()
if not DB:
    st.error('Database not found. Put your SQLite database in db/ or data/.')
    st.stop()
con=sqlite3.connect(str(DB),check_same_thread=False)

def tables():
    return pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'",con)['name'].tolist()
TABLES=tables()

def cols(t):
    if t not in TABLES:return []
    return pd.read_sql_query(f'PRAGMA table_info("{t}")',con)['name'].tolist()

def col(t,*names):
    m={x.lower():x for x in cols(t)}
    for n in names:
        if n.lower() in m:return m[n.lower()]
    return None

def q(sql,params=None):
    try:return pd.read_sql_query(sql,con,params=params or [])
    except Exception as e:
        st.warning(str(e));return pd.DataFrame()

def n(x):
    try:return float(x or 0)
    except:return 0.0

def qi(x):return '"'+x.replace('"','""')+'"'

OT='orders' if 'orders' in TABLES else None
RT='returns' if 'returns' in TABLES else None
A=col('orders','asin','item_asin') if OT else None
S=col('orders','sku','merchant_sku','seller_sku') if OT else None
OID=col('orders','order_id','amazon_order_id') if OT else None
OD=col('orders','order_date','purchase_date','purchase-date') if OT else None
Q=col('orders','quantity','qty','item_quantity') if OT else None
PRICE=col('orders','item_price','price','sale_price','sales_price','amount') if OT else None
TAX=col('orders','item_tax','tax','sales_tax') if OT else None
CITY=col('orders','ship_city','city') if OT else None
STATE=col('orders','ship_state','state') if OT else None
PIN=col('orders','ship_postal_code','ship-postal-code','postal_code','pincode','pin_code') if OT else None
STATUS=col('orders','status','order_status','order_status_code') if OT else None
PRODUCT=col('orders','product_name','item_name','title','product_title') if OT else None
CATEGORY=col('orders','category','product_type','item_category') if OT else None
RA=col('returns','asin','item_asin') if RT else None
ROID=col('returns','order_id','amazon_order_id') if RT else None
RQ=col('returns','return_quantity','quantity','qty') if RT else None
RR=col('returns','return_reason','reason','return_reason_code') if RT else None
RDATE=col('returns','return_date','return-date','return_creation_date','return_creation_timestamp','return_date_time','return_request_date','authorization_date','return_delivery_date','date') if RT else None

# Cancelled orders are excluded from ALL sales calculations.
def valid(alias='o'):
    if not STATUS:return '1=1'
    c=f'{alias}.{qi(STATUS)}'
    return f"LOWER(COALESCE({c},'')) NOT LIKE '%cancel%'"

def daily():
    if not OT or not OD:return pd.DataFrame()
    price=f'COALESCE(CAST(o.{qi(PRICE)} AS REAL),0)' if PRICE else '0'
    qty=f'COALESCE(CAST(o.{qi(Q)} AS REAL),1)' if Q else '1'
    oid=f'o.{qi(OID)}' if OID else 'rowid'
    return q(f'''SELECT DATE(o.{qi(OD)}) order_date,SUM({price}) revenue,SUM({qty}) units,COUNT(DISTINCT {oid}) orders FROM orders o WHERE {valid()} GROUP BY DATE(o.{qi(OD)}) ORDER BY order_date''')

def top_asins(limit=30):
    if not OT or not A:return pd.DataFrame()
    price=f'COALESCE(CAST(o.{qi(PRICE)} AS REAL),0)' if PRICE else '0';qty=f'COALESCE(CAST(o.{qi(Q)} AS REAL),1)' if Q else '1'
    return q(f'''SELECT o.{qi(A)} asin,SUM({qty}) units,SUM({price}) revenue FROM orders o WHERE {valid()} AND TRIM(COALESCE(o.{qi(A)},''))<>'' GROUP BY o.{qi(A)} ORDER BY revenue DESC LIMIT {limit}''')

def returns_by_reason(limit=30):
    if not RT or not RR:return pd.DataFrame()
    qty=f'COALESCE(CAST(r.{qi(RQ)} AS REAL),1)' if RQ else '1'
    return q(f'''SELECT COALESCE(NULLIF(TRIM(r.{qi(RR)}),''),'Unknown') reason,SUM({qty}) returns FROM returns r GROUP BY reason ORDER BY returns DESC LIMIT {limit}''')

def returns_by_location(cname,limit=30):
    if not RT or not OT or not cname or not ROID or not OID:return pd.DataFrame()
    qty=f'COALESCE(CAST(r.{qi(RQ)} AS REAL),1)' if RQ else '1'
    return q(f'''SELECT COALESCE(NULLIF(TRIM(o.{qi(cname)}),''),'Unknown') location,SUM({qty}) returns FROM returns r JOIN orders o ON o.{qi(OID)}=r.{qi(ROID)} WHERE {valid()} GROUP BY location ORDER BY returns DESC LIMIT {limit}''')

def return_asins(limit=30):
    if not RT:return pd.DataFrame()
    qty=f'COALESCE(CAST(r.{qi(RQ)} AS REAL),1)' if RQ else '1'
    if RA:
        return q(f'''SELECT r.{qi(RA)} asin,SUM({qty}) returns FROM returns r GROUP BY r.{qi(RA)} ORDER BY returns DESC LIMIT {limit}''')
    if ROID and OID and A:
        return q(f'''SELECT o.{qi(A)} asin,SUM({qty}) returns FROM returns r JOIN orders o ON o.{qi(OID)}=r.{qi(ROID)} WHERE {valid()} GROUP BY o.{qi(A)} ORDER BY returns DESC LIMIT {limit}''')
    return pd.DataFrame()

def asin_profile(asin):
    out={'units':0,'orders':0,'revenue':0,'returns':0}
    if OT and A:
        price=f'COALESCE(CAST(o.{qi(PRICE)} AS REAL),0)' if PRICE else '0';qty=f'COALESCE(CAST(o.{qi(Q)} AS REAL),1)' if Q else '1';oid=f'o.{qi(OID)}' if OID else 'rowid'
        extra=[]
        if S:extra.append(f'MAX(o.{qi(S)}) sku')
        if PRODUCT:extra.append(f'MAX(o.{qi(PRODUCT)}) product_name')
        if CATEGORY:extra.append(f'MAX(o.{qi(CATEGORY)}) category')
        x=','+','.join(extra) if extra else ''
        d=q(f'''SELECT SUM({qty}) units,SUM({price}) revenue,COUNT(DISTINCT {oid}) orders{x} FROM orders o WHERE o.{qi(A)}=? AND {valid()}''',[asin])
        if not d.empty:out.update(d.iloc[0].to_dict())
    if RT:
        qty=f'COALESCE(CAST(r.{qi(RQ)} AS REAL),1)' if RQ else '1'
        if RA:d=q(f'''SELECT SUM({qty}) returns FROM returns r WHERE r.{qi(RA)}=?''',[asin])
        elif ROID and OID and A:d=q(f'''SELECT SUM({qty}) returns FROM returns r JOIN orders o ON o.{qi(OID)}=r.{qi(ROID)} WHERE o.{qi(A)}=? AND {valid()}''',[asin])
        else:d=pd.DataFrame()
        if not d.empty:out['returns']=n(d.iloc[0]['returns'])
    out['units']=n(out['units']);out['revenue']=n(out['revenue']);out['orders']=int(n(out['orders']));out['returns']=n(out['returns']);out['return_rate']=out['returns']/out['units']*100 if out['units'] else 0
    return out

def asin_reasons(asin):
    if not RT or not RR:return pd.DataFrame()
    qty=f'COALESCE(CAST(r.{qi(RQ)} AS REAL),1)' if RQ else '1'
    if RA:return q(f'''SELECT COALESCE(NULLIF(TRIM(r.{qi(RR)}),''),'Unknown') reason,SUM({qty}) returns FROM returns r WHERE r.{qi(RA)}=? GROUP BY reason ORDER BY returns DESC''',[asin])
    if ROID and OID and A:return q(f'''SELECT COALESCE(NULLIF(TRIM(r.{qi(RR)}),''),'Unknown') reason,SUM({qty}) returns FROM returns r JOIN orders o ON o.{qi(OID)}=r.{qi(ROID)} WHERE o.{qi(A)}=? AND {valid()} GROUP BY reason ORDER BY returns DESC''',[asin])
    return pd.DataFrame()

d=sales_daily();revenue=n(d.revenue.sum()) if not d.empty else 0;units=n(d.units.sum()) if not d.empty else 0;orders=int(d.orders.sum()) if not d.empty else 0
rd=return_asins(10000);return_units=n(rd.returns.sum()) if not rd.empty else 0;rate=return_units/units*100 if units else 0

st.markdown('<div class="hero"><h1>Amazon Ops Analytics Pro</h1><p>Sales intelligence • Return intelligence • ASIN performance • Location analysis</p></div>',unsafe_allow_html=True)
st.sidebar.title('Amazon Ops')
st.sidebar.caption('Operations Intelligence')
page=st.sidebar.radio('Module',['Executive Dashboard','🔎 ASIN Search','📈 Sales Intelligence','↩️ Return Intelligence','📍 Location Intelligence','🎯 ASIN Scorecard','📤 Upload Center','🛠️ Data Audit'])
st.sidebar.divider();st.sidebar.caption(f'Database: {DB.name}')

def k(label,value,note):st.markdown(f'<div class="kpi"><div class="kl">{label}</div><div class="kv">{value}</div><div class="kn">{note}</div></div>',unsafe_allow_html=True)

if page=='Executive Dashboard':
    st.subheader('Executive Overview');c=st.columns(5)
    for x,label,value,note in zip(c,['Revenue','Valid Orders','Units Sold','Return Units','Return Rate'],[f'₹{revenue:,.0f}',f'{orders:,}',f'{units:,.0f}',f'{return_units:,.0f}',f'{rate:.2f}%'],['Non-cancelled orders','Cancelled excluded','Non-cancelled orders','Imported returns','Returns ÷ sold units']):
        with x:k(label,value,note)
    st.subheader('Sales Trend')
    if not d.empty:
        if PLOTLY:
            fig=px.line(d,x='order_date',y='revenue',markers=True,title='Daily Revenue');fig.update_layout(height=390,margin=dict(l=20,r=20,t=55,b=20));st.plotly_chart(fig,use_container_width=True)
        else:st.line_chart(d.set_index('order_date').revenue)
    c1,c2=st.columns(2)
    with c1:
        st.subheader('Top ASIN Performance');a=top_asins(20);st.dataframe(a,use_container_width=True,hide_index=True)
        if PLOTLY and not a.empty:st.plotly_chart(px.bar(a.sort_values('revenue'),x='revenue',y='asin',orientation='h',title='Revenue by ASIN'),use_container_width=True)
    with c2:
        st.subheader('Top Returned ASINs');st.dataframe(rd.head(20),use_container_width=True,hide_index=True)
        if PLOTLY and not rd.empty:st.plotly_chart(px.bar(rd.head(15).sort_values('returns'),x='returns',y='asin',orientation='h',title='Return Units'),use_container_width=True)

elif page=='🔎 ASIN Search':
    st.subheader('🔎 ASIN Search & Product Analysis');st.caption('Search an ASIN for sales, return, reason and location intelligence.')
    asin=st.text_input('Enter ASIN',placeholder='B0XXXXXXXX').strip().upper()
    if asin:
        p=asin_profile(asin);c=st.columns(5)
        vals=[(f'{p["units"]:,.0f}','Units Sold','Valid orders'),(f'{p["orders"]:,}','Orders','Cancelled excluded'),(f'₹{p["revenue"]:,.0f}','Revenue','Sale value'),(f'{p["returns"]:,.0f}','Returns','Return units'),(f'{p["return_rate"]:.2f}%','Return Rate','ASIN returns / units')]
        for x,(v,l,note) in zip(c,vals):
            with x:k(l,v,note)
        if p['orders']==0 and p['returns']==0:st.warning('No matching data found for this ASIN.')
        else:
            profile={z:p[z] for z in ['sku','product_name','category'] if p.get(z) not in [None,'']}
            if profile:st.dataframe(pd.DataFrame([profile]),use_container_width=True,hide_index=True)
            c1,c2=st.columns(2)
            with c1:
                st.markdown('### Return Reasons');x=asin_reasons(asin);st.dataframe(x,use_container_width=True,hide_index=True)
                if PLOTLY and not x.empty:st.plotly_chart(px.pie(x,names='reason',values='returns',hole=.45,title='Why customers return this ASIN'),use_container_width=True)
            with c2:
                st.markdown('### Return Locations')
                loc=PIN or CITY or STATE
                x=returns_by_location(loc,20) if loc else pd.DataFrame()
                if not x.empty:st.dataframe(x,use_container_width=True,hide_index=True)

elif page=='📈 Sales Intelligence':
    st.subheader('📈 Sales Intelligence');a=top_asins(200);r=return_asins(10000)
    if not a.empty and not r.empty:a=a.merge(r,on='asin',how='left');a['returns']=a.returns.fillna(0);a['return_rate']=(a.returns/a.units.replace(0,pd.NA)*100).fillna(0)
    st.dataframe(a,use_container_width=True,hide_index=True)

elif page=='↩️ Return Intelligence':
    st.subheader('↩️ Return Intelligence');c1,c2=st.columns(2)
    with c1:
        x=returns_by_reason(30);st.markdown('### Return Reasons');st.dataframe(x,use_container_width=True,hide_index=True)
        if PLOTLY and not x.empty:st.plotly_chart(px.bar(x.sort_values('returns'),x='returns',y='reason',orientation='h'),use_container_width=True)
    with c2:
        st.markdown('### Products with Most Returns');st.dataframe(rd.head(30),use_container_width=True,hide_index=True)

elif page=='📍 Location Intelligence':
    st.subheader('📍 Location Intelligence');st.caption('Find cities, states and pincodes generating the most returns.')
    names=[];mapping=[]
    if PIN:names.append('Pincode');mapping.append(PIN)
    if CITY:names.append('City');mapping.append(CITY)
    if STATE:names.append('State');mapping.append(STATE)
    if not names:st.warning('No ship-postal-code, ship_city or ship_state column found in orders.')
    else:
        tabs=st.tabs(names)
        for tab,title,cname in zip(tabs,names,mapping):
            with tab:
                x=returns_by_location(cname,50);st.dataframe(x,use_container_width=True,hide_index=True)
                if PLOTLY and not x.empty:st.plotly_chart(px.bar(x.head(25).sort_values('returns'),x='returns',y='location',orientation='h',title=f'Top return {title.lower()}s'),use_container_width=True)

elif page=='🎯 ASIN Scorecard':
    st.subheader('🎯 ASIN Scorecard');a=top_asins(300);r=return_asins(10000)
    if not a.empty:
        if not r.empty:a=a.merge(r,on='asin',how='left')
        if 'returns' not in a:a['returns']=0
        a['returns']=a.returns.fillna(0);a['return_rate']=(a.returns/a.units.replace(0,pd.NA)*100).fillna(0);a['risk']=a.return_rate.apply(lambda x:'HIGH' if x>=15 else ('WATCH' if x>=8 else 'GOOD'))
        st.dataframe(a.sort_values('return_rate',ascending=False),use_container_width=True,hide_index=True)

elif page=='📤 Upload Center':
    st.subheader('📤 Upload Center');st.info('Keep your existing upload/import workflow here. This dashboard only reads the database.');st.write('Detected tables:',', '.join(TABLES))

else:
    st.subheader('🛠️ Data Audit');rows=[]
    for label,value in [('Orders table',OT),('Returns table',RT),('ASIN',A),('SKU',S),('Order ID',OID),('Order date',OD),('Quantity',Q),('Item price / sale price',PRICE),('Item tax',TAX),('Ship city',CITY),('Ship state',STATE),('Ship postal code',PIN),('Order status',STATUS),('Return ASIN',RA),('Return date',RDATE),('Return quantity',RQ),('Return reason',RR)]:rows.append({'Field':label,'Detected column':value or 'NOT FOUND'})
    st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    for t in TABLES:
        with st.expander(t):st.code(', '.join(cols(t)))

st.divider();st.caption('Amazon Ops Analytics Pro • Cancelled orders are excluded from sales KPIs and sales analysis.')
