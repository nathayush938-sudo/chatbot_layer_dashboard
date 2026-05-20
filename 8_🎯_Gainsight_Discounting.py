"""
gainsight_discounting.py  (place in pages/ as  9_🎯_Gainsight_Discounting.py)
Gainsight Discounting Dashboard — CTA-level discount tracking.
All amounts are pre-converted to USD in the gs materialized view.
No Claude API calls — pure SQL → DataFrame → Streamlit.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from dashboard_utils import run_query, get_fy_info, fmt, fmt_pct, render_kpi_card

st.set_page_config(page_title="Gainsight Discounting", layout="wide")

# ─────────────────────────────────────────────
# FY CONTEXT
# ─────────────────────────────────────────────

fy      = get_fy_info()
CUR_FY  = fy["current_fy"]
PREV_FY = fy["previous_fy"]


def fy_date_range(fy_label: str):
    """Return (start_inclusive, end_exclusive) date strings for an Indian FY.
    FY26 → ('2025-04-01', '2026-04-01')
    """
    end_year = 2000 + int(fy_label[2:])
    return f"{end_year - 1}-04-01", f"{end_year}-04-01"


# ─────────────────────────────────────────────
# FILTER OPTIONS
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_filter_options():
    def vals(col, include_unassigned=True):
        cond = (f"WHERE {col} IS NOT NULL"
                if include_unassigned
                else f"WHERE {col} IS NOT NULL AND {col} != 'Unassigned'")
        return run_query(
            f"SELECT DISTINCT {col} FROM gs {cond} ORDER BY {col}"
        ).iloc[:, 0].tolist()

    return {
        "region":               vals("region",               include_unassigned=True),
        "client_journey_stage": vals("client_journey_stage", include_unassigned=True),
        "client_buckets":       vals("client_buckets",       include_unassigned=True),
        "collection_status":    vals("collection_status",    include_unassigned=True),
        "discount_type":        vals("type_of_discount_gc",  include_unassigned=True),
        "owner_name":           vals("owner_name",           include_unassigned=True),
    }

with st.spinner("Loading filters…"):
    opts = load_filter_options()


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────

with st.sidebar:
    st.header("Filters")

    raw_values = st.toggle("Show raw values", value=False)

    st.divider()
    if st.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ─────────────────────────────────────────────
# WHERE CLAUSE BUILDER
# gs amounts are pre-converted to USD — no exchange rate needed.
# FY filter uses created_date.
# ─────────────────────────────────────────────

def _add_dim_clauses(clauses: list):
    def in_clause(col, selections):
        if selections:
            v = ", ".join(f"'{s}'" for s in selections)
            clauses.append(f"{col} IN ({v})")
    in_clause("region",               sel_region)
    in_clause("client_journey_stage", sel_cjs)
    in_clause("client_buckets",       sel_bucket)
    in_clause("collection_status",    sel_status)
    in_clause("type_of_discount_gc",  sel_dtype)
    in_clause("owner_name",           sel_owner)


def build_where(fy_label: str = None) -> str:
    clauses = []
    if fy_label and fy_label != "All":
        start, end = fy_date_range(fy_label)
        clauses.append(f"created_date >= '{start}' AND created_date < '{end}'")
    _add_dim_clauses(clauses)
    return ("WHERE " + "\n  AND ".join(clauses)) if clauses else ""


# Convenience: USD symbol — all gs amounts are in USD
CURRENCY = "USD"


# ─────────────────────────────────────────────
# PAGE HEADER + DIMENSION FILTERS
# ─────────────────────────────────────────────

selected_fy = st.session_state.get("gs_fy", "All")
_caption = "All time · All amounts in USD" if selected_fy == "All" else f"CTA created between {fy_date_range(selected_fy)[0]} and {fy_date_range(selected_fy)[1][:7]} · All amounts in USD"

st.title(f"🎯 Gainsight Discounting — {selected_fy}")
st.caption(_caption)
st.divider()

with st.expander("🔽 Filters", expanded=True):
    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    r2c1, r2c2, r2c3 = st.columns(3)
    with r1c1:
        selected_fy = st.selectbox("Financial Year", options=["All", CUR_FY, PREV_FY, fy["two_years_ago_fy"]], index=0, key="gs_fy", help="Filters by CTA created_date")
    with r1c2:
        sel_region  = st.multiselect("Region",               opts["region"],               placeholder="All regions")
    with r1c3:
        sel_cjs     = st.multiselect("Client Journey Stage", opts["client_journey_stage"], placeholder="All stages")
    with r1c4:
        sel_bucket  = st.multiselect("Client Bucket",        opts["client_buckets"],       placeholder="All buckets")
    with r2c1:
        sel_status  = st.multiselect("Collection Status",    opts["collection_status"],    placeholder="All statuses")
    with r2c2:
        sel_dtype   = st.multiselect("Discount Type",        opts["discount_type"],        placeholder="All types")
    with r2c3:
        sel_owner   = st.multiselect("Owner",                opts["owner_name"],           placeholder="All owners")

dim_cache_key = (
    selected_fy,
    tuple(sel_region), tuple(sel_cjs), tuple(sel_bucket),
    tuple(sel_status), tuple(sel_dtype), tuple(sel_owner),
)



# ─────────────────────────────────────────────
# SECTION 1 — KPI CARDS
# ─────────────────────────────────────────────

st.subheader("KPIs")

@st.cache_data(ttl=300, show_spinner=False)
def load_kpis(dim_key):
    where = build_where(selected_fy)
    return run_query(f"""
        SELECT
            SUM(requested_discount)                                             AS total_requested,
            SUM(CASE WHEN cta_type = 'Approved' THEN approved_discount  END)   AS total_approved,
            SUM(CASE WHEN cta_type = 'Rejected' THEN requested_discount END)   AS total_rejected,
            SUM(CASE WHEN cta_type = 'Open'     THEN requested_discount END)   AS open_requested,
            COUNT(*)                                                            AS total_ctas,
            COUNT(CASE WHEN cta_type = 'Approved' THEN 1 END)                  AS approved_count,
            COUNT(CASE WHEN cta_type = 'Rejected' THEN 1 END)                  AS rejected_count,
            COUNT(CASE WHEN cta_type = 'Open'     THEN 1 END)                  AS open_count
        FROM gs
        {where}
    """).iloc[0]

with st.spinner("Loading KPIs…"):
    kpi = load_kpis(dim_cache_key)

c1, c2, c3, c4 = st.columns(4)

def _kpi_card(col, title, value, count, color):
    """Mini KPI card with colored badge — matches screenshot style."""
    col.markdown(f"""
    <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;
                padding:16px 20px;">
        <div style="font-size:13px;color:#374151;font-weight:600;
                    margin-bottom:10px;">{title}</div>
        <span style="background:{color};color:#fff;font-weight:700;
                     font-size:14px;padding:5px 12px;border-radius:20px;">
            {fmt(float(value or 0), CURRENCY, raw=raw_values)}
        </span>
        <div style="font-size:12px;color:#9ca3af;margin-top:8px;">{int(count or 0):,} CTAs</div>
    </div>""", unsafe_allow_html=True)

with c1: _kpi_card(c1, "Total Requested $",  kpi["total_requested"], kpi["total_ctas"],     "#f97316")
with c2: _kpi_card(c2, "Total Approved $",   kpi["total_approved"],  kpi["approved_count"], "#22c55e")
with c3: _kpi_card(c3, "Total Rejected $",   kpi["total_rejected"],  kpi["rejected_count"], "#6ee7b7")
with c4: _kpi_card(c4, "Open Requests $",    kpi["open_requested"],  kpi["open_count"],     "#dc2626")

st.divider()


# ─────────────────────────────────────────────
# SECTION 2 — OPEN REQUESTS AGEING
# Days open = CURRENT_DATE - created_date
# Only for cta_type = 'Open'
# ─────────────────────────────────────────────

st.subheader("Open Requests Ageing")

AGEING_BUCKETS_GS = [
    ("1-30 Days",   "days_open BETWEEN 1 AND 30",   "#6ee7b7", "#065f46"),
    ("31-60 Days",  "days_open BETWEEN 31 AND 60",  "#5eead4", "#134e4a"),
    ("61-90 Days",  "days_open BETWEEN 61 AND 90",  "#a3e635", "#365314"),
    ("91-180 Days", "days_open BETWEEN 91 AND 180", "#fef08a", "#713f12"),
    (">180 Days",   "days_open > 180",              "#fb923c", "#7c2d12"),
]

@st.cache_data(ttl=300, show_spinner=False)
def load_open_ageing(dim_key):
    # Build open-only where (reuse dim filters but force cta_type = 'Open')
    base_where = build_where(selected_fy)
    if base_where:
        open_where = base_where + "\n  AND cta_type = 'Open'"
    else:
        open_where = "WHERE cta_type = 'Open'"

    cases = ",\n            ".join([
        f"SUM(CASE WHEN {cond} THEN requested_discount ELSE 0 END) AS bucket_{i}"
        for i, (label, cond, _, _) in enumerate(AGEING_BUCKETS_GS)
    ])
    return run_query(f"""
        SELECT {cases}
        FROM (
            SELECT requested_discount,
                   (CURRENT_DATE - created_date::date) AS days_open
            FROM gs
            {open_where}
        ) sub
    """).iloc[0]

with st.spinner("Loading open ageing…"):
    age_kpi = load_open_ageing(dim_cache_key)

age_cols = st.columns(len(AGEING_BUCKETS_GS))
for i, (label, _, bg, text_color) in enumerate(AGEING_BUCKETS_GS):
    val = float(age_kpi[f"bucket_{i}"] or 0)
    with age_cols[i]:
        st.markdown(f"""
        <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;
                    padding:16px 20px;">
            <div style="font-size:13px;color:#374151;font-weight:600;
                        margin-bottom:10px;">{label}</div>
            <span style="background:{bg};color:{text_color};font-weight:700;
                         font-size:14px;padding:5px 12px;border-radius:20px;">
                {fmt(val, CURRENCY, raw=raw_values)}
            </span>
        </div>""", unsafe_allow_html=True)

st.divider()


# ─────────────────────────────────────────────
# SECTION 3 — OPEN REQUESTS STAGE-WISE SPLIT
# ─────────────────────────────────────────────

st.subheader("Open Requests — Stage Wise Split")

@st.cache_data(ttl=300, show_spinner=False)
def load_open_by_stage(dim_key):
    base_where = build_where(selected_fy)
    open_where = (base_where + "\n  AND cta_type = 'Open'") if base_where else "WHERE cta_type = 'Open'"
    return run_query(f"""
        SELECT
            status,
            SUM(requested_discount) AS requested_amount,
            COUNT(*)                AS cta_count
        FROM gs
        {open_where}
        GROUP BY status
        ORDER BY requested_amount DESC NULLS LAST
    """)

with st.spinner("Loading stage split…"):
    stage_df = load_open_by_stage(dim_cache_key)

if not stage_df.empty:
    view_stage = st.radio("View", ["Table", "Chart"], horizontal=True,
                          key="stage_view", label_visibility="collapsed")
    total_stage = stage_df["requested_amount"].sum()
    grand_stage = pd.DataFrame([{
        "status": "Grand Total",
        "requested_amount": total_stage,
        "cta_count": stage_df["cta_count"].sum()
    }])
    stage_disp = pd.concat([stage_df, grand_stage], ignore_index=True)

    if view_stage == "Table":
        stage_disp["requested_amount"] = stage_disp["requested_amount"].apply(
            lambda x: fmt(x, CURRENCY, raw=raw_values)
        )
        stage_disp.columns = ["Stage", "Requested Amount", "# CTAs"]
        st.dataframe(stage_disp, width="stretch", hide_index=True)
    else:
        fig = px.bar(
            stage_df.sort_values("requested_amount"),
            x="requested_amount", y="status", orientation="h",
            title="Open Requests by Stage",
            color_discrete_sequence=px.colors.qualitative.Set2,
            text=stage_df.sort_values("requested_amount")["requested_amount"].apply(
                lambda v: fmt(v, CURRENCY, raw=raw_values)
            ),
        )
        fig.update_traces(textposition="outside", cliponaxis=False)
        fig.update_layout(xaxis_title="Requested Amount (USD)", yaxis_title="",
                          margin=dict(l=10, r=120, t=40, b=10))
        st.plotly_chart(fig, width="stretch", key="chart_stage")

st.divider()


# ─────────────────────────────────────────────
# SECTION 4 — APPROVED REQUESTS DISCOUNT TYPE SPLIT
# ─────────────────────────────────────────────

st.subheader("Approved Requests — Discount Type Split")

@st.cache_data(ttl=300, show_spinner=False)
def load_approved_by_type(dim_key):
    base_where = build_where(selected_fy)
    appr_where = (base_where + "\n  AND cta_type = 'Approved'") if base_where else "WHERE cta_type = 'Approved'"
    return run_query(f"""
        SELECT
            COALESCE(type_of_discount_gc, 'Unassigned') AS discount_type,
            SUM(approved_discount)  AS approved_amount,
            COUNT(*)                AS cta_count
        FROM gs
        {appr_where}
        GROUP BY type_of_discount_gc
        ORDER BY approved_amount DESC NULLS LAST
    """)

with st.spinner("Loading discount type split…"):
    dtype_df = load_approved_by_type(dim_cache_key)

if not dtype_df.empty:
    view_dtype = st.radio("View", ["Table", "Chart"], horizontal=True,
                          key="dtype_view", label_visibility="collapsed")
    total_dtype = dtype_df["approved_amount"].sum()
    grand_dtype = pd.DataFrame([{
        "discount_type": "Grand Total",
        "approved_amount": total_dtype,
        "cta_count": dtype_df["cta_count"].sum()
    }])
    dtype_disp = pd.concat([dtype_df, grand_dtype], ignore_index=True)

    if view_dtype == "Table":
        dtype_disp["approved_amount"] = dtype_disp["approved_amount"].apply(
            lambda x: fmt(x, CURRENCY, raw=raw_values)
        )
        dtype_disp.columns = ["Discount Type", "Approved", "# CTAs"]
        st.dataframe(dtype_disp, width="stretch", hide_index=True)
    else:
        fig = px.bar(
            dtype_df.sort_values("approved_amount"),
            x="approved_amount", y="discount_type", orientation="h",
            title="Approved Discounts by Type",
            color_discrete_sequence=px.colors.qualitative.Pastel,
            text=dtype_df.sort_values("approved_amount")["approved_amount"].apply(
                lambda v: fmt(v, CURRENCY, raw=raw_values)
            ),
        )
        fig.update_traces(textposition="outside", cliponaxis=False)
        fig.update_layout(xaxis_title="Approved Amount (USD)", yaxis_title="",
                          margin=dict(l=10, r=120, t=40, b=10))
        st.plotly_chart(fig, width="stretch", key="chart_dtype")

st.divider()


# ─────────────────────────────────────────────
# SECTION 5 — REGION WISE ($ AND COUNT)
# ─────────────────────────────────────────────

st.subheader("Region Wise — Requested, Approved and Rejected")

@st.cache_data(ttl=300, show_spinner=False)
def load_by_region(dim_key):
    where = build_where(selected_fy)
    return run_query(f"""
        SELECT
            region,
            SUM(requested_discount)                                             AS requested,
            SUM(CASE WHEN cta_type = 'Approved' THEN approved_discount  END)   AS approved,
            SUM(CASE WHEN cta_type = 'Rejected' THEN requested_discount END)   AS rejected,
            COUNT(*)                                                            AS total_count,
            COUNT(CASE WHEN cta_type = 'Approved' THEN 1 END)                  AS approved_count,
            COUNT(CASE WHEN cta_type = 'Rejected' THEN 1 END)                  AS rejected_count
        FROM gs
        {where}
        GROUP BY region
        ORDER BY requested DESC NULLS LAST
    """)

with st.spinner("Loading region breakdown…"):
    reg_df = load_by_region(dim_cache_key)

if not reg_df.empty:
    # ── $ split ──────────────────────────────────────────────────────────────
    st.markdown("**Region wise — Requested, Approved and Rejected ($)**")
    view_reg_amt = st.radio("View", ["Table", "Chart"], horizontal=True,
                            key="reg_amt_view", label_visibility="collapsed")

    if view_reg_amt == "Table":
        reg_amt = reg_df[["region", "requested", "approved", "rejected"]].copy()
        grand_ra = {"region": "Grand Total",
                    "requested": reg_amt["requested"].sum(),
                    "approved":  reg_amt["approved"].sum(),
                    "rejected":  reg_amt["rejected"].sum()}
        reg_amt = pd.concat([reg_amt, pd.DataFrame([grand_ra])], ignore_index=True)
        for col in ["requested", "approved", "rejected"]:
            reg_amt[col] = reg_amt[col].apply(lambda x: fmt(x, CURRENCY, raw=raw_values))
        reg_amt.columns = ["Region", "Requested", "Approved", "Rejected"]
        st.dataframe(reg_amt, width="stretch", hide_index=True)
    else:
        reg_melt = reg_df[["region", "requested", "approved", "rejected"]].melt(
            id_vars="region", var_name="type", value_name="amount"
        )
        fig = px.bar(
            reg_melt, x="region", y="amount", color="type",
            barmode="group", title="Region wise — $ Amount",
            color_discrete_map={
                "requested": "#1d4ed8",
                "approved":  "#ec4899",
                "rejected":  "#22c55e",
            },
            text=reg_melt["amount"].apply(lambda v: fmt(v, CURRENCY, raw=raw_values)),
            height=400,
        )
        fig.update_traces(textposition="outside", cliponaxis=False, textfont=dict(size=10))
        fig.update_layout(xaxis_title="", yaxis_title="Amount (USD)",
                          legend_title="Type",
                          margin=dict(l=10, r=10, t=40, b=60))
        st.plotly_chart(fig, width="stretch", key="chart_reg_amt")

    st.markdown("")

    # ── Count split ───────────────────────────────────────────────────────────
    st.markdown("**Region wise — Requested, Approved and Rejected (Count)**")
    view_reg_cnt = st.radio("View", ["Table", "Chart"], horizontal=True,
                            key="reg_cnt_view", label_visibility="collapsed")

    if view_reg_cnt == "Table":
        reg_cnt = reg_df[["region", "total_count", "approved_count", "rejected_count"]].copy()
        grand_rc = {"region": "Grand Total",
                    "total_count":    int(reg_cnt["total_count"].sum()),
                    "approved_count": int(reg_cnt["approved_count"].sum()),
                    "rejected_count": int(reg_cnt["rejected_count"].sum())}
        reg_cnt = pd.concat([reg_cnt, pd.DataFrame([grand_rc])], ignore_index=True)
        reg_cnt.columns = ["Region", "Requested", "Approved", "Rejected"]
        st.dataframe(reg_cnt, width="stretch", hide_index=True)
    else:
        reg_cnt_melt = reg_df[["region", "total_count", "approved_count", "rejected_count"]].melt(
            id_vars="region", var_name="type", value_name="count"
        )
        fig2 = px.bar(
            reg_cnt_melt, x="region", y="count", color="type",
            barmode="group", title="Region wise — Count",
            color_discrete_map={
                "total_count":    "#1d4ed8",
                "approved_count": "#eab308",
                "rejected_count": "#dc2626",
            },
            text="count", height=400,
        )
        fig2.update_traces(textposition="outside", cliponaxis=False, textfont=dict(size=10))
        fig2.update_layout(xaxis_title="", yaxis_title="# CTAs",
                           legend_title="Type",
                           margin=dict(l=10, r=10, t=40, b=60))
        st.plotly_chart(fig2, width="stretch", key="chart_reg_cnt")

st.divider()


# ─────────────────────────────────────────────
# SECTION 6 — TOP 20 DISCOUNTS
# Two sub-sections: NetSuite (credit notes) and Gainsight (CTAs)
# ─────────────────────────────────────────────

st.subheader("Top 20 Discounts — NS, GS")

# ── NetSuite (credit notes from billing table) ───────────────────────────────
st.markdown("**Netsuite**")

@st.cache_data(ttl=300, show_spinner=False)
def load_top_ns(dim_key):
    # Credit notes are CustCred rows in billing — negative billing_amount.
    # ABS() so the "Discount Amount" column shows a positive figure.
    # FY filter and dimension filters re-use the same sidebar selections.
    clauses = [
        "transaction_type = 'CustCred'",
        "inter_company_status = 'F'",
    ]
    if selected_fy != "All":
        fy_start, fy_end = fy_date_range(selected_fy)
        clauses.append(f"transaction_date >= '{fy_start}' AND transaction_date < '{fy_end}'")
    # Dimension filters that exist on the billing table
    def in_clause(col, selections):
        if selections:
            v = ", ".join(f"'{s}'" for s in selections)
            clauses.append(f"{col} IN ({v})")
    in_clause("region",               sel_region)
    in_clause("client_journey_stage", sel_cjs)
    in_clause("client_buckets",       sel_bucket)
    in_clause("collection_status",    sel_status)

    ns_where = "WHERE " + "\n  AND ".join(clauses)

    return run_query(f"""
        SELECT
            transaction_number                                          AS inv_no,
            customer_ucc                                                AS ucc,
            customer_name                                               AS customer,
            transaction_date::date                                      AS doc_issue_date,
            ABS(billing_amount * usd_exchangerate)                      AS discount_amount
        FROM billing
        {ns_where}
        ORDER BY discount_amount DESC NULLS LAST
        LIMIT 20
    """)

with st.spinner("Loading top NS discounts…"):
    top_ns = load_top_ns(dim_cache_key)

if not top_ns.empty:
    tab_ns_t, tab_ns_c = st.tabs(["Table", "Chart"])
    with tab_ns_t:
        ns_disp = top_ns.copy()
        ns_disp["discount_amount"] = ns_disp["discount_amount"].apply(
            lambda x: fmt(x, CURRENCY, raw=raw_values)
        )
        ns_disp.columns = ["Inv No", "UCC", "Customer", "Doc Issue Date", "Discount Amount"]
        st.dataframe(ns_disp, width="stretch", hide_index=True)
    with tab_ns_c:
        fig_ns = px.bar(
            top_ns.sort_values("discount_amount"),
            x="discount_amount", y="customer", orientation="h",
            title="Top 20 NS Discounts",
            color_discrete_sequence=px.colors.qualitative.Set2,
            text=top_ns.sort_values("discount_amount")["discount_amount"].apply(
                lambda v: fmt(v, CURRENCY, raw=raw_values)
            ),
            height=max(400, len(top_ns) * 30),
        )
        fig_ns.update_traces(textposition="outside", cliponaxis=False)
        fig_ns.update_layout(xaxis_title="Discount Amount (USD)", yaxis_title="",
                             margin=dict(l=10, r=120, t=40, b=10))
        st.plotly_chart(fig_ns, width="stretch", key="chart_top_ns")
else:
    st.info("No NetSuite credit notes found for the selected filters.")

st.markdown("")

# ── Gainsight (CTA level) ─────────────────────────────────────────────────────
st.markdown("**Gainsight**")

@st.cache_data(ttl=300, show_spinner=False)
def load_top_gs(dim_key):
    base_where = build_where(selected_fy)
    appr_where = (base_where + "\n  AND cta_type = 'Approved'") if base_where else "WHERE cta_type = 'Approved'"
    return run_query(f"""
        SELECT
            name                                            AS cta_name,
            COALESCE(netsuite_company_name,
                     gainsight_company_name)                AS client_name,
            customer_ucc                                    AS ucc,
            reason                                          AS discount_reason,
            approved_discount                               AS approved_amount
        FROM gs
        {appr_where}
        ORDER BY approved_discount DESC NULLS LAST
        LIMIT 20
    """)

with st.spinner("Loading top GS discounts…"):
    top_gs = load_top_gs(dim_cache_key)

if not top_gs.empty:
    tab_gs_t, tab_gs_c = st.tabs(["Table", "Chart"])
    with tab_gs_t:
        gs_disp = top_gs.copy()
        gs_disp["approved_amount"] = gs_disp["approved_amount"].apply(
            lambda x: fmt(x, CURRENCY, raw=raw_values)
        )
        gs_disp.columns = ["CTA Name", "Client Name", "UCC", "Discount Reason", "Approved Amount"]
        st.dataframe(gs_disp, width="stretch", hide_index=True)
    with tab_gs_c:
        fig_gs = px.bar(
            top_gs.sort_values("approved_amount"),
            x="approved_amount", y="client_name", orientation="h",
            title="Top 20 GS Approved Discounts",
            color_discrete_sequence=px.colors.qualitative.Pastel,
            text=top_gs.sort_values("approved_amount")["approved_amount"].apply(
                lambda v: fmt(v, CURRENCY, raw=raw_values)
            ),
            height=max(400, len(top_gs) * 30),
        )
        fig_gs.update_traces(textposition="outside", cliponaxis=False)
        fig_gs.update_layout(xaxis_title="Approved Amount (USD)", yaxis_title="",
                             margin=dict(l=10, r=120, t=40, b=10))
        st.plotly_chart(fig_gs, width="stretch", key="chart_top_gs")
else:
    st.info("No approved Gainsight discounts found for the selected filters.")