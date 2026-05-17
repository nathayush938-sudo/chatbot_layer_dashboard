"""
dashboard_ar_analysis.py  (place in pages/ as  4_📈_AR_Analysis.py)
AR Analysis dashboard — real-time snapshot, no FY filter, no Claude API calls.
"""

import streamlit as st
import pandas as pd
from datetime import date
from dashboard_utils import (
    run_query, get_fy_info, fmt, fmt_pct,
    render_kpi_card, render_bar_chart,
)

st.set_page_config(page_title="AR Analysis", layout="wide")

AR_AGEING_ORDER = ["Current", "1-30 days", "31-60 days",
                   "61-90 days", "91-180 days", ">180 days"]

# ─────────────────────────────────────────────
# FILTER OPTIONS
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_filter_options():
    def vals(col, include_unassigned=False):
        cond = f"WHERE {col} IS NOT NULL" if include_unassigned \
               else f"WHERE {col} IS NOT NULL AND {col} != 'Unassigned'"
        df = run_query(
            f"SELECT DISTINCT {col} FROM ar {cond} ORDER BY {col}"
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
    sel_currency = st.multiselect(
        "Transaction Currency", opts["currency_symbol"], placeholder="All currencies"
    )

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


def build_where(include_ic=False):
    """AR is a real-time snapshot — no FY filter."""
    ic = "'T'" if include_ic else "'F'"
    clauses = [f"inter_company_status = {ic}"]
    _add_dim_clauses(clauses)
    return "WHERE " + "\n  AND ".join(clauses)


dim_cache_key = (
    currency,
    tuple(sel_region), tuple(sel_entity), tuple(sel_cjs),
    tuple(sel_bucket), tuple(sel_status), tuple(sel_currency)
)

# ─────────────────────────────────────────────
# PAGE HEADER
# ─────────────────────────────────────────────

st.title("📈 AR Analysis")
st.caption(f"Real-time snapshot · As of {date.today().strftime('%d %b %Y')} · "
           f"External customers only · {currency}")
st.divider()

# ─────────────────────────────────────────────
# SECTION 1 — TOP KPIs
# ─────────────────────────────────────────────

st.subheader("Key Metrics")

@st.cache_data(ttl=300, show_spinner=False)
def load_top_kpis(rate, dim_key):
    return run_query(f"""
        SELECT
            SUM(open_amount * {rate})                                                   AS outstanding,
            SUM(CASE WHEN open_days >= 1 THEN open_amount * {rate} ELSE 0 END)         AS overdue,
            SUM(CASE WHEN open_days < 1  THEN open_amount * {rate} ELSE 0 END)         AS current_amt,
            ROUND(
                SUM(CASE WHEN open_days >= 1 THEN open_amount * {rate} ELSE 0 END) /
                NULLIF(SUM(open_amount * {rate}), 0) * 100, 1
            )                                                                           AS overdue_pct
        FROM ar
        {build_where()}
    """).iloc[0]

with st.spinner("Loading KPIs…"):
    kpi = load_top_kpis(rate_col, dim_cache_key)

c1, c2, c3, c4 = st.columns(4)
with c1:
    render_kpi_card("Total Outstanding", kpi["outstanding"], currency=currency,
                    vs_label="")
with c2:
    render_kpi_card("Total Overdue", kpi["overdue"], currency=currency,
                    vs_label="")
with c3:
    render_kpi_card("Current (Not Due)", kpi["current_amt"], currency=currency,
                    vs_label="")
with c4:
    # Show overdue % as a special KPI
    pct = float(kpi["overdue_pct"] or 0)
    st.markdown(f"""
    <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;
                padding:16px 20px;height:100%;">
        <div style="font-size:12px;color:#6b7280;font-weight:500;
                    text-transform:uppercase;letter-spacing:0.05em;
                    margin-bottom:6px;">Overdue %</div>
        <div style="font-size:26px;font-weight:700;color:#111827;
                    margin-bottom:4px;">{pct:.1f}%</div>
        <div style="font-size:13px;color:#9ca3af;">of total outstanding</div>
    </div>
    """, unsafe_allow_html=True)

st.divider()

# ─────────────────────────────────────────────
# SECTION 2 — CLIENT BUCKET BREAKDOWN
# ─────────────────────────────────────────────

st.subheader("Client Bucket Breakdown")

@st.cache_data(ttl=300, show_spinner=False)
def load_bucket_kpis(rate, dim_key):
    return run_query(f"""
        SELECT
            client_buckets,
            SUM(open_amount * {rate})                                           AS outstanding,
            SUM(CASE WHEN open_days >= 1 THEN open_amount * {rate} ELSE 0 END) AS overdue
        FROM ar
        {build_where()}
        GROUP BY client_buckets
        ORDER BY outstanding DESC
    """)

with st.spinner("Loading bucket breakdown…"):
    bkt = load_bucket_kpis(rate_col, dim_cache_key)

if not bkt.empty:
    total_out = float(kpi["outstanding"] or 1)
    cols_bkt  = st.columns(len(bkt))
    for i, (_, row) in enumerate(bkt.iterrows()):
        label = row["client_buckets"] or "Unassigned"
        pct   = float(row["outstanding"] or 0) / total_out if total_out else 0
        with cols_bkt[i]:
            st.markdown(f"""
            <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;
                        padding:16px 20px;text-align:center;">
                <div style="font-size:12px;color:#6b7280;font-weight:500;
                            text-transform:uppercase;letter-spacing:0.05em;
                            margin-bottom:6px;">Outstanding — {label}</div>
                <div style="font-size:22px;font-weight:700;color:#111827;
                            margin-bottom:4px;">{fmt(row['outstanding'], currency)}</div>
                <div style="font-size:13px;color:#6b7280;">
                    {fmt_pct(pct)} of total
                </div>
                <div style="font-size:12px;color:#ef4444;margin-top:4px;">
                    Overdue: {fmt(row['overdue'], currency)}
                </div>
            </div>
            """, unsafe_allow_html=True)

st.divider()

# ─────────────────────────────────────────────
# SECTION 3 — CUSTOMER JOURNEY BREAKDOWN
# ─────────────────────────────────────────────

st.subheader("Customer Journey Stage Breakdown")

@st.cache_data(ttl=300, show_spinner=False)
def load_cjs_kpis(rate, dim_key):
    return run_query(f"""
        SELECT
            client_journey_stage,
            SUM(open_amount * {rate})                                           AS outstanding,
            SUM(CASE WHEN open_days >= 1 THEN open_amount * {rate} ELSE 0 END) AS overdue
        FROM ar
        {build_where()}
        GROUP BY client_journey_stage
        ORDER BY outstanding DESC
    """)

with st.spinner("Loading CJS breakdown…"):
    cjs = load_cjs_kpis(rate_col, dim_cache_key)

if not cjs.empty:
    cols_cjs = st.columns(min(len(cjs), 4))
    for i, (_, row) in enumerate(cjs.iterrows()):
        if i >= 4: break
        label = row["client_journey_stage"] or "Unassigned"
        pct   = float(row["outstanding"] or 0) / total_out if total_out else 0
        with cols_cjs[i]:
            st.markdown(f"""
            <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;
                        padding:16px 20px;text-align:center;">
                <div style="font-size:12px;color:#6b7280;font-weight:500;
                            text-transform:uppercase;letter-spacing:0.05em;
                            margin-bottom:6px;">Outstanding — {label}</div>
                <div style="font-size:22px;font-weight:700;color:#111827;
                            margin-bottom:4px;">{fmt(row['outstanding'], currency)}</div>
                <div style="font-size:13px;color:#6b7280;">
                    {fmt_pct(pct)} of total
                </div>
                <div style="font-size:12px;color:#ef4444;margin-top:4px;">
                    Overdue: {fmt(row['overdue'], currency)}
                </div>
            </div>
            """, unsafe_allow_html=True)

    # Show remaining stages if more than 4
    if len(cjs) > 4:
        st.markdown("")
        cols_cjs2 = st.columns(len(cjs) - 4)
        for i, (_, row) in enumerate(cjs.iloc[4:].iterrows()):
            label = row["client_journey_stage"] or "Unassigned"
            pct   = float(row["outstanding"] or 0) / total_out if total_out else 0
            with cols_cjs2[i]:
                st.markdown(f"""
                <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;
                            padding:16px 20px;text-align:center;">
                    <div style="font-size:12px;color:#6b7280;font-weight:500;
                                text-transform:uppercase;letter-spacing:0.05em;
                                margin-bottom:6px;">Outstanding — {label}</div>
                    <div style="font-size:22px;font-weight:700;color:#111827;
                                margin-bottom:4px;">{fmt(row['outstanding'], currency)}</div>
                    <div style="font-size:13px;color:#6b7280;">{fmt_pct(pct)} of total</div>
                    <div style="font-size:12px;color:#ef4444;margin-top:4px;">
                        Overdue: {fmt(row['overdue'], currency)}
                    </div>
                </div>
                """, unsafe_allow_html=True)

st.divider()

# ─────────────────────────────────────────────
# SECTION 4 — AR BY REGION + BY SUBSIDIARY
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# SECTION 4 — AR BY REGION
# ─────────────────────────────────────────────

st.subheader("AR by Region")

@st.cache_data(ttl=300, show_spinner=False)
def load_by_region(rate, dim_key):
    return run_query(f"""
        SELECT
            region,
            SUM(open_amount * {rate})                                           AS outstanding,
            SUM(CASE WHEN open_days >= 1 THEN open_amount * {rate} ELSE 0 END) AS overdue
        FROM ar
        {build_where()}
        GROUP BY region
        ORDER BY outstanding DESC
    """)

with st.spinner("Loading region…"):
    reg = load_by_region(rate_col, dim_cache_key)

if not reg.empty:
    view = st.radio("", ["Table", "Chart"], horizontal=True,
                    key="region_view", label_visibility="collapsed")
    if view == "Table":
        total_r = reg["outstanding"].sum()
        reg_d   = reg.copy()
        reg_d["outstanding_pct"] = (reg_d["outstanding"] / total_r).apply(fmt_pct)
        reg_d["outstanding"]     = reg_d["outstanding"].apply(lambda x: fmt(x, currency))
        reg_d["overdue"]         = reg_d["overdue"].apply(lambda x: fmt(x, currency))
        reg_d.columns            = ["Region", "Outstanding", "Outstanding %", "Overdue"]
        st.dataframe(reg_d, width='stretch', hide_index=True)
    else:
        render_bar_chart(reg, "region", "outstanding",
                         "AR by Region", currency, height=350)

st.divider()

# ─────────────────────────────────────────────
# SECTION 5 — AR BY BILLING ENTITY
# ─────────────────────────────────────────────

st.subheader("AR by Billing Entity")

@st.cache_data(ttl=300, show_spinner=False)
def load_by_entity(rate, dim_key):
    return run_query(f"""
        SELECT
            subsidiary_name,
            SUM(open_amount * {rate})                                           AS outstanding,
            SUM(CASE WHEN open_days >= 1 THEN open_amount * {rate} ELSE 0 END) AS overdue
        FROM ar
        {build_where()}
        GROUP BY subsidiary_name
        ORDER BY outstanding DESC
    """)

with st.spinner("Loading entity…"):
    ent = load_by_entity(rate_col, dim_cache_key)

if not ent.empty:
    view = st.radio("", ["Table", "Chart"], horizontal=True,
                    key="entity_view", label_visibility="collapsed")
    if view == "Table":
        total_e = ent["outstanding"].sum()
        ent_d   = ent.copy()
        ent_d["outstanding_pct"] = (ent_d["outstanding"] / total_e).apply(fmt_pct)
        ent_d["outstanding"]     = ent_d["outstanding"].apply(lambda x: fmt(x, currency))
        ent_d["overdue"]         = ent_d["overdue"].apply(lambda x: fmt(x, currency))
        ent_d.columns            = ["Billing Entity", "Outstanding", "Outstanding %", "Overdue"]
        st.dataframe(ent_d, width='stretch', hide_index=True)
    else:
        render_bar_chart(ent, "subsidiary_name", "outstanding",
                         "AR by Billing Entity", currency, height=320)

st.divider()

# ─────────────────────────────────────────────
# SECTION 5 — AGEING BUCKET BREAKDOWN
# ─────────────────────────────────────────────

st.subheader("AR by Ageing Bucket")

@st.cache_data(ttl=300, show_spinner=False)
def load_ageing(rate, dim_key):
    return run_query(f"""
        SELECT
            CASE
                WHEN open_days < 1               THEN 'Current'
                WHEN open_days BETWEEN 1  AND 30  THEN '1-30 days'
                WHEN open_days BETWEEN 31 AND 60  THEN '31-60 days'
                WHEN open_days BETWEEN 61 AND 90  THEN '61-90 days'
                WHEN open_days BETWEEN 91 AND 180 THEN '91-180 days'
                ELSE '>180 days'
            END AS ageing_bucket,
            SUM(open_amount * {rate}) AS outstanding
        FROM ar
        {build_where()}
        GROUP BY ageing_bucket
    """)

with st.spinner("Loading ageing…"):
    age = load_ageing(rate_col, dim_cache_key)

if not age.empty:
    # Sort by defined order
    age["_sort"] = age["ageing_bucket"].map(
        {b: i for i, b in enumerate(AR_AGEING_ORDER)}
    ).fillna(99)
    age = age.sort_values("_sort").drop(columns="_sort")

    view = st.radio("", ["Table", "Chart"], horizontal=True,
                    key="ageing_view", label_visibility="collapsed")
    if view == "Table":
        total_a = age["outstanding"].sum()
        grand   = pd.DataFrame([{"ageing_bucket": "Grand Total",
                                  "outstanding": total_a}])
        age_d   = pd.concat([age, grand], ignore_index=True)
        age_d["pct"]         = (age_d["outstanding"] / total_a).apply(fmt_pct)
        age_d["outstanding"] = age_d["outstanding"].apply(lambda x: fmt(x, currency))
        age_d.columns        = ["Ageing Bucket", "Outstanding", "% of Total"]
        st.dataframe(age_d, width='stretch', hide_index=True)
    else:
        render_bar_chart(age, "ageing_bucket", "outstanding",
                         "AR by Ageing Bucket", currency, height=350)

st.divider()

# ─────────────────────────────────────────────
# SECTION 6 — TOP 20 OUTSTANDING
# ─────────────────────────────────────────────

st.subheader("Top 20 Outstanding Customers")

@st.cache_data(ttl=300, show_spinner=False)
def load_top_outstanding(rate, dim_key):
    return run_query(f"""
        SELECT
            customer_ucc                        AS entity_id,
            customer_name                       AS company_name,
            SUM(open_amount * {rate})           AS outstanding,
            SUM(CASE WHEN open_days >= 1
                     THEN open_amount * {rate}
                     ELSE 0 END)               AS overdue
        FROM ar
        {build_where()}
          AND customer_name IS NOT NULL
        GROUP BY customer_ucc, customer_name
        ORDER BY outstanding DESC
        LIMIT 20
    """)

with st.spinner("Loading top outstanding…"):
    top_out = load_top_outstanding(rate_col, dim_cache_key)

if not top_out.empty:
    tab_t, tab_c = st.tabs(["Table", "Chart"])
    with tab_t:
        top_d = top_out.copy()
        top_d["outstanding"] = top_d["outstanding"].apply(lambda x: fmt(x, currency))
        top_d["overdue"]     = top_d["overdue"].apply(lambda x: fmt(x, currency))
        top_d.columns        = ["Entity ID", "Company Name", "Outstanding", "Overdue"]
        st.dataframe(top_d, width='stretch', hide_index=True)
    with tab_c:
        render_bar_chart(top_out, "company_name", "outstanding",
                         "Top 20 Outstanding", currency,
                         horizontal=True, height=max(400, len(top_out) * 28))

st.divider()

# ─────────────────────────────────────────────
# SECTION 7 — TOP 20 OVERDUE
# ─────────────────────────────────────────────

st.subheader("Top 20 Overdue Customers")

@st.cache_data(ttl=300, show_spinner=False)
def load_top_overdue(rate, dim_key):
    return run_query(f"""
        SELECT
            customer_ucc                                                        AS entity_id,
            customer_name                                                       AS company_name,
            SUM(CASE WHEN open_days < 1  THEN open_amount * {rate} ELSE 0 END) AS current_amt,
            SUM(CASE WHEN open_days >= 1 THEN open_amount * {rate} ELSE 0 END) AS overdue,
            SUM(open_amount * {rate})                                           AS outstanding
        FROM ar
        {build_where()}
          AND customer_name IS NOT NULL
          AND open_days >= 1
        GROUP BY customer_ucc, customer_name
        ORDER BY overdue DESC
        LIMIT 20
    """)

with st.spinner("Loading top overdue…"):
    top_ov = load_top_overdue(rate_col, dim_cache_key)

if not top_ov.empty:
    tab_t2, tab_c2 = st.tabs(["Table", "Chart"])
    with tab_t2:
        top_ov_d = top_ov.copy()
        for col in ["current_amt", "overdue", "outstanding"]:
            top_ov_d[col] = top_ov_d[col].apply(lambda x: fmt(x, currency))
        top_ov_d.columns = ["Entity ID", "Company Name",
                            "Current", "Overdue", "Total Outstanding"]
        st.dataframe(top_ov_d, width='stretch', hide_index=True)
    with tab_c2:
        render_bar_chart(top_ov, "company_name", "overdue",
                         "Top 20 Overdue", currency,
                         horizontal=True, height=max(400, len(top_ov) * 28))