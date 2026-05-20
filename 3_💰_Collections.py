"""
dashboard_collections.py  (place in pages/ as  3_💰_Collections.py)
Collections dashboard — pre-defined SQL, no Claude API calls.
Mirrors the Collections Dashboard PDF layout.
"""

import streamlit as st
import pandas as pd
from dashboard_utils import (
    run_query, get_fy_info, fmt, fmt_pct,
    render_kpi_card, render_dashboard_table,
    render_bar_chart, render_line_chart,
)

st.set_page_config(page_title="Collections Dashboard", layout="wide")

AGEING_ORDER = [
    "Within CP", "1-15 days", "16-30 days",
    "31-45 days", "46-60 days", "61-90 days", ">90 days"
]

# ─────────────────────────────────────────────
# FY CONTEXT
# ─────────────────────────────────────────────

fy      = get_fy_info()
CUR_FY  = fy["current_fy"]
PREV_FY = fy["previous_fy"]

# ─────────────────────────────────────────────
# FILTER OPTIONS
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_filter_options():
    def vals(col, include_unassigned=False):
        cond = f"WHERE {col} IS NOT NULL" if include_unassigned \
               else f"WHERE {col} IS NOT NULL AND {col} != 'Unassigned'"
        df = run_query(
            f"SELECT DISTINCT {col} FROM collections {cond} ORDER BY {col}"
        )
        return df[col].tolist()
    return {
        "region":               vals("region", include_unassigned=True),
        "subsidiary_name":      vals("subsidiary_name"),
        "client_journey_stage": vals("client_journey_stage", include_unassigned=True),
        "client_buckets":       vals("client_buckets", include_unassigned=True),
        "collection_status":    vals("collection_status", include_unassigned=True),
        "currency_symbol":      vals("currency_symbol"),
    }

with st.spinner("Loading filters…"):
    opts = load_filter_options()

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────

with st.sidebar:
    st.header("Filters")

    currency = st.radio("Currency", ["INR", "USD"], horizontal=True)
    raw_values = st.toggle("Show raw values", value=False)
    rate_col = "inr_exchangerate" if currency == "INR" else "usd_exchangerate"

    st.divider()
    if st.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ─────────────────────────────────────────────
# WHERE CLAUSE BUILDER
# ─────────────────────────────────────────────

def _add_dim_clauses(clauses):
    def in_clause(col, selections):
        if selections:
            vals = ", ".join(f"'{v}'" for v in selections)
            clauses.append(f"{col} IN ({vals})")
    in_clause("region",               sel_region)
    in_clause("subsidiary_name",      sel_entity)
    in_clause("client_journey_stage", sel_cjs)
    in_clause("client_buckets",       sel_bucket)
    in_clause("collection_status",    sel_status)
    in_clause("currency_symbol",      sel_currency)


def build_where(fy_filter, tds="exclude", include_ic=False):
    """
    tds='exclude' → tds_flag = 'F'  (net collections, default)
    tds='include' → no tds filter   (gross collections)
    tds='only'    → tds_flag = 'T'  (TDS only)
    """
    ic = "'T'" if include_ic else "'F'"
    clauses = [
        f"inter_company_status = {ic}",
        f"transaction_fy_quarter LIKE '{fy_filter}%'",
    ]
    if tds == "exclude":
        clauses.append("tds_flag = 'F'")
    elif tds == "only":
        clauses.append("tds_flag = 'T'")
    _add_dim_clauses(clauses)
    return "WHERE " + "\n  AND ".join(clauses)


def build_dim_filters(tds="exclude", include_ic=False):
    """WHERE without FY filter — used in CASE WHEN KPI queries."""
    ic = "'T'" if include_ic else "'F'"
    clauses = [f"inter_company_status = {ic}"]
    if tds == "exclude":
        clauses.append("tds_flag = 'F'")
    elif tds == "only":
        clauses.append("tds_flag = 'T'")
    _add_dim_clauses(clauses)
    return "WHERE " + "\n  AND ".join(clauses)


# ─────────────────────────────────────────────
# PAGE HEADER + DIMENSION FILTERS
# ─────────────────────────────────────────────

selected_fy = st.session_state.get("collections_fy", CUR_FY)
PREV = PREV_FY if selected_fy == CUR_FY else fy["two_years_ago_fy"]

st.title(f"💰 Collections Dashboard — {selected_fy}")
st.caption(f"External customers only · {currency} · TDS excluded · Compared vs {PREV}")
st.divider()

with st.expander("🔽 Filters", expanded=True):
    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    r2c1, r2c2, r2c3 = st.columns(3)
    with r1c1:
        selected_fy  = st.selectbox("Financial Year", options=[CUR_FY, PREV_FY, fy["two_years_ago_fy"]], index=0, key="collections_fy")
    with r1c2:
        sel_region   = st.multiselect("Region", opts["region"], placeholder="All regions")
    with r1c3:
        sel_entity   = st.multiselect("Billing Entity", opts["subsidiary_name"], placeholder="All entities")
    with r1c4:
        sel_cjs      = st.multiselect("Client Journey Stage", opts["client_journey_stage"], placeholder="All stages")
    with r2c1:
        sel_bucket   = st.multiselect("Client Bucket", opts["client_buckets"], placeholder="All buckets")
    with r2c2:
        sel_status   = st.multiselect("Collection Status", opts["collection_status"], placeholder="All statuses")
    with r2c3:
        sel_currency = st.multiselect("Transaction Currency", opts["currency_symbol"], placeholder="All currencies")

dim_cache_key = (
    tuple(sel_region), tuple(sel_entity), tuple(sel_cjs),
    tuple(sel_bucket), tuple(sel_status), tuple(sel_currency)
)

PREV = PREV_FY if selected_fy == CUR_FY else fy["two_years_ago_fy"]


# ─────────────────────────────────────────────
# SECTION 1 — KPI CARDS
# ─────────────────────────────────────────────

st.subheader("Key Metrics")

@st.cache_data(ttl=300, show_spinner=False)
def load_kpis(fy_filter, prev_filter, rate, dim_key):
    where_net   = build_dim_filters(tds="exclude")
    where_gross = build_dim_filters(tds="include")
    sql = f"""
        SELECT
            SUM(CASE WHEN transaction_fy_quarter LIKE '{fy_filter}%'
                     THEN collection_amount * {rate} ELSE 0 END)  AS ytd_gross,
            SUM(CASE WHEN transaction_fy_quarter LIKE '{prev_filter}%'
                     THEN collection_amount * {rate} ELSE 0 END)  AS prev_gross,
            SUM(CASE WHEN transaction_fy_quarter LIKE '{fy_filter}%'
                     THEN collection_amount * {rate} ELSE 0 END)  AS ytd_net,
            SUM(CASE WHEN transaction_fy_quarter LIKE '{prev_filter}%'
                     THEN collection_amount * {rate} ELSE 0 END)  AS prev_net
        FROM collections
        {where_gross}
    """
    gross = run_query(sql).iloc[0]

    sql_net = f"""
        SELECT
            SUM(CASE WHEN transaction_fy_quarter LIKE '{fy_filter}%'
                     THEN collection_amount * {rate} ELSE 0 END)  AS ytd_net,
            SUM(CASE WHEN transaction_fy_quarter LIKE '{prev_filter}%'
                     THEN collection_amount * {rate} ELSE 0 END)  AS prev_net
        FROM collections
        {where_net}
    """
    net = run_query(sql_net).iloc[0]

    return {
        "ytd_gross":  gross["ytd_gross"],
        "prev_gross": gross["prev_gross"],
        "ytd_net":    net["ytd_net"],
        "prev_net":   net["prev_net"],
    }

with st.spinner("Loading KPIs…"):
    kpi = load_kpis(selected_fy, PREV, rate_col, dim_cache_key)

c1, c2, c3 = st.columns(3)
with c1:
    render_kpi_card("YTD Collections (Incl TDS)",
                    kpi["ytd_gross"], kpi["prev_gross"], currency)
with c2:
    render_kpi_card("YTD Collections (Excl TDS)",
                    kpi["ytd_net"], kpi["prev_net"], currency)
with c3:
    tds_curr = (kpi["ytd_gross"] or 0) - (kpi["ytd_net"] or 0)
    tds_prev = (kpi["prev_gross"] or 0) - (kpi["prev_net"] or 0)
    render_kpi_card("TDS Amount", tds_curr, tds_prev, currency, raw=raw_values)

st.divider()

# ─────────────────────────────────────────────
# SECTION 2 — QoQ COLLECTIONS
# ─────────────────────────────────────────────

st.subheader(f"QoQ Collections — {selected_fy}")

@st.cache_data(ttl=300, show_spinner=False)
def load_qoq(fy_filter, rate, dim_key):
    return run_query(f"""
        SELECT
            transaction_fy_quarter AS quarter,
            SUM(collection_amount * {rate}) AS net_collections
        FROM collections
        {build_where(fy_filter, tds="exclude")}
        GROUP BY quarter
        ORDER BY quarter
    """)

with st.spinner("Loading QoQ…"):
    qoq = load_qoq(selected_fy, rate_col, dim_cache_key)

if not qoq.empty:
    view = st.radio("View", ["Table", "Chart"], horizontal=True,
                    key="qoq_view", label_visibility="collapsed")
    if view == "Table":
        total = qoq["net_collections"].sum()
        grand = pd.DataFrame([{"quarter": "Grand Total", "net_collections": total}])
        qoq_d = pd.concat([qoq, grand], ignore_index=True)
        qoq_d["row_pct"] = qoq_d["net_collections"] / total if total else 0
        qoq_d["net_collections"] = qoq_d["net_collections"].apply(lambda x: fmt(x, currency, raw=raw_values))
        qoq_d["row_pct"]         = qoq_d["row_pct"].apply(fmt_pct)
        qoq_d.columns = ["Quarter", "Collections", "Row %"]
        st.dataframe(qoq_d, width='stretch', hide_index=True)
    else:
        render_line_chart(qoq, "quarter", ["net_collections"],
                         f"QoQ Collections — {selected_fy}", currency, raw=raw_values)

st.divider()

# ─────────────────────────────────────────────
# SECTION 3 — BILLING ENTITY SPLIT
# ─────────────────────────────────────────────

st.subheader("YTD Collections — Billing Entity Split")

@st.cache_data(ttl=300, show_spinner=False)
def load_by_entity(fy_filter, rate, dim_key):
    return run_query(f"""
        SELECT
            subsidiary_name,
            SUM(collection_amount * {rate}) AS amount
        FROM collections
        {build_where(fy_filter, tds="exclude")}
        GROUP BY subsidiary_name
        ORDER BY amount DESC
    """)

with st.spinner("Loading entity split…"):
    ent = load_by_entity(selected_fy, rate_col, dim_cache_key)

if not ent.empty:
    view = st.radio("View", ["Table", "Chart"], horizontal=True,
                    key="entity_view", label_visibility="collapsed")
    total_ent = ent["amount"].sum()
    grand_ent = pd.DataFrame([{"subsidiary_name": "Grand Total", "amount": total_ent}])
    ent_d = pd.concat([ent, grand_ent], ignore_index=True)
    ent_d["row_pct"] = ent_d["amount"] / total_ent if total_ent else 0
    ent_d["row_pct"] = ent_d["row_pct"].apply(fmt_pct)
    ent_d["amount"]  = ent_d["amount"].apply(lambda x: fmt(x, currency, raw=raw_values))
    ent_d.columns    = ["Billing Entity", "Amount", "Row %"]
    if view == "Table":
        st.dataframe(ent_d, width='stretch', hide_index=True)
    else:
        render_bar_chart(ent, "subsidiary_name", "amount",
                         f"Collections by Entity — {selected_fy}",
                         currency, horizontal=False, height=300, raw=raw_values)

st.divider()

# ─────────────────────────────────────────────
# SECTION 4 — CURRENCY SPLIT
# ─────────────────────────────────────────────

st.subheader("YTD Collections — Currency Split")

@st.cache_data(ttl=300, show_spinner=False)
def load_by_currency(fy_filter, rate, dim_key):
    return run_query(f"""
        SELECT
            currency_symbol,
            SUM(collection_amount * {rate}) AS amount
        FROM collections
        {build_where(fy_filter, tds="exclude")}
        GROUP BY currency_symbol
        ORDER BY amount DESC
    """)

with st.spinner("Loading currency split…"):
    cur = load_by_currency(selected_fy, rate_col, dim_cache_key)

if not cur.empty:
    view = st.radio("View", ["Table", "Chart"], horizontal=True,
                    key="currency_view", label_visibility="collapsed")
    total_cur = cur["amount"].sum()
    grand_cur = pd.DataFrame([{"currency_symbol": "Grand Total", "amount": total_cur}])
    cur_d = pd.concat([cur, grand_cur], ignore_index=True)
    cur_d["row_pct"] = cur_d["amount"] / total_cur if total_cur else 0
    cur_d["row_pct"] = cur_d["row_pct"].apply(fmt_pct)
    cur_d["amount"]  = cur_d["amount"].apply(lambda x: fmt(x, currency, raw=raw_values))
    cur_d.columns    = ["Currency", "Amount", "Row %"]
    if view == "Table":
        st.dataframe(cur_d, width='stretch', hide_index=True)
    else:
        render_bar_chart(cur, "currency_symbol", "amount",
                         f"Collections by Currency — {selected_fy}",
                         currency, horizontal=False, height=300, raw=raw_values)

st.divider()

# ─────────────────────────────────────────────
# SECTION 5 — REGION SPLIT
# ─────────────────────────────────────────────

st.subheader("YTD Collections — Region Split")

@st.cache_data(ttl=300, show_spinner=False)
def load_by_region(fy_filter, rate, dim_key):
    return run_query(f"""
        SELECT
            region,
            SUM(collection_amount * {rate}) AS amount
        FROM collections
        {build_where(fy_filter, tds="exclude")}
        GROUP BY region
        ORDER BY amount DESC
    """)

with st.spinner("Loading region split…"):
    reg = load_by_region(selected_fy, rate_col, dim_cache_key)

if not reg.empty:
    view = st.radio("View", ["Table", "Chart"], horizontal=True,
                    key="region_view", label_visibility="collapsed")
    total_reg = reg["amount"].sum()
    grand_reg = pd.DataFrame([{"region": "Grand Total", "amount": total_reg}])
    reg_d = pd.concat([reg, grand_reg], ignore_index=True)
    reg_d["row_pct"] = reg_d["amount"] / total_reg if total_reg else 0
    reg_d["row_pct"] = reg_d["row_pct"].apply(fmt_pct)
    reg_d["amount"]  = reg_d["amount"].apply(lambda x: fmt(x, currency, raw=raw_values))
    reg_d.columns    = ["Region", "Amount", "Row %"]
    if view == "Table":
        st.dataframe(reg_d, width='stretch', hide_index=True)
    else:
        render_bar_chart(reg, "region", "amount",
                         f"Collections by Region — {selected_fy}",
                         currency, horizontal=False, height=350, raw=raw_values)

st.divider()

# ─────────────────────────────────────────────
# SECTION 6 — TOP 20 CUSTOMERS
# ─────────────────────────────────────────────

st.subheader("Top 20 Customers — YTD Collections")

@st.cache_data(ttl=300, show_spinner=False)
def load_top_customers(fy_filter, rate, dim_key):
    return run_query(f"""
        SELECT
            customer_name,
            SUM(collection_amount * {rate}) AS amount
        FROM collections
        {build_where(fy_filter, tds="exclude")}
          AND customer_name IS NOT NULL
        GROUP BY customer_name
        ORDER BY amount DESC
        LIMIT 20
    """)

with st.spinner("Loading top customers…"):
    cust = load_top_customers(selected_fy, rate_col, dim_cache_key)

if not cust.empty:
    tab_t, tab_c = st.tabs(["Table", "Chart"])
    with tab_t:
        total_cust = cust["amount"].sum()
        cust_d = cust.copy()
        cust_d["row_pct"] = cust_d["amount"] / total_cust if total_cust else 0
        cust_d["row_pct"] = cust_d["row_pct"].apply(fmt_pct)
        cust_d["amount"]  = cust_d["amount"].apply(lambda x: fmt(x, currency, raw=raw_values))
        cust_d.columns    = ["Customer", "Amount", "Row %"]
        st.dataframe(cust_d, width='stretch', hide_index=True)
    with tab_c:
        render_bar_chart(cust, "customer_name", "amount",
                         f"Top 20 Customers — {selected_fy}",
                         currency, horizontal=True,
                         height=max(400, len(cust) * 28))

st.divider()

# ─────────────────────────────────────────────
# SECTION 7 — INTERCOMPANY COLLECTIONS
# ─────────────────────────────────────────────

st.subheader("Intercompany Collections")

@st.cache_data(ttl=300, show_spinner=False)
def load_intercompany(fy_filter, rate, dim_key):
    return run_query(f"""
        SELECT
            TRIM(paying_entity)  AS paying_entity,
            subsidiary_name      AS receiving_entity,
            SUM(collection_amount * {rate}) AS amount
        FROM collections
        {build_where(fy_filter, tds="exclude", include_ic=True)}
        GROUP BY TRIM(paying_entity), subsidiary_name
    """)

with st.spinner("Loading intercompany…"):
    ic = load_intercompany(selected_fy, rate_col, dim_cache_key)

if not ic.empty:
    pivot = ic.pivot_table(
        index="paying_entity", columns="receiving_entity",
        values="amount", aggfunc="sum", fill_value=0
    ).reset_index()

    recv_cols = [c for c in pivot.columns if c != "paying_entity"]
    pivot["Row Total"] = pivot[recv_cols].sum(axis=1)
    grand = {"paying_entity": "Grand Total"}
    for c in recv_cols + ["Row Total"]:
        grand[c] = pivot[c].sum()
    pivot = pd.concat([pivot, pd.DataFrame([grand])], ignore_index=True)

    total_ic = grand["Row Total"]
    pivot.insert(1, "Row %", pivot["Row Total"] / total_ic if total_ic else 0)

    pivot_disp = pivot.copy()
    pivot_disp["Row %"] = pivot_disp["Row %"].apply(fmt_pct)
    for c in recv_cols + ["Row Total"]:
        pivot_disp[c] = pivot_disp[c].apply(lambda x: fmt(x, currency, raw=raw_values))
    pivot_disp = pivot_disp.rename(
        columns={"paying_entity": "Paying Entity ↓ / Receiving Entity →"}
    )
    st.dataframe(pivot_disp, width='stretch', hide_index=True)
else:
    st.info("No intercompany collections data for this period.")

st.divider()

# ─────────────────────────────────────────────
# SECTION 8 — CUMULATIVE AGEING ANALYSIS
# ─────────────────────────────────────────────

st.subheader("Cumulative Ageing Analysis")
st.caption("Each quarter shows collected amounts by ageing bucket, with cumulative % in the row below.")

@st.cache_data(ttl=300, show_spinner=False)
def load_ageing(fy_filter, rate, dim_key):
    return run_query(f"""
        SELECT
            transaction_fy_quarter AS quarter,
            ageingbucket,
            SUM(collection_amount * {rate}) AS amount
        FROM collections
        {build_where(fy_filter, tds="exclude")}
        GROUP BY quarter, ageingbucket
        ORDER BY quarter, ageingbucket
    """)

with st.spinner("Loading ageing analysis…"):
    age = load_ageing(selected_fy, rate_col, dim_cache_key)

if not age.empty:
    # Pivot: quarters × ageing buckets
    age_pivot = age.pivot_table(
        index="quarter", columns="ageingbucket",
        values="amount", aggfunc="sum", fill_value=0
    ).reset_index()

    # Reorder ageing columns
    existing_buckets = [b for b in AGEING_ORDER if b in age_pivot.columns]
    age_pivot = age_pivot[["quarter"] + existing_buckets]
    age_pivot["Row Total"] = age_pivot[existing_buckets].sum(axis=1)

    # Grand total row
    grand_age = {"quarter": "Grand Total"}
    for c in existing_buckets + ["Row Total"]:
        grand_age[c] = age_pivot[c].sum()
    age_pivot = pd.concat([age_pivot, pd.DataFrame([grand_age])], ignore_index=True)

    # Build display with interleaved cumulative % rows
    rows = []
    for _, row in age_pivot.iterrows():
        total = row["Row Total"]
        amount_row = {"Financial Quarter": row["quarter"]}
        for b in existing_buckets:
            amount_row[b] = fmt(row[b], currency, raw=raw_values)
        amount_row["Row Total"] = fmt(total, currency, raw=raw_values)
        amount_row["Row %"] = fmt_pct(total / age_pivot.iloc[:-1]["Row Total"].sum()
                                      if age_pivot.iloc[:-1]["Row Total"].sum() and
                                      row["quarter"] != "Grand Total" else
                                      (1.0 if row["quarter"] == "Grand Total" else 0))
        rows.append(amount_row)

        # Add cumulative % row (skip for Grand Total)
        if row["quarter"] != "Grand Total":
            cum_row = {"Financial Quarter": f"{row['quarter']} (Cumulative %)"}
            running = 0
            for b in existing_buckets:
                running += row[b]
                cum_row[b] = fmt_pct(running / total) if total else "—"
            cum_row["Row Total"] = "100.0%"
            cum_row["Row %"] = ""
            rows.append(cum_row)

    display_df = pd.DataFrame(rows)
    st.dataframe(display_df, width='stretch', hide_index=True)