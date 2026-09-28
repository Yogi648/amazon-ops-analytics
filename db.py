from pathlib import Path
import os
import sqlite3

ROOT=Path(__file__).resolve().parents[1]
DB_PATH=ROOT/"data"/"amazon_ops.db"
_DATABASE_URL = None


class DatabaseConnection:
    def __init__(self, connection, backend):
        self._connection = connection
        self.backend = backend

    def execute(self, sql, params=None):
        if self.backend == "postgres":
            if params:
                sql = sql.replace("%", "%%").replace("?", "%s")
                return self._connection.execute(sql, params)
            return self._connection.execute(sql)
        return self._connection.execute(sql, params or ())

    def commit(self):
        self._connection.commit()

    def close(self):
        self._connection.close()


def configure_database(database_url=None):
    global _DATABASE_URL
    _DATABASE_URL = database_url


def persistent_database_configured():
    return bool(_DATABASE_URL or os.environ.get("DATABASE_URL"))

def connect():
    database_url = _DATABASE_URL or os.environ.get("DATABASE_URL")
    if database_url:
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "Install psycopg[binary] to use the configured Postgres database."
            ) from exc
        connection = psycopg.connect(database_url)
        return DatabaseConnection(connection, "postgres")

    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys=ON")
    return DatabaseConnection(con, "sqlite")


def table_columns(con, table):
    if con.backend == "postgres":
        rows = con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name=?",
            [table],
        ).fetchall()
        return {row[0] for row in rows}

    return {
        row[1]
        for row in con.execute(f"PRAGMA table_info({table})").fetchall()
    }

def init_db():
    con=connect()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS orders(
        order_id TEXT PRIMARY KEY,
        order_date TEXT,
        order_status TEXT,
        marketplace TEXT,
        ship_state TEXT,
        ship_city TEXT
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS order_items(
        order_id TEXT,
        order_item_key TEXT,
        order_date TEXT,
        sku TEXT,
        asin TEXT,
        quantity INTEGER,
        item_price REAL,
        item_tax REAL,
        currency TEXT,
        PRIMARY KEY(order_id,order_item_key)
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS returns(
        return_id TEXT PRIMARY KEY,
        order_id TEXT,
        return_date TEXT,
        sku TEXT,
        asin TEXT,
        quantity INTEGER,
        reason TEXT,
        customer_comment TEXT,
        disposition TEXT
        )""")
        con.commit()
    finally:
        con.close()
