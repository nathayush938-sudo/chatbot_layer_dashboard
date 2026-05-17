"""
dashboard_billing.py  (place in pages/ folder as  2_📋_Billing.py)
Billing dashboard — pre-defined SQL, no Claude API calls.
Mirrors the Billing Dashboard PDF layout.
"""

import streamlit as st
import pandas as pd
from dashboard_utils import (
    run_query, get_fy_info, fmt, fmt_pct,
    render_kpi_card, render_dashboard_table,
    render_bar_chart, render_line_chart,
)

st.set_page_config(page_title="Billing Dashboard", layout="wide")

# ─────────────────────────────────────────────
# FY CONTEXT + SIDEBAR FILTER
# ─────────────────────────────────────────────

fy      = get_fy_info()
CUR_FY  = fy["current_fy"]
PREV_FY = fy["previous_fy"]

# ─────────────────────────────────────────────
# LOAD FILTER OPTIONS FROM DB
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_filter_options():
    """Load distinct dimension values for sidebar filters. Cached for 1 hour."""
    def vals(col, include_unassigned=False):
        condition = f"WHERE {col} IS NOT NULL" if include_unassigned else f"WHERE {col} IS NOT NULL AND {col} != 'Unassigned'"
        df = run_query(f"SELECT DISTINCT {col} FROM billing {condition} ORDER BY {col}")
        return df[col].tolist()
    return {
        "region":               vals("region", include_unassigned=True),
        "subsidiary_name":      vals("subsidiary_name"),
        "client_journey_stage": vals("client_journey_stage", include_unassigned=True),
        "client_buckets":       vals("client_buckets", include_unassigned=True),
        "collection_status":    vals("collection_status", include_unassigned=True),
        "transaction_type":     vals("transaction_type"),
        "currency_symbol":      vals("currency_symbol"),
    }

with st.spinner("Loading filters…"):
    opts = load_filter_options()

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────

with st.sidebar:
    st.header("Filters")

    selected_fy = st.selectbox(
        "Financial Year",
        options=[CUR_FY, PREV_FY, fy["two_years_ago_fy"]],
        index=0,
    )
    currency = st.radio("Currency", ["USD", "INR"], horizontal=True)
    rate_col = "usd_exchangerate" if currency == "USD" else "inr_exchangerate"

    st.divider()
    st.subheader("Dimensions")

    sel_region = st.multiselect(
        "Region", opts["region"], placeholder="All regions"
    )
    sel_entity = st.multiselect(
        "Billing Entity", opts["subsidiary_name"], placeholder="All entities"
    )
    sel_cjs = st.multiselect(
        "Client Journey Stage", opts["client_journey_stage"], placeholder="All stages"
    )
    sel_bucket = st.multiselect(
        "Client Bucket", opts["client_buckets"], placeholder="All buckets"
    )
    sel_status = st.multiselect(
        "Collection Status", opts["collection_status"], placeholder="All statuses"
    )
    sel_txn_type = st.multiselect(
        "Transaction Type", opts["transaction_type"], placeholder="All types"
    )
    sel_currency = st.multiselect(
        "Transaction Currency", opts["currency_symbol"], placeholder="All currencies"
    )

    st.divider()
    if st.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

PREV = PREV_FY if selected_fy == CUR_FY else fy["two_years_ago_fy"]


# ─────────────────────────────────────────────
# WHERE CLAUSE BUILDER
# ─────────────────────────────────────────────

def build_where(fy_filter: str, include_ic: bool = False) -> str:
    """
    Build a SQL WHERE clause from sidebar filter selections.
    fy_filter:  e.g. 'FY26' — applied as LIKE 'FY26%'
    include_ic: True for intercompany queries (inter_company_status = 'T')
    """
    ic_filter = "'T'" if include_ic else "'F'"
    clauses = [
        f"inter_company_status = {ic_filter}",
        f"transaction_fy_quarter LIKE '{fy_filter}%'",
    ]
    _add_dim_clauses(clauses)
    return "WHERE " + "\n  AND ".join(clauses)


def build_dim_filters(include_ic: bool = False) -> str:
    """
    WHERE clause with IC status + dimension filters but NO FY filter.
    Used by the KPI query which handles FY via CASE WHEN.
    """
    ic_filter = "'T'" if include_ic else "'F'"
    clauses   = [f"inter_company_status = {ic_filter}"]
    _add_dim_clauses(clauses)
    return "WHERE " + "\n  AND ".join(clauses)


def _add_dim_clauses(clauses: list):
    """Append selected dimension filter conditions to a clauses list."""
    def in_clause(col, selections):
        if selections:
            vals = ", ".join(f"'{v}'" for v in selections)
            clauses.append(f"{col} IN ({vals})")

    in_clause("region",               sel_region)
    in_clause("subsidiary_name",      sel_entity)
    in_clause("client_journey_stage", sel_cjs)
    in_clause("client_buckets",       sel_bucket)
    in_clause("collection_status",    sel_status)
    in_clause("transaction_type",     sel_txn_type)
    in_clause("currency_symbol",      sel_currency)

st.title(f"📋 Billing Dashboard — {selected_fy}")
st.caption(f"External customers only · {currency} · Compared vs {PREV}")
st.divider()


# ─────────────────────────────────────────────
# SECTION 1 — KPI CARDS
# ─────────────────────────────────────────────

st.subheader("Key Metrics")

@st.cache_data(ttl=300, show_spinner=False)
def load_kpis(fy_filter, prev_filter, rate, dim_key):
    where = build_dim_filters()
    sql = f"""
        SELECT
            SUM(CASE WHEN transaction_fy_quarter LIKE '{fy_filter}%'
                     THEN billing_amount * {rate} ELSE 0 END)                          AS ytd_incl,
            SUM(CASE WHEN transaction_fy_quarter LIKE '{fy_filter}%'
                     THEN (billing_amount - COALESCE(transaction_tax,0)) * {rate} ELSE 0 END) AS ytd_excl,
            SUM(CASE WHEN transaction_fy_quarter LIKE '{prev_filter}%'
                     THEN billing_amount * {rate} ELSE 0 END)                          AS prev_incl,
            SUM(CASE WHEN transaction_fy_quarter LIKE '{prev_filter}%'
                     THEN (billing_amount - COALESCE(transaction_tax,0)) * {rate} ELSE 0 END) AS prev_excl
        FROM billing
        {where}
    """
    return run_query(sql).iloc[0]

# Build a hashable key from current dimension selections for cache busting
dim_cache_key = (
    tuple(sel_region), tuple(sel_entity), tuple(sel_cjs),
    tuple(sel_bucket), tuple(sel_status), tuple(sel_txn_type), tuple(sel_currency)
)

with st.spinner("Loading KPIs…"):
    kpi = load_kpis(selected_fy, PREV, rate_col, dim_cache_key)

c1, c2, c3 = st.columns(3)
with c1:
    render_kpi_card("YTD Billing (Tax Incl.)",
                    kpi["ytd_incl"], kpi["prev_incl"], currency)
with c2:
    render_kpi_card("YTD Billing (Tax Excl.)",
                    kpi["ytd_excl"], kpi["prev_excl"], currency)
with c3:
    render_kpi_card("Tax Amount",
                    kpi["ytd_incl"] - kpi["ytd_excl"] if kpi["ytd_incl"] else 0,
                    kpi["prev_incl"] - kpi["prev_excl"] if kpi["prev_incl"] else 0,
                    currency)

st.divider()

# ─────────────────────────────────────────────
# SECTION 2 — QoQ TREND
# ─────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def load_qoq(fy_filter, rate, dim_key):
    return run_query(f"""
        SELECT
            transaction_fy_quarter AS quarter,
            SUM(billing_amount * {rate})                                            AS billed_incl,
            SUM((billing_amount - COALESCE(transaction_tax,0)) * {rate})            AS billed_excl
        FROM billing
        {build_where(fy_filter)}
        GROUP BY quarter
        ORDER BY quarter
    """)

with st.spinner("Loading QoQ…"):
    qoq = load_qoq(selected_fy, rate_col, dim_cache_key)

st.subheader(f"QoQ Billing — {selected_fy}")
if not qoq.empty:
    view = st.radio("", ["Table", "Chart"], horizontal=True,
                    key="qoq_view", label_visibility="collapsed")
    if view == "Table":
        qoq_display = qoq.copy()
        total_incl  = qoq_display["billed_incl"].sum()
        total_excl  = qoq_display["billed_excl"].sum()
        grand       = pd.DataFrame([{
            "quarter":      "Grand Total",
            "billed_incl":  total_incl,
            "billed_excl":  total_excl,
        }])
        qoq_display = pd.concat([qoq_display, grand], ignore_index=True)
        qoq_display["pct_of_total"] = qoq_display["billed_incl"] / total_incl if total_incl else 0
        qoq_display["billed_incl"]  = qoq_display["billed_incl"].apply(lambda x: fmt(x, currency))
        qoq_display["pct_of_total"] = qoq_display["pct_of_total"].apply(fmt_pct)
        qoq_display["billed_excl"]  = qoq_display["billed_excl"].apply(lambda x: fmt(x, currency))
        qoq_display = qoq_display[["quarter", "billed_incl", "pct_of_total", "billed_excl"]]
        qoq_display.columns = ["Quarter", "Billed (Incl Tax)", "Incl Tax %", "Billed (Excl Tax)"]
        st.dataframe(qoq_display, width='stretch', hide_index=True)
    else:
        render_line_chart(qoq, "quarter", ["billed_incl", "billed_excl"],
                         f"QoQ Billing — {selected_fy}", currency)

st.divider()

# ─────────────────────────────────────────────
# SECTION 3 — INVOICE TYPE SPLIT
# ─────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def load_type_split(fy_filter, rate, dim_key):
    return run_query(f"""
        SELECT
            SUM(subscriptionfee    * {rate})                                                        AS subscription,
            SUM(implementationfee  * {rate})                                                        AS implementation,
            SUM(integrationfee     * {rate})                                                        AS integration,
            SUM(studiofee          * {rate})                                                        AS studio,
            SUM((COALESCE(amsfee,0)+COALESCE(otherservicesfee,0)+COALESCE(openingsplitfee,0))*{rate}) AS other_services,
            SUM(COALESCE(transaction_tax,0) * {rate})                                               AS tax_amount
        FROM billing
        {build_where(fy_filter)}
    """)

with st.spinner("Loading type split…"):
    ts_raw = load_type_split(selected_fy, rate_col, dim_cache_key)

st.subheader("YTD Billing — Invoice Type Split")
if not ts_raw.empty:
    row    = ts_raw.iloc[0]
    labels = {
        "subscription":    "Subscription Revenue",
        "implementation":  "Implementation Revenue",
        "integration":     "Integration Revenue",
        "studio":          "Studio Revenue",
        "other_services":  "Other Services Revenue",
        "tax_amount":      "Tax Amount",
    }
    total  = sum(row[k] for k in labels if pd.notnull(row[k]))
    ts_df  = pd.DataFrame([
        {
            "Invoice Type": labels[k],
            "Amount":       fmt(row[k], currency),
            "Row %":        fmt_pct(row[k] / total) if total else "—",
            "_sort":        row[k],
        }
        for k in labels if pd.notnull(row[k])
    ]).sort_values("_sort", ascending=False).drop(columns="_sort")

    grand  = pd.DataFrame([{
        "Invoice Type": "Grand Total",
        "Amount": fmt(total, currency),
        "Row %": "100.0%",
    }])
    ts_df  = pd.concat([ts_df, grand], ignore_index=True)

    view = st.radio("", ["Table", "Chart"], horizontal=True,
                    key="type_split_view", label_visibility="collapsed")
    if view == "Table":
        st.dataframe(ts_df, width='stretch', hide_index=True)
    else:
        bar_df = pd.DataFrame([
            {"Type": labels[k], "Amount": float(row[k])}
            for k in labels if k != "tax_amount" and pd.notnull(row[k])
        ]).sort_values("Amount", ascending=True)
        render_bar_chart(bar_df, "Type", "Amount",
                         f"Revenue Type Split — {selected_fy}",
                         currency, horizontal=True, height=300)

st.divider()

# ─────────────────────────────────────────────
# SECTION 4 — BILLING BY ENTITY
# ─────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def load_by_entity(fy_filter, rate, dim_key):
    return run_query(f"""
        SELECT
            subsidiary_name,
            SUM(billing_amount * {rate}) AS amount
        FROM billing
        {build_where(fy_filter)}
        GROUP BY subsidiary_name
        ORDER BY amount DESC
    """)

with st.spinner("Loading entity split…"):
    ent = load_by_entity(selected_fy, rate_col, dim_cache_key)

st.subheader("YTD Billing — Billing Entity Split")
if not ent.empty:
    total_ent = ent["amount"].sum()
    ent_disp  = ent.copy()
    ent_disp["row_pct"] = ent_disp["amount"] / total_ent if total_ent else 0
    grand_ent = pd.DataFrame([{"subsidiary_name": "Grand Total",
                                "amount": total_ent, "row_pct": 1.0}])
    ent_disp  = pd.concat([ent_disp, grand_ent], ignore_index=True)
    ent_disp["amount"]  = ent_disp["amount"].apply(lambda x: fmt(x, currency))
    ent_disp["row_pct"] = ent_disp["row_pct"].apply(fmt_pct)
    ent_disp.columns    = ["Billing Entity", "Amount", "Row %"]

    view = st.radio("", ["Table", "Chart"], horizontal=True,
                    key="entity_view", label_visibility="collapsed")
    if view == "Table":
        st.dataframe(ent_disp, width='stretch', hide_index=True)
    else:
        render_bar_chart(ent, "subsidiary_name", "amount",
                         f"Billing by Entity — {selected_fy}",
                         currency, horizontal=False, height=300)

st.divider()

# ─────────────────────────────────────────────
# SECTION 5 — BILLING BY REGION
# ─────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def load_by_region(fy_filter, rate, dim_key):
    return run_query(f"""
        SELECT
            region,
            SUM(billing_amount * {rate}) AS amount
        FROM billing
        {build_where(fy_filter)}
        GROUP BY region
        ORDER BY amount DESC
    """)

with st.spinner("Loading region split…"):
    reg = load_by_region(selected_fy, rate_col, dim_cache_key)

st.subheader("YTD Billing — Region Split")
if not reg.empty:
    total_reg = reg["amount"].sum()
    reg_disp  = reg.copy()
    reg_disp["row_pct"] = reg_disp["amount"] / total_reg if total_reg else 0
    grand_reg = pd.DataFrame([{"region": "Grand Total",
                                "amount": total_reg, "row_pct": 1.0}])
    reg_disp  = pd.concat([reg_disp, grand_reg], ignore_index=True)
    reg_disp["amount"]  = reg_disp["amount"].apply(lambda x: fmt(x, currency))
    reg_disp["row_pct"] = reg_disp["row_pct"].apply(fmt_pct)
    reg_disp.columns    = ["Region", "Amount", "Row %"]

    view = st.radio("", ["Table", "Chart"], horizontal=True,
                    key="region_view", label_visibility="collapsed")
    if view == "Table":
        st.dataframe(reg_disp, width='stretch', hide_index=True)
    else:
        render_bar_chart(reg, "region", "amount",
                         f"Billing by Region — {selected_fy}",
                         currency, horizontal=False, height=300)

st.divider()


# ─────────────────────────────────────────────
# SECTION 4 — BILLING ENTITY × TYPE SPLIT (PIVOT)
# ─────────────────────────────────────────────

st.subheader("Billing Entity × Invoice Type Split")

@st.cache_data(ttl=300, show_spinner=False)
def load_entity_type_pivot(fy_filter, rate, dim_key):
    return run_query(f"""
        SELECT
            subsidiary_name,
            SUM(billing_amount * {rate})                                                        AS total,
            SUM(subscriptionfee    * {rate})                                                    AS subscription,
            SUM(implementationfee  * {rate})                                                    AS implementation,
            SUM(integrationfee     * {rate})                                                    AS integration,
            SUM(studiofee          * {rate})                                                    AS studio,
            SUM((COALESCE(amsfee,0)+COALESCE(otherservicesfee,0)+COALESCE(openingsplitfee,0))*{rate}) AS other_services,
            SUM(COALESCE(transaction_tax,0) * {rate})                                           AS tax_amount
        FROM billing
        {build_where(fy_filter)}
        GROUP BY subsidiary_name
        ORDER BY total DESC
    """)

with st.spinner("Loading entity × type pivot…"):
    etp = load_entity_type_pivot(selected_fy, rate_col, dim_cache_key)

if not etp.empty:
    metric_cols = ["subscription","implementation","integration",
                   "studio","other_services","tax_amount","total"]
    total_row   = {c: etp[c].sum() for c in metric_cols}
    total_row["subsidiary_name"] = "Grand Total"
    etp = pd.concat([etp, pd.DataFrame([total_row])], ignore_index=True)

    grand_total = total_row["total"]
    etp_disp    = etp.copy()
    etp_disp["row_pct"] = etp_disp["total"] / grand_total if grand_total else 0

    col_rename = {
        "subsidiary_name": "Subsidiary",
        "row_pct":         "% of Total",
        "subscription":    "Subscription",
        "implementation":  "Implementation",
        "integration":     "Integration",
        "studio":          "Studio",
        "other_services":  "Other Services",
        "tax_amount":      "Tax",
        "total":           "Total",
    }
    for col in metric_cols:
        etp_disp[col] = etp_disp[col].apply(lambda x: fmt(x, currency))
    etp_disp["row_pct"] = etp_disp["row_pct"].apply(fmt_pct)
    etp_disp = etp_disp.rename(columns=col_rename)
    # Reorder so % of Total is after Total
    cols = [c for c in etp_disp.columns if c not in ["% of Total"]] + ["% of Total"]
    etp_disp = etp_disp[cols]
    st.dataframe(etp_disp, width='stretch', hide_index=True)

st.divider()


# ─────────────────────────────────────────────
# SECTION 5 — QoQ × INVOICE TYPE SPLIT (PIVOT)
# ─────────────────────────────────────────────

st.subheader("QoQ × Invoice Type Split")

@st.cache_data(ttl=300, show_spinner=False)
def load_qoq_type_pivot(fy_filter, rate, dim_key):
    return run_query(f"""
        SELECT
            transaction_fy_quarter AS quarter,
            SUM(billing_amount * {rate})                                                        AS total,
            SUM(subscriptionfee    * {rate})                                                    AS subscription,
            SUM(implementationfee  * {rate})                                                    AS implementation,
            SUM(integrationfee     * {rate})                                                    AS integration,
            SUM(studiofee          * {rate})                                                    AS studio,
            SUM((COALESCE(amsfee,0)+COALESCE(otherservicesfee,0)+COALESCE(openingsplitfee,0))*{rate}) AS other_services,
            SUM(COALESCE(transaction_tax,0) * {rate})                                           AS tax_amount
        FROM billing
        {build_where(fy_filter)}
        GROUP BY quarter
        ORDER BY quarter
    """)

with st.spinner("Loading QoQ type pivot…"):
    qtp = load_qoq_type_pivot(selected_fy, rate_col, dim_cache_key)

if not qtp.empty:
    metric_cols = ["subscription","implementation","integration",
                   "studio","other_services","tax_amount","total"]
    total_row   = {c: qtp[c].sum() for c in metric_cols}
    total_row["quarter"] = "Grand Total"
    qtp = pd.concat([qtp, pd.DataFrame([total_row])], ignore_index=True)

    grand_total = total_row["total"]
    qtp_disp    = qtp.copy()
    qtp_disp["row_pct"] = qtp_disp["total"] / grand_total if grand_total else 0

    col_rename = {
        "quarter":        "Quarter",
        "row_pct":        "% of Total",
        "subscription":   "Subscription",
        "implementation": "Implementation",
        "integration":    "Integration",
        "studio":         "Studio",
        "other_services": "Other Services",
        "tax_amount":     "Tax",
        "total":          "Total",
    }
    for col in metric_cols:
        qtp_disp[col] = qtp_disp[col].apply(lambda x: fmt(x, currency))
    qtp_disp["row_pct"] = qtp_disp["row_pct"].apply(fmt_pct)
    qtp_disp = qtp_disp.rename(columns=col_rename)
    cols = [c for c in qtp_disp.columns if c not in ["% of Total"]] + ["% of Total"]
    qtp_disp = qtp_disp[cols]
    st.dataframe(qtp_disp, width='stretch', hide_index=True)

st.divider()


# ─────────────────────────────────────────────
# SECTION 6 — REGION × TYPE SPLIT (PIVOT)
# ─────────────────────────────────────────────

st.subheader("Region × Invoice Type Split")

@st.cache_data(ttl=300, show_spinner=False)
def load_region_type_pivot(fy_filter, rate, dim_key):
    return run_query(f"""
        SELECT
            region,
            SUM(billing_amount * {rate})                                                        AS total,
            SUM(subscriptionfee    * {rate})                                                    AS subscription,
            SUM(implementationfee  * {rate})                                                    AS implementation,
            SUM(integrationfee     * {rate})                                                    AS integration,
            SUM(studiofee          * {rate})                                                    AS studio,
            SUM((COALESCE(amsfee,0)+COALESCE(otherservicesfee,0)+COALESCE(openingsplitfee,0))*{rate}) AS other_services,
            SUM(COALESCE(transaction_tax,0) * {rate})                                           AS tax_amount
        FROM billing
        {build_where(fy_filter)}
        GROUP BY region
        ORDER BY total DESC
    """)

with st.spinner("Loading region type pivot…"):
    rtp = load_region_type_pivot(selected_fy, rate_col, dim_cache_key)

if not rtp.empty:
    metric_cols = ["subscription","implementation","integration",
                   "studio","other_services","tax_amount","total"]
    total_row   = {c: rtp[c].sum() for c in metric_cols}
    total_row["region"] = "Grand Total"
    rtp = pd.concat([rtp, pd.DataFrame([total_row])], ignore_index=True)

    grand_total = total_row["total"]
    rtp_disp    = rtp.copy()
    rtp_disp["row_pct"] = rtp_disp["total"] / grand_total if grand_total else 0

    col_rename = {
        "region":         "Region",
        "row_pct":        "% of Total",
        "subscription":   "Subscription",
        "implementation": "Implementation",
        "integration":    "Integration",
        "studio":         "Studio",
        "other_services": "Other Services",
        "tax_amount":     "Tax",
        "total":          "Total",
    }
    for col in metric_cols:
        rtp_disp[col] = rtp_disp[col].apply(lambda x: fmt(x, currency))
    rtp_disp["row_pct"] = rtp_disp["row_pct"].apply(fmt_pct)
    rtp_disp = rtp_disp.rename(columns=col_rename)
    cols = [c for c in rtp_disp.columns if c not in ["% of Total"]] + ["% of Total"]
    rtp_disp = rtp_disp[cols]
    st.dataframe(rtp_disp, width='stretch', hide_index=True)

st.divider()


# ─────────────────────────────────────────────
# SECTION 7 — BILLING CURRENCY MIX (PIVOT)
# ─────────────────────────────────────────────

st.subheader("Billing Currency Mix")

@st.cache_data(ttl=300, show_spinner=False)
def load_currency_mix(fy_filter, rate, dim_key):
    quarters_df = run_query(f"""
        SELECT DISTINCT transaction_fy_quarter
        FROM billing
        {build_where(fy_filter)}
        ORDER BY transaction_fy_quarter
    """)
    quarters = quarters_df["transaction_fy_quarter"].tolist()

    cases = ",\n".join([
        f"SUM(CASE WHEN transaction_fy_quarter = '{q}' "
        f"THEN billing_amount * {rate} ELSE 0 END) AS \"{q}\""
        for q in quarters
    ])

    return run_query(f"""
        SELECT
            currency_symbol,
            SUM(billing_amount * {rate}) AS total,
            {cases}
        FROM billing
        {build_where(fy_filter)}
        GROUP BY currency_symbol
        ORDER BY total DESC
    """), quarters

with st.spinner("Loading currency mix…"):
    cm, quarters = load_currency_mix(selected_fy, rate_col, dim_cache_key)

if not cm.empty:
    grand_total  = cm["total"].sum()
    cm_disp      = cm.copy()
    cm_disp["row_pct"] = cm_disp["total"] / grand_total if grand_total else 0

    # Grand Total row
    grand_row = {"currency_symbol": "Grand Total",
                 "row_pct": 1.0,
                 "total": grand_total}
    for q in quarters:
        grand_row[q] = cm_disp[q].sum() if q in cm_disp.columns else 0
    cm_disp = pd.concat([cm_disp, pd.DataFrame([grand_row])], ignore_index=True)

    for col in quarters + ["total"]:
        if col in cm_disp.columns:
            cm_disp[col] = cm_disp[col].apply(lambda x: fmt(x, currency))
    cm_disp["row_pct"] = cm_disp["row_pct"].apply(fmt_pct)
    cm_disp = cm_disp.rename(columns={"currency_symbol": "Currency",
                                       "row_pct": "% of Total", "total": "Total"})
    st.dataframe(cm_disp, width='stretch', hide_index=True)

st.divider()


# ─────────────────────────────────────────────
# SECTION 8 — TOP 20 CUSTOMERS
# ─────────────────────────────────────────────

st.subheader("Top 20 Billed Customers")

@st.cache_data(ttl=300, show_spinner=False)
def load_top_customers(fy_filter, rate, dim_key):
    return run_query(f"""
        SELECT
            customer_name,
            SUM(billing_amount * {rate}) AS amount
        FROM billing
        {build_where(fy_filter)}
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
        cust_disp  = cust.copy()
        cust_disp["row_pct"] = cust_disp["amount"] / total_cust if total_cust else 0
        cust_disp["amount"]  = cust_disp["amount"].apply(lambda x: fmt(x, currency))
        cust_disp["row_pct"] = cust_disp["row_pct"].apply(fmt_pct)
        cust_disp.columns    = ["Customer", "Amount", "Row %"]
        st.dataframe(cust_disp, width='stretch', hide_index=True)

    with tab_c:
        render_bar_chart(cust, "customer_name", "amount",
                         f"Top 20 Customers — {selected_fy}",
                         currency, horizontal=True,
                         height=max(400, len(cust) * 28))

st.divider()


# ─────────────────────────────────────────────
# SECTION 9 — INTERCOMPANY BILLING
# ─────────────────────────────────────────────

st.subheader("Intercompany Billing")

@st.cache_data(ttl=300, show_spinner=False)
def load_intercompany_pivot(fy_filter, rate, dim_key):
    return run_query(f"""
        SELECT
            subsidiary_name,
            TRIM(paying_entity) AS paying_entity,
            SUM(billing_amount * {rate}) AS amount
        FROM billing
        {build_where(fy_filter, include_ic=True)}
        GROUP BY subsidiary_name, TRIM(paying_entity)
    """)

with st.spinner("Loading intercompany pivot…"):
    ic = load_intercompany_pivot(selected_fy, rate_col, dim_cache_key)

if not ic.empty:
    pivot = ic.pivot_table(
        index="subsidiary_name", columns="paying_entity",
        values="amount", aggfunc="sum", fill_value=0
    ).reset_index()

    paying_cols = [c for c in pivot.columns if c != "subsidiary_name"]
    pivot["Total"] = pivot[paying_cols].sum(axis=1)
    grand = {"subsidiary_name": "Grand Total"}
    for c in paying_cols + ["Total"]:
        grand[c] = pivot[c].sum()
    pivot = pd.concat([pivot, pd.DataFrame([grand])], ignore_index=True)

    pivot_disp = pivot.copy()
    for c in paying_cols + ["Total"]:
        pivot_disp[c] = pivot_disp[c].apply(lambda x: fmt(x, currency))
    pivot_disp = pivot_disp.rename(columns={"subsidiary_name": "Billing Entity ↓ / Paying Entity →"})
    st.dataframe(pivot_disp, width='stretch', hide_index=True)
else:
    st.info("No intercompany billing data for this period.")