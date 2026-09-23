from db import connect

def get_dashboard_summary():
    con = connect()
    sales = con.execute("""
        SELECT
            COALESCE(SUM(item_price), 0) AS revenue,
            COALESCE(SUM(quantity), 0) AS units,
            COUNT(DISTINCT order_id) AS orders
        FROM order_items
    """).fetchdf()
    returns = con.execute("""
        SELECT COALESCE(SUM(quantity), 0) AS return_units
        FROM returns
    """).fetchdf()
    con.close()
    return {
        "revenue": float(sales.loc[0, "revenue"]),
        "units": int(sales.loc[0, "units"]),
        "orders": int(sales.loc[0, "orders"]),
        "return_units": int(returns.loc[0, "return_units"]),
    }

def sales_by_sku():
    con = connect()
    df = con.execute("""
        SELECT sku, asin, SUM(quantity) AS units,
               SUM(item_price) AS revenue
        FROM order_items
        GROUP BY 1,2
        ORDER BY revenue DESC
    """).fetchdf()
    con.close()
    return df

def returns_by_sku():
    con = connect()
    df = con.execute("""
        SELECT sku, asin, SUM(quantity) AS return_units,
               COUNT(*) AS return_records
        FROM returns
        GROUP BY 1,2
        ORDER BY return_units DESC
    """).fetchdf()
    con.close()
    return df
from db import connect

def get_dashboard_summary():
    con = connect()
    sales = con.execute("""
        SELECT
            COALESCE(SUM(item_price), 0) AS revenue,
            COALESCE(SUM(quantity), 0) AS units,
            COUNT(DISTINCT order_id) AS orders
        FROM order_items
    """).fetchdf()
    returns = con.execute("""
        SELECT COALESCE(SUM(quantity), 0) AS return_units
        FROM returns
    """).fetchdf()
    con.close()
    return {
        "revenue": float(sales.loc[0, "revenue"]),
        "units": int(sales.loc[0, "units"]),
        "orders": int(sales.loc[0, "orders"]),
        "return_units": int(returns.loc[0, "return_units"]),
    }

def sales_by_sku():
    con = connect()
    df = con.execute("""
        SELECT sku, asin, SUM(quantity) AS units,
               SUM(item_price) AS revenue
        FROM order_items
        GROUP BY 1,2
        ORDER BY revenue DESC
    """).fetchdf()
    con.close()
    return df

def returns_by_sku():
    con = connect()
    df = con.execute("""
        SELECT sku, asin, SUM(quantity) AS return_units,
               COUNT(*) AS return_records
        FROM returns
        GROUP BY 1,2
        ORDER BY return_units DESC
    """).fetchdf()
    con.close()
    return df
