from pathlib import Path
import io
import re
import pandas as pd

from db import connect, init_db


# ============================================================
# AMAZON OPS ANALYTICS - ROBUST IMPORTER
# ============================================================
# ORDERS:
#   Sale Price = item-price ONLY
#   item-tax is stored separately and NEVER added to Sale Price
#   ship-city -> ship_city
#   ship-postal-code -> ship_postal_code
#
# RETURNS:
#   return_request_date -> return_date
#   amazon_rma_id -> return_id
#   merchant_sku -> sku
#   return_quantity -> quantity
#   return_reason -> reason
#   resolution -> disposition
#
# Existing databases are upgraded automatically without deleting
# existing data.
# ============================================================


def norm(x):
    return re.sub(
        r"[^a-z0-9]+",
        "_",
        str(x).strip().lower().replace("\ufeff", "")
    ).strip("_")


def read_file(uploaded):
    """
    Read CSV/TSV/TXT/XLS/XLSX Amazon reports.

    Amazon reports can contain Windows-1252 characters such as
    degree symbols, so several encodings are attempted.
    """
    suffix = Path(uploaded.name).suffix.lower()
    data = uploaded.getvalue()

    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(io.BytesIO(data))

    encodings = [
        "utf-8-sig",
        "utf-8",
        "cp1252",
        "windows-1252",
        "latin-1",
    ]

    sample = None
    last_error = None

    for enc in encodings:
        try:
            sample = data[:12000].decode(enc)
            break
        except UnicodeDecodeError as e:
            last_error = e

    if sample is None:
        raise ValueError(
            "Could not decode the Amazon report. "
            f"Last error: {last_error}"
        )

    sep = "\t" if sample.count("\t") >= sample.count(",") else ","

    for enc in encodings:
        try:
            return pd.read_csv(
                io.BytesIO(data),
                sep=sep,
                dtype=str,
                keep_default_na=False,
                encoding=enc,
                engine="python",
            )
        except UnicodeDecodeError:
            continue

    raise ValueError(
        "Could not read the report using UTF-8, CP1252 or Latin-1."
    )


def cols(df):
    df = df.copy()
    df.columns = [norm(c) for c in df.columns]
    return df


def find(df, names, required=False):
    for n in names:
        n = norm(n)
        if n in df.columns:
            return n

    if required:
        raise ValueError(
            "Required column not found. "
            "Expected one of: "
            + ", ".join(names)
            + ". Detected columns: "
            + str(list(df.columns))
        )

    return None


def ser(df, c, default=""):
    if c:
        return (
            df[c]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    return pd.Series(
        [default] * len(df),
        index=df.index
    )


def num(s):
    s = (
        s.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("₹", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace("€", "", regex=False)
        .str.replace("£", "", regex=False)
    )

    return pd.to_numeric(
        s,
        errors="coerce"
    ).fillna(0.0)


def integer(s):
    return (
        pd.to_numeric(
            s,
            errors="coerce"
        )
        .fillna(0)
        .astype(int)
    )


def dates(s):
    """
    Convert a date column to Python date objects.
    Invalid/blank dates become None, never pandas NaT.
    SQLite cannot bind pandas NaT, so this conversion is important.
    """
    parsed = pd.to_datetime(
        s,
        errors="coerce"
    )

    result = []
    for value in parsed:
        if pd.isna(value):
            result.append(None)
        else:
            result.append(value.date())

    return pd.Series(
        result,
        index=s.index,
        dtype="object"
    )


def text(s):
    return (
        s.astype(str)
        .replace({
            "nan": "",
            "None": "",
            "NaT": ""
        })
        .str.strip()
    )


def sqlite_value(value):
    """
    Convert pandas/numpy missing values to None so SQLite can bind them.
    """
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    # Convert pandas Timestamp to a normal Python value.
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()

    return value


# ============================================================
# DATABASE UPGRADE HELPERS
# ============================================================

def table_columns(con, table):
    return {
        row[1]
        for row in con.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }


def add_column_if_missing(con, table, column, sql_type="TEXT"):
    existing = table_columns(con, table)

    if column not in existing:
        con.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
        )


def ensure_order_columns(con):
    """
    Upgrade the existing orders table safely.

    Does not delete existing rows.
    """

    required = {
        "sales_channel": "TEXT",
        "ship_state": "TEXT",
        "ship_city": "TEXT",
        "ship_postal_code": "TEXT",
    }

    for column, sql_type in required.items():
        add_column_if_missing(
            con,
            "orders",
            column,
            sql_type
        )


def ensure_return_columns(con):
    """
    Upgrade the existing returns table safely.

    The original project has a 9-column returns table.
    We retain those columns and add the Amazon-specific fields
    needed by the current return report.
    """

    columns = {
        "return_request_status": "TEXT",
        "return_delivery_date": "TEXT",
        "seller_rma_id": "TEXT",
        "label_type": "TEXT",
        "label_cost": "REAL",
        "currency_code": "TEXT",
        "return_carrier": "TEXT",
        "tracking_id": "TEXT",
        "label_to_be_paid_by": "TEXT",
        "a_to_z_claim": "TEXT",
        "is_prime": "TEXT",
        "in_policy": "TEXT",
        "return_type": "TEXT",
        "resolution": "TEXT",
        "invoice_number": "TEXT",
        "order_amount": "REAL",
        "order_quantity": "INTEGER",
        "safet_action_reason": "TEXT",
        "safet_claim_id": "TEXT",
        "safet_claim_state": "TEXT",
        "safet_claim_creation_time": "TEXT",
        "safet_claim_reimbursement_amount": "REAL",
        "refunded_amount": "REAL",
        "category": "TEXT",
    }

    for column, sql_type in columns.items():
        add_column_if_missing(
            con,
            "returns",
            column,
            sql_type
        )


# ============================================================
# ORDERS IMPORT
# ============================================================

def import_orders(df):
    df = cols(df)

    oid = find(
        df,
        [
            "order_id",
            "order-id",
            "amazon_order_id"
        ],
        True
    )

    od = find(
        df,
        [
            "purchase_date",
            "purchase-date",
            "order_date",
            "order-date"
        ],
        True
    )

    status = find(
        df,
        [
            "order_status",
            "order-status",
            "status"
        ]
    )

    sku = find(
        df,
        [
            "sku",
            "merchant_sku"
        ]
    )

    asin = find(
        df,
        [
            "asin1",
            "asin",
            "product_asin"
        ]
    )

    qty = find(
        df,
        [
            "quantity",
            "quantity_ordered",
            "item_quantity"
        ]
    )

    # ========================================================
    # IMPORTANT:
    # item-price is Sale Price.
    # item-tax is NOT added to Sale Price.
    # ========================================================

    price = find(
        df,
        [
            "item_price",
            "item_price_amount",
            "price"
        ]
    )

    tax = find(
        df,
        [
            "item_tax",
            "item_tax_amount",
            "tax"
        ]
    )

    currency = find(
        df,
        [
            "currency",
            "currency_code"
        ]
    )

    state = find(
        df,
        [
            "ship_state",
            "shipping_state",
            "state"
        ]
    )

    city = find(
        df,
        [
            "ship_city",
            "shipping_city",
            "city"
        ]
    )

    postal = find(
        df,
        [
            "ship_postal_code",
            "ship_postalcode",
            "shipping_postal_code",
            "postal_code",
            "ship_pincode",
            "ship_pin_code",
            "pincode",
            "pin_code",
            "zip"
        ]
    )

    key = find(
        df,
        [
            "order_item_id",
            "order_item_key"
        ]
    )

    w = pd.DataFrame(index=df.index)

    w["order_id"] = text(
        ser(df, oid)
    )

    w["order_date"] = dates(
        ser(df, od)
    )

    w["order_status"] = text(
        ser(df, status)
    )

    w["sku"] = text(
        ser(df, sku)
    )

    w["asin"] = text(
        ser(df, asin)
    )

    w["quantity"] = integer(
        ser(df, qty, "0")
    )

    # Sale Price = item-price ONLY.
    w["item_price"] = num(
        ser(df, price, "0")
    )

    # Tax is stored separately.
    w["item_tax"] = num(
        ser(df, tax, "0")
    )

    w["currency"] = text(
        ser(df, currency)
    )

    w["ship_state"] = text(
        ser(df, state)
    )

    w["ship_city"] = text(
        ser(df, city)
    )

    w["ship_postal_code"] = text(
        ser(df, postal)
    )

    w["order_item_key"] = text(
        ser(df, key)
    )

    w = w[
        w.order_id != ""
    ].copy()

    missing = w.order_item_key == ""

    w.loc[missing, "order_item_key"] = [
        f"{order_id}__ROW_{i}"
        for i, order_id in zip(
            w.index[missing],
            w.loc[missing, "order_id"]
        )
    ]

    con = connect()

    try:
        ensure_order_columns(con)

        # IMPORTANT:
        # Explicit column list avoids errors when the old database
        # has a different table schema/order.
        for r in (
            w.drop_duplicates("order_id")
            .itertuples(index=False)
        ):
            con.execute(
                """
                INSERT OR REPLACE INTO orders
                (
                    order_id,
                    order_date,
                    order_status,
                    sales_channel,
                    ship_state,
                    ship_city,
                    ship_postal_code
                )
                VALUES (?,?,?,?,?,?,?)
                """,
                [
                    sqlite_value(r.order_id),
                    sqlite_value(r.order_date),
                    sqlite_value(r.order_status),
                    "Amazon",
                    sqlite_value(r.ship_state),
                    sqlite_value(r.ship_city),
                    sqlite_value(r.ship_postal_code),
                ]
            )

        # Preserve existing order_items structure.
        order_item_columns = table_columns(
            con,
            "order_items"
        )

        # Current application schema.
        required_item_columns = [
            "order_id",
            "order_item_key",
            "order_date",
            "sku",
            "asin",
            "quantity",
            "item_price",
            "item_tax",
            "currency",
        ]

        # If the existing schema has exactly these fields, use
        # the original INSERT OR REPLACE behavior.
        if all(
            c in order_item_columns
            for c in required_item_columns
        ):
            for r in w.itertuples(index=False):
                con.execute(
                    """
                    INSERT OR REPLACE INTO order_items
                    (
                        order_id,
                        order_item_key,
                        order_date,
                        sku,
                        asin,
                        quantity,
                        item_price,
                        item_tax,
                        currency
                    )
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    [
                        sqlite_value(r.order_id),
                        sqlite_value(r.order_item_key),
                        sqlite_value(r.order_date),
                        sqlite_value(r.sku),
                        sqlite_value(r.asin),
                        sqlite_value(r.quantity),
                        sqlite_value(r.item_price),
                        sqlite_value(r.item_tax),
                        sqlite_value(r.currency),
                    ]
                )

        con.commit()

    finally:
        con.close()

    return len(df), len(w)


# ============================================================
# RETURNS IMPORT
# ============================================================

def import_returns(df):
    df = cols(df)

    # --------------------------------------------------------
    # Exact Amazon Return report mapping supplied by user:
    #
    # order_id
    # order_date
    # return_request_date
    # return_request_status
    # amazon_rma_id
    # seller_rma_id
    # label_type
    # label_cost
    # currency_code
    # return_carrier
    # tracking_id
    # label_to_be_paid_by
    # a_to_z_claim
    # is_prime
    # asin
    # merchant_sku
    # item_name
    # return_quantity
    # return_reason
    # in_policy
    # return_type
    # resolution
    # invoice_number
    # return_delivery_date
    # order_amount
    # order_quantity
    # safet_action_reason
    # safet_claim_id
    # safet_claim_state
    # safet_claim_creation_time
    # safet_claim_reimbursement_amount
    # refunded_amount
    # category
    # order_item_id
    # --------------------------------------------------------

    oid = find(
        df,
        [
            "order_id",
            "order-id",
            "amazon_order_id"
        ],
        True
    )

    # FIX:
    # The Amazon report uses return_request_date.
    rd = find(
        df,
        [
            "return_request_date",
            "return_date",
            "return-date",
            "return_creation_date",
            "return_creation_timestamp",
            "return_date_time",
            "date",
            "authorization_date"
        ],
        True
    )

    return_request_status = find(
        df,
        [
            "return_request_status",
            "return-request-status",
            "return_status",
            "return-status",
            "status"
        ]
    )

    sku = find(
        df,
        [
            "merchant_sku",
            "sku"
        ]
    )

    asin = find(
        df,
        [
            "asin",
            "asin1",
            "product_asin"
        ]
    )

    qty = find(
        df,
        [
            "return_quantity",
            "quantity_returned",
            "return_qty",
            "quantity"
        ]
    )

    reason = find(
        df,
        [
            "return_reason",
            "return-reason",
            "reason",
            "return_reason_code"
        ]
    )

    # Customer comments are not present in the supplied report,
    # so this remains optional.
    comment = find(
        df,
        [
            "customer_comments",
            "customer_comment",
            "comments"
        ]
    )

    # For the current dashboard, resolution is the most useful
    # disposition field.
    disp = find(
        df,
        [
            "resolution",
            "detailed_disposition",
            "disposition"
        ]
    )

    # Amazon RMA is the primary return identifier.
    rid = find(
        df,
        [
            "amazon_rma_id",
            "return_id",
            "return-id",
            "rma_id",
            "rma"
        ]
    )

    return_delivery_date = find(
        df,
        [
            "return_delivery_date"
        ]
    )

    seller_rma_id = find(
        df,
        [
            "seller_rma_id"
        ]
    )

    label_type = find(
        df,
        [
            "label_type"
        ]
    )

    label_cost = find(
        df,
        [
            "label_cost"
        ]
    )

    currency_code = find(
        df,
        [
            "currency_code",
            "currency"
        ]
    )

    return_carrier = find(
        df,
        [
            "return_carrier"
        ]
    )

    tracking_id = find(
        df,
        [
            "tracking_id"
        ]
    )

    label_to_be_paid_by = find(
        df,
        [
            "label_to_be_paid_by"
        ]
    )

    a_to_z_claim = find(
        df,
        [
            "a_to_z_claim"
        ]
    )

    is_prime = find(
        df,
        [
            "is_prime"
        ]
    )

    in_policy = find(
        df,
        [
            "in_policy"
        ]
    )

    return_type = find(
        df,
        [
            "return_type"
        ]
    )

    resolution = find(
        df,
        [
            "resolution"
        ]
    )

    invoice_number = find(
        df,
        [
            "invoice_number"
        ]
    )

    order_amount = find(
        df,
        [
            "order_amount"
        ]
    )

    order_quantity = find(
        df,
        [
            "order_quantity"
        ]
    )

    safet_action_reason = find(
        df,
        [
            "safet_action_reason"
        ]
    )

    safet_claim_id = find(
        df,
        [
            "safet_claim_id"
        ]
    )

    safet_claim_state = find(
        df,
        [
            "safet_claim_state"
        ]
    )

    safet_claim_creation_time = find(
        df,
        [
            "safet_claim_creation_time"
        ]
    )

    safet_claim_reimbursement_amount = find(
        df,
        [
            "safet_claim_reimbursement_amount"
        ]
    )

    refunded_amount = find(
        df,
        [
            "refunded_amount"
        ]
    )

    category = find(
        df,
        [
            "category"
        ]
    )

    w = pd.DataFrame(index=df.index)

    w["order_id"] = text(
        ser(df, oid)
    )

    w["return_date"] = dates(
        ser(df, rd)
    )

    w["return_request_status"] = text(
        ser(df, return_request_status)
    )

    w["sku"] = text(
        ser(df, sku)
    )

    w["asin"] = text(
        ser(df, asin)
    )

    w["quantity"] = integer(
        ser(df, qty, "1")
    )

    w["reason"] = text(
        ser(df, reason)
    )

    w["customer_comment"] = text(
        ser(df, comment)
    )

    w["disposition"] = text(
        ser(df, disp)
    )

    # Primary RMA ID.
    w["return_id"] = text(
        ser(df, rid)
    )

    w = w[
        w.order_id != ""
    ].copy()

    # --------------------------------------------------------
    # Add missing return IDs safely.
    # --------------------------------------------------------
    missing = (
        w.return_id == ""
    )

    w.loc[
        missing,
        "return_id"
    ] = [
        f"{order_id}__RETURN_{i}"
        for i, order_id in zip(
            w.index[missing],
            w.loc[missing, "order_id"]
        )
    ]

    # --------------------------------------------------------
    # Extra Amazon fields.
    # --------------------------------------------------------

    w["return_delivery_date"] = dates(
        ser(df.loc[w.index], return_delivery_date)
    )

    w["seller_rma_id"] = text(
        ser(df.loc[w.index], seller_rma_id)
    )

    w["label_type"] = text(
        ser(df.loc[w.index], label_type)
    )

    w["label_cost"] = num(
        ser(df.loc[w.index], label_cost, "0")
    )

    w["currency_code"] = text(
        ser(df.loc[w.index], currency_code)
    )

    w["return_carrier"] = text(
        ser(df.loc[w.index], return_carrier)
    )

    w["tracking_id"] = text(
        ser(df.loc[w.index], tracking_id)
    )

    w["label_to_be_paid_by"] = text(
        ser(df.loc[w.index], label_to_be_paid_by)
    )

    w["a_to_z_claim"] = text(
        ser(df.loc[w.index], a_to_z_claim)
    )

    w["is_prime"] = text(
        ser(df.loc[w.index], is_prime)
    )

    w["in_policy"] = text(
        ser(df.loc[w.index], in_policy)
    )

    w["return_type"] = text(
        ser(df.loc[w.index], return_type)
    )

    w["resolution"] = text(
        ser(df.loc[w.index], resolution)
    )

    w["invoice_number"] = text(
        ser(df.loc[w.index], invoice_number)
    )

    w["order_amount"] = num(
        ser(df.loc[w.index], order_amount, "0")
    )

    w["order_quantity"] = integer(
        ser(df.loc[w.index], order_quantity, "0")
    )

    w["safet_action_reason"] = text(
        ser(df.loc[w.index], safet_action_reason)
    )

    w["safet_claim_id"] = text(
        ser(df.loc[w.index], safet_claim_id)
    )

    w["safet_claim_state"] = text(
        ser(df.loc[w.index], safet_claim_state)
    )

    w["safet_claim_creation_time"] = text(
        ser(df.loc[w.index], safet_claim_creation_time)
    )

    w["safet_claim_reimbursement_amount"] = num(
        ser(
            df.loc[w.index],
            safet_claim_reimbursement_amount,
            "0"
        )
    )

    w["refunded_amount"] = num(
        ser(df.loc[w.index], refunded_amount, "0")
    )

    w["category"] = text(
        ser(df.loc[w.index], category)
    )

    con = connect()

    try:
        ensure_return_columns(con)

        # ----------------------------------------------------
        # First save the core 9 fields expected by the original
        # dashboard schema.
        # ----------------------------------------------------
        for r in w.itertuples(index=False):
            con.execute(
                """
                INSERT OR REPLACE INTO returns
                (
                    return_id,
                    order_id,
                    return_date,
                    sku,
                    asin,
                    quantity,
                    reason,
                    customer_comment,
                    disposition
                )
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                [
                    sqlite_value(r.return_id),
                    sqlite_value(r.order_id),
                    sqlite_value(r.return_date),
                    sqlite_value(r.sku),
                    sqlite_value(r.asin),
                    sqlite_value(r.quantity),
                    sqlite_value(r.reason),
                    sqlite_value(r.customer_comment),
                    sqlite_value(r.disposition),
                ]
            )

        # ----------------------------------------------------
        # Update the additional Amazon return fields.
        # This is done separately so it works with both the
        # old and upgraded schemas.
        # ----------------------------------------------------
        extra_fields = [
            "return_request_status",
            "return_delivery_date",
            "seller_rma_id",
            "label_type",
            "label_cost",
            "currency_code",
            "return_carrier",
            "tracking_id",
            "label_to_be_paid_by",
            "a_to_z_claim",
            "is_prime",
            "in_policy",
            "return_type",
            "resolution",
            "invoice_number",
            "order_amount",
            "order_quantity",
            "safet_action_reason",
            "safet_claim_id",
            "safet_claim_state",
            "safet_claim_creation_time",
            "safet_claim_reimbursement_amount",
            "refunded_amount",
            "category",
        ]

        current_columns = table_columns(
            con,
            "returns"
        )

        usable_extra = [
            x for x in extra_fields
            if x in current_columns
        ]

        if usable_extra:
            assignments = ", ".join(
                f"{x} = ?"
                for x in usable_extra
            )

            for _, r in w.iterrows():
                values = [
                    sqlite_value(r[x])
                    for x in usable_extra
                ]

                con.execute(
                    f"""
                    UPDATE returns
                    SET {assignments}
                    WHERE return_id = ?
                    """,
                    values + [sqlite_value(r["return_id"])]
                )

        con.commit()

    finally:
        con.close()

    return len(df), len(w)


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def ingest_report(uploaded, report_type):
    init_db()

    df = read_file(uploaded)

    if df.empty:
        raise ValueError(
            "The uploaded report contains no data rows."
        )

    if report_type == "Orders":
        read, imp = import_orders(df)

    elif report_type == "Returns":
        read, imp = import_returns(df)

    else:
        raise ValueError(
            "Unsupported report type."
        )

    return {
        "status": "success",
        "message": (
            f"{report_type} report imported successfully."
        ),
        "report_type": report_type,
        "rows_read": read,
        "rows_imported": imp,
        "rows_skipped": read - imp,
        "columns_detected": list(df.columns),
    }
