from pathlib import Path
import sqlite3

ROOT=Path(__file__).resolve().parents[1]
DB_PATH=ROOT/"data"/"amazon_ops.db"

def connect():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys=ON")
    return con

def init_db():
    con=connect()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS orders(
        order_id TEXT PRIMARY KEY,
        order_date DATE,
        order_status TEXT,
        marketplace TEXT,
        ship_state TEXT,
        ship_city TEXT
    );
    CREATE TABLE IF NOT EXISTS order_items(
        order_id TEXT,
        order_item_key TEXT,
        order_date DATE,
        sku TEXT,
        asin TEXT,
        quantity INTEGER,
        item_price REAL,
        item_tax REAL,
        currency TEXT,
        PRIMARY KEY(order_id,order_item_key)
    );
    CREATE TABLE IF NOT EXISTS returns(
        return_id TEXT PRIMARY KEY,
        order_id TEXT,
        return_date DATE,
        sku TEXT,
        asin TEXT,
        quantity INTEGER,
        reason TEXT,
        customer_comment TEXT,
        disposition TEXT
    );
    """)
    con.commit()
    con.close()
