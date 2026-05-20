"""
customer_master.py  (place in pages/ as  8_🏢_Customer_Master.py)
Customer Master — full customer list with balances, segmentation, and dimensions.
No Claude API calls — pure SQL → DataFrame → Streamlit.
"""

import streamlit as st
import pandas as pd
from dashboard_utils import run_query, fmt, fmt_pct, render_kpi_card, render_bar_chart

st.set_page_config(page_title="Customer Master", layout="wide")

# ─────────────────────────────────────────────
# BASE CTE
# All queries in this page wrap this CTE so the
# source definition lives in exactly one place.
# ─────────────────────────────────────────────

CUSTOMER_MASTER_CTE = """
WITH customer_refined AS (
    SELECT
        custentity_cust_ucc          AS customer_ucc,
        companyname                  AS customer_name,
        entityid                     AS entity_id,
        balancesearch                AS balance,
        overduebalancesearch         AS overdue_balance,
        custentity_permanent_account_number AS pan,
        currency                     AS currency_id,
        email                        AS customer_email,
        id                           AS customer_id,
        custentity_cust_ucc_parent   AS ucc_parent
    FROM customer
),
customer_master AS (
    SELECT
        cr.*,
        er.symbol                           AS currency_symbol,
        er.inr_exchangerate,
        er.usd_exchangerate,
        COALESCE(u.region,           'Unassigned') AS region,
        COALESCE(u.country,          'Unassigned') AS country,
        COALESCE(u.cjs,              'Unassigned') AS client_journey_stage,
        COALESCE(u.client_buckets,   'Unassigned') AS client_buckets,
        COALESCE(u.collection_status,'Unassigned') AS collection_status
    FROM customer_refined cr
    LEFT JOIN exchangerate er
        ON cr.currency_id = er.id
    LEFT JOIN ucctoregioncustomerstatusmastermapping u
        ON cr.customer_ucc = u.ucc
)
"""


# ─────────────────────────────────────────────
# FILTER OPTIONS
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_filter_options():
    def vals(query):
        return run_query(query).iloc[:, 0].tolist()

    base = f"{CUSTOMER_MASTER_CTE} SELECT * FROM customer_master"

    def distinct(col, include_unassigned=True):
        cond = (f"WHERE {col} IS NOT NULL"
                if include_unassigned
                else f"WHERE {col} IS NOT NULL AND {col} != 'Unassigned'")
        return vals(
            f"{CUSTOMER_MASTER_CTE} "
            f"SELECT DISTINCT {col} FROM customer_master "
            f"{cond} ORDER BY {col}"
        )

    return {
        "region":               distinct("region",            include_unassigned=True),
        "country":              distinct("country",           include_unassigned=True),
        "client_journey_stage": distinct("client_journey_stage", include_unassigned=True),
        "client_buckets":       distinct("client_buckets",    include_unassigned=True),
        "collection_status":    distinct("collection_status", include_unassigned=True),
        "currency_symbol":      distinct("currency_symbol",   include_unassigned=False),
    }

with st.spinner("Loading filters…"):
    opts = load_filter_options()


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────

with st.sidebar:
    st.header("Settings")
    currency   = st.radio("Currency", ["USD", "INR"], horizontal=True)
    raw_values = st.toggle("Show raw values", value=False)
    rate_col   = "usd_exchangerate" if currency == "USD" else "inr_exchangerate"

    st.divider()
    exclude_internal = st.toggle(
        "Exclude internal entities",
        value=True,
        help="Hides customers whose name contains 'Darwinbox' or 'Compport'",
    )

    st.divider()
    if st.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ─────────────────────────────────────────────
# WHERE CLAUSE BUILDER
# ─────────────────────────────────────────────

def _add_dim_clauses(clauses: list):
    def in_clause(col, selections):
        if selections:
            v = ", ".join(f"'{s}'" for s in selections)
            clauses.append(f"{col} IN ({v})")
    in_clause("region",               sel_region)
    in_clause("country",              sel_country)
    in_clause("client_journey_stage", sel_cjs)
    in_clause("client_buckets",       sel_bucket)
    in_clause("collection_status",    sel_status)
    in_clause("currency_symbol",      sel_curr)
    if exclude_internal:
        clauses.append("customer_name NOT ILIKE '%darwinbox%'")
        clauses.append("customer_name NOT ILIKE '%compport%'")


def build_where() -> str:
    clauses = []
    _add_dim_clauses(clauses)
    if not clauses:
        return ""
    return "WHERE " + "\n  AND ".join(clauses)


# ─────────────────────────────────────────────
# PAGE HEADER + DIMENSION FILTERS
# ─────────────────────────────────────────────

st.title("🏢 Customer Master")
st.caption(f"Full customer list with live balances · {currency}")

with st.expander("🔽 Filters", expanded=True):
    r1c1, r1c2, r1c3 = st.columns(3)
    r2c1, r2c2, r2c3 = st.columns(3)
    with r1c1:
        sel_region  = st.multiselect("Region",               opts["region"],               placeholder="All regions")
    with r1c2:
        sel_country = st.multiselect("Country",              opts["country"],              placeholder="All countries")
    with r1c3:
        sel_cjs     = st.multiselect("Client Journey Stage", opts["client_journey_stage"], placeholder="All stages")
    with r2c1:
        sel_bucket  = st.multiselect("Client Bucket",        opts["client_buckets"],       placeholder="All buckets")
    with r2c2:
        sel_status  = st.multiselect("Collection Status",    opts["collection_status"],    placeholder="All statuses")
    with r2c3:
        sel_curr    = st.multiselect("Transaction Currency", opts["currency_symbol"],      placeholder="All currencies")

dim_cache_key = (
    currency,
    tuple(sel_region), tuple(sel_country), tuple(sel_cjs),
    tuple(sel_bucket), tuple(sel_status), tuple(sel_curr),
    exclude_internal,
)

st.divider()


# ─────────────────────────────────────────────
# SECTION 1 — KPI CARDS
# ─────────────────────────────────────────────

st.subheader("Key Metrics")

@st.cache_data(ttl=300, show_spinner=False)
def load_kpis(rate, dim_key):
    where = build_where()
    # balance / overdue_balance are in transaction currency → convert with rate
    return run_query(f"""
        {CUSTOMER_MASTER_CTE}
        SELECT
            COUNT(*)                                                        AS total_customers,
            COUNT(CASE WHEN balance > 0 THEN 1 END)                        AS customers_with_balance,
            SUM(balance       * {rate})                                     AS total_balance,
            SUM(overdue_balance * {rate})                                   AS total_overdue_balance
        FROM customer_master
        {where}
    """).iloc[0]

with st.spinner("Loading KPIs…"):
    kpi = load_kpis(rate_col, dim_cache_key)

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f"""
    <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;
                padding:16px 20px;height:100%;">
        <div style="font-size:12px;color:#6b7280;font-weight:500;
                    text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px;">
            Total Customers</div>
        <div style="font-size:26px;font-weight:700;color:#111827;margin-bottom:4px;">
            {int(kpi['total_customers'] or 0):,}</div>
        <div style="font-size:13px;color:#9ca3af;">active records</div>
    </div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""
    <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;
                padding:16px 20px;height:100%;">
        <div style="font-size:12px;color:#6b7280;font-weight:500;
                    text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px;">
            With Open Balance</div>
        <div style="font-size:26px;font-weight:700;color:#111827;margin-bottom:4px;">
            {int(kpi['customers_with_balance'] or 0):,}</div>
        <div style="font-size:13px;color:#9ca3af;">
            {fmt_pct(int(kpi['customers_with_balance'] or 0) / max(int(kpi['total_customers'] or 1), 1))} of total
        </div>
    </div>""", unsafe_allow_html=True)
with c3:
    render_kpi_card("Total Balance",         kpi["total_balance"],         currency=currency, vs_label="", raw=raw_values)
with c4:
    render_kpi_card("Total Overdue Balance", kpi["total_overdue_balance"], currency=currency, vs_label="", raw=raw_values)


st.divider()


# ─────────────────────────────────────────────
# SECTION 2 — BREAKDOWN CHARTS
# ─────────────────────────────────────────────

# ── By Client Bucket ──────────────────────────
st.subheader("By Client Bucket")

@st.cache_data(ttl=300, show_spinner=False)
def load_by_bucket(rate, dim_key):
    where = build_where()
    return run_query(f"""
        {CUSTOMER_MASTER_CTE}
        SELECT
            client_buckets,
            COUNT(*)                        AS customer_count,
            SUM(balance * {rate})           AS total_balance,
            SUM(overdue_balance * {rate})   AS total_overdue
        FROM customer_master
        {where}
        GROUP BY client_buckets
        ORDER BY total_balance DESC NULLS LAST
    """)

with st.spinner("Loading bucket breakdown…"):
    bkt = load_by_bucket(rate_col, dim_cache_key)

if not bkt.empty:
    view_bkt = st.radio("View", ["Table", "Chart"], horizontal=True,
                        key="bkt_view", label_visibility="collapsed")
    if view_bkt == "Table":
        total_b = bkt["total_balance"].sum()
        bkt_d   = bkt.copy()
        bkt_d["pct"] = (bkt_d["total_balance"] / total_b).apply(fmt_pct)
        grand_bkt = pd.DataFrame([{
            "client_buckets": "Grand Total",
            "customer_count": int(bkt["customer_count"].sum()),
            "total_balance":  bkt["total_balance"].sum(),
            "total_overdue":  bkt["total_overdue"].sum(),
            "pct":            "100.0%",
        }])
        bkt_d = pd.concat([bkt_d, grand_bkt], ignore_index=True)
        bkt_d["total_balance"] = bkt_d["total_balance"].apply(lambda x: fmt(x, currency, raw=raw_values))
        bkt_d["total_overdue"] = bkt_d["total_overdue"].apply(lambda x: fmt(x, currency, raw=raw_values))
        bkt_d.columns          = ["Client Bucket", "Customers", "Balance", "Overdue", "% of Total"]
        st.dataframe(bkt_d, width="stretch", hide_index=True)
    else:
        render_bar_chart(bkt, "client_buckets", "total_balance",
                         "Balance by Client Bucket", currency, raw=raw_values)

st.divider()

# ── By Client Journey Stage ────────────────────
st.subheader("By Client Journey Stage")

@st.cache_data(ttl=300, show_spinner=False)
def load_by_cjs(rate, dim_key):
    where = build_where()
    return run_query(f"""
        {CUSTOMER_MASTER_CTE}
        SELECT
            client_journey_stage,
            COUNT(*)                        AS customer_count,
            SUM(balance * {rate})           AS total_balance,
            SUM(overdue_balance * {rate})   AS total_overdue
        FROM customer_master
        {where}
        GROUP BY client_journey_stage
        ORDER BY total_balance DESC NULLS LAST
    """)

with st.spinner("Loading CJS breakdown…"):
    cjs = load_by_cjs(rate_col, dim_cache_key)

if not cjs.empty:
    view_cjs = st.radio("View", ["Table", "Chart"], horizontal=True,
                        key="cjs_view", label_visibility="collapsed")
    if view_cjs == "Table":
        total_c = cjs["total_balance"].sum()
        cjs_d   = cjs.copy()
        cjs_d["pct"] = (cjs_d["total_balance"] / total_c).apply(fmt_pct)
        grand_cjs = pd.DataFrame([{
            "client_journey_stage": "Grand Total",
            "customer_count":       int(cjs["customer_count"].sum()),
            "total_balance":        cjs["total_balance"].sum(),
            "total_overdue":        cjs["total_overdue"].sum(),
            "pct":                  "100.0%",
        }])
        cjs_d = pd.concat([cjs_d, grand_cjs], ignore_index=True)
        cjs_d["total_balance"] = cjs_d["total_balance"].apply(lambda x: fmt(x, currency, raw=raw_values))
        cjs_d["total_overdue"] = cjs_d["total_overdue"].apply(lambda x: fmt(x, currency, raw=raw_values))
        cjs_d.columns          = ["Client Journey Stage", "Customers", "Balance", "Overdue", "% of Total"]
        st.dataframe(cjs_d, width="stretch", hide_index=True)
    else:
        render_bar_chart(cjs, "client_journey_stage", "total_balance",
                         "Balance by Client Journey Stage", currency, raw=raw_values)

st.divider()


# ─────────────────────────────────────────────
# SECTION 3 — BY REGION
# ─────────────────────────────────────────────

st.subheader("By Region")

@st.cache_data(ttl=300, show_spinner=False)
def load_by_region(rate, dim_key):
    where = build_where()
    return run_query(f"""
        {CUSTOMER_MASTER_CTE}
        SELECT
            region,
            COUNT(*)                        AS customer_count,
            SUM(balance * {rate})           AS total_balance,
            SUM(overdue_balance * {rate})   AS total_overdue
        FROM customer_master
        {where}
        GROUP BY region
        ORDER BY total_balance DESC NULLS LAST
    """)

with st.spinner("Loading region breakdown…"):
    reg = load_by_region(rate_col, dim_cache_key)

if not reg.empty:
    view_reg = st.radio("View", ["Table", "Chart"], horizontal=True,
                        key="reg_view", label_visibility="collapsed")
    if view_reg == "Table":
        total_r = reg["total_balance"].sum()
        reg_d   = reg.copy()
        reg_d["pct"] = (reg_d["total_balance"] / total_r).apply(fmt_pct)
        grand_reg = pd.DataFrame([{
            "region":         "Grand Total",
            "customer_count": int(reg["customer_count"].sum()),
            "total_balance":  reg["total_balance"].sum(),
            "total_overdue":  reg["total_overdue"].sum(),
            "pct":            "100.0%",
        }])
        reg_d = pd.concat([reg_d, grand_reg], ignore_index=True)
        reg_d["total_balance"] = reg_d["total_balance"].apply(lambda x: fmt(x, currency, raw=raw_values))
        reg_d["total_overdue"] = reg_d["total_overdue"].apply(lambda x: fmt(x, currency, raw=raw_values))
        reg_d.columns          = ["Region", "Customers", "Balance", "Overdue", "% of Total"]
        st.dataframe(reg_d, width="stretch", hide_index=True)
    else:
        render_bar_chart(reg, "region", "total_balance",
                         "Balance by Region", currency,
                         horizontal=True, height=max(350, len(reg) * 36),
                         raw=raw_values)

st.divider()


# ─────────────────────────────────────────────
# SECTION 4 — FULL CUSTOMER TABLE
# ─────────────────────────────────────────────

st.subheader("Customer Directory")

# Search + column visibility controls
search_col, toggle_col = st.columns([3, 1])
with search_col:
    search = st.text_input(
        "🔍 Search", placeholder="Customer name, UCC, or entity ID…",
        label_visibility="collapsed",
    )
with toggle_col:
    show_finance = st.toggle("Show balance columns", value=True)

@st.cache_data(ttl=300, show_spinner=False)
def load_customer_table(rate, dim_key):
    where = build_where()
    return run_query(f"""
        {CUSTOMER_MASTER_CTE}
        SELECT
            customer_ucc,
            customer_name,
            entity_id,
            pan,
            currency_symbol,
            ucc_parent,
            region,
            country,
            client_journey_stage,
            client_buckets,
            collection_status,
            balance         * {rate}   AS balance_converted,
            overdue_balance * {rate}   AS overdue_balance_converted
        FROM customer_master
        {where}
        ORDER BY balance_converted DESC NULLS LAST
    """)

with st.spinner("Loading customer directory…"):
    cust_df = load_customer_table(rate_col, dim_cache_key)

if not cust_df.empty:
    # Apply search filter across text columns
    if search:
        s = search.lower()
        mask = (
            cust_df["customer_name"].fillna("").str.lower().str.contains(s, regex=False) |
            cust_df["customer_ucc"].fillna("").str.lower().str.contains(s, regex=False) |
            cust_df["entity_id"].fillna("").str.lower().str.contains(s, regex=False)
        )
        cust_df = cust_df[mask]

    st.caption(f"{len(cust_df):,} customers")

    display_df = cust_df.copy()

    # Format balance columns
    if show_finance:
        display_df["balance_converted"] = display_df["balance_converted"].apply(
            lambda x: fmt(x, currency, raw=raw_values) if pd.notnull(x) else "—"
        )
        display_df["overdue_balance_converted"] = display_df["overdue_balance_converted"].apply(
            lambda x: fmt(x, currency, raw=raw_values) if pd.notnull(x) else "—"
        )
    else:
        display_df = display_df.drop(columns=["balance_converted", "overdue_balance_converted"])

    # Rename for display
    rename_map = {
        "customer_ucc":              "UCC",
        "customer_name":             "Customer Name",
        "entity_id":                 "Entity ID",
        "pan":                       "PAN",
        "currency_symbol":           "Currency",
        "ucc_parent":                "Parent UCC",
        "region":                    "Region",
        "country":                   "Country",
        "client_journey_stage":      "CJS",
        "client_buckets":            "Client Bucket",
        "collection_status":         "Collection Status",
        "balance_converted":         f"Balance ({currency})",
        "overdue_balance_converted": f"Overdue Balance ({currency})",
    }
    display_df = display_df.rename(columns=rename_map)

    st.dataframe(display_df, width="stretch", hide_index=True)
else:
    st.info("No customers found for the selected filters.")