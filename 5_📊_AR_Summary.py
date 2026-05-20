"""
dashboard_ar_summary.py  (place in pages/ as  5_📊_AR_Summary.py)
AR Aging Summary — customer-level aging breakdown, real-time snapshot.
"""

import streamlit as st
import pandas as pd
from datetime import date
from dashboard_utils import run_query, fmt, fmt_pct, render_kpi_card

st.set_page_config(page_title="AR Aging Summary", layout="wide")

AR_AGEING_BUCKETS = [
    ("Current",     "open_days < 1"),
    ("1-30 days",   "open_days BETWEEN 1 AND 30"),
    ("31-60 days",  "open_days BETWEEN 31 AND 60"),
    ("61-90 days",  "open_days BETWEEN 61 AND 90"),
    ("91-180 days", "open_days BETWEEN 91 AND 180"),
    (">180 days",   "open_days > 180"),
]

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
    st.header("Settings")
    currency = st.radio("Currency", ["USD", "INR"], horizontal=True)
    raw_values = st.toggle("Show raw values", value=False)
    rate_col = "usd_exchangerate" if currency == "USD" else "inr_exchangerate"

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


def build_where():
    clauses = ["inter_company_status = 'F'"]
    _add_dim_clauses(clauses)
    return "WHERE " + "\n  AND ".join(clauses)


# ─────────────────────────────────────────────
# PAGE HEADER + DIMENSION FILTERS
# ─────────────────────────────────────────────

st.title("📊 AR Aging Summary")
st.caption(f"Real-time snapshot · As of {date.today().strftime('%d %b %Y')} · "
           f"External customers only · {currency}")

with st.expander("🔽 Filters", expanded=True):
    r1c1, r1c2, r1c3 = st.columns(3)
    r2c1, r2c2, r2c3 = st.columns(3)
    with r1c1:
        sel_region   = st.multiselect("Region", opts["region"], placeholder="All regions")
    with r1c2:
        sel_entity   = st.multiselect("Billing Entity", opts["subsidiary_name"], placeholder="All entities")
    with r1c3:
        sel_cjs      = st.multiselect("Client Journey Stage", opts["client_journey_stage"], placeholder="All stages")
    with r2c1:
        sel_bucket   = st.multiselect("Client Bucket", opts["client_buckets"], placeholder="All buckets")
    with r2c2:
        sel_status   = st.multiselect("Collection Status", opts["collection_status"], placeholder="All statuses")
    with r2c3:
        sel_currency = st.multiselect("Transaction Currency", opts["currency_symbol"], placeholder="All currencies")

dim_cache_key = (
    currency,
    tuple(sel_region), tuple(sel_entity), tuple(sel_cjs),
    tuple(sel_bucket), tuple(sel_status), tuple(sel_currency)
)

st.divider()

# ─────────────────────────────────────────────
# SECTION 1 — GRAND TOTAL SUMMARY CARDS
# ─────────────────────────────────────────────

bucket_cases = ",\n            ".join([
    f"SUM(CASE WHEN {cond} THEN open_amount * {rate_col} ELSE 0 END) AS bucket_{i}"
    for i, (label, cond) in enumerate(AR_AGEING_BUCKETS)
])

@st.cache_data(ttl=300, show_spinner=False)
def load_totals(rate, dim_key):
    cases = ",\n            ".join([
        f"SUM(CASE WHEN {cond} THEN open_amount * {rate} ELSE 0 END) AS bucket_{i}"
        for i, (label, cond) in enumerate(AR_AGEING_BUCKETS)
    ])
    return run_query(f"""
        SELECT
            SUM(open_amount * {rate})                                           AS total_outstanding,
            SUM(CASE WHEN open_days >= 1 THEN open_amount * {rate} ELSE 0 END) AS total_overdue,
            {cases}
        FROM ar
        {build_where()}
    """).iloc[0]

with st.spinner("Loading totals…"):
    totals = load_totals(rate_col, dim_cache_key)

# Top 2 KPIs
c1, c2 = st.columns(2)
with c1:
    render_kpi_card("Total Outstanding", totals["total_outstanding"],
                    currency=currency, vs_label="", raw=raw_values)
with c2:
    render_kpi_card("Total Overdue", totals["total_overdue"],
                    currency=currency, vs_label="", raw=raw_values)

st.markdown("")

# Ageing bucket summary cards
st.markdown("**Ageing Breakdown**")
bucket_cols = st.columns(len(AR_AGEING_BUCKETS))
total_out   = float(totals["total_outstanding"] or 1)
for i, (label, _) in enumerate(AR_AGEING_BUCKETS):
    val = float(totals[f"bucket_{i}"] or 0)
    pct = val / total_out if total_out else 0
    with bucket_cols[i]:
        st.markdown(f"""
        <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;
                    padding:12px 16px;text-align:center;">
            <div style="font-size:11px;color:#6b7280;font-weight:500;
                        text-transform:uppercase;letter-spacing:0.04em;
                        margin-bottom:4px;">{label}</div>
            <div style="font-size:18px;font-weight:700;color:#111827;
                        margin-bottom:2px;">{fmt(val, currency, raw=raw_values)}</div>
            <div style="font-size:12px;color:#6b7280;">{fmt_pct(pct)}</div>
        </div>
        """, unsafe_allow_html=True)

st.divider()

# ─────────────────────────────────────────────
# SECTION 2 — CUSTOMER SEARCH
# ─────────────────────────────────────────────

search = st.text_input(
    "🔍 Search customer", placeholder="Company name, UCC, or Entity ID…",
    help="Filters the aging table below by company name, UCC, or entity ID"
)

# ─────────────────────────────────────────────
# SECTION 3 — CUSTOMER-LEVEL AGING TABLE
# ─────────────────────────────────────────────

st.subheader("Customer Aging Detail")

@st.cache_data(ttl=300, show_spinner=False)
def load_aging_detail(rate, dim_key):
    cases = ",\n            ".join([
        f"SUM(CASE WHEN {cond} THEN open_amount * {rate} ELSE 0 END) AS bucket_{i}"
        for i, (label, cond) in enumerate(AR_AGEING_BUCKETS)
    ])
    return run_query(f"""
        SELECT
            customer_ucc,
            entity_id,
            customer_name,
            client_buckets,
            collection_status,
            client_journey_stage,
            SUM(open_amount * {rate})                                           AS total_outstanding,
            SUM(CASE WHEN open_days >= 1 THEN open_amount * {rate} ELSE 0 END) AS total_overdue,
            {cases}
        FROM ar
        {build_where()}
          AND customer_name IS NOT NULL
        GROUP BY customer_ucc, entity_id, customer_name, client_buckets,
                 collection_status, client_journey_stage
        ORDER BY total_outstanding DESC
    """)

with st.spinner("Loading customer aging detail…"):
    detail = load_aging_detail(rate_col, dim_cache_key)

if not detail.empty:
    # Apply search filter
    if search:
        s = search.lower()
        detail = detail[
            detail["customer_name"].fillna("").str.lower().str.contains(s, regex=False) |
            detail["customer_ucc"].fillna("").str.lower().str.contains(s, regex=False) |
            detail["entity_id"].fillna("").str.lower().str.contains(s, regex=False)
        ]

    total_rows = len(detail)
    st.caption(f"{total_rows:,} customers")

    # Build grand total row
    grand = {"customer_ucc": "", "entity_id": "", "customer_name": "Grand Total",
             "client_buckets": "", "collection_status": "",
             "client_journey_stage": ""}
    for col in ["total_outstanding", "total_overdue"] + [f"bucket_{i}" for i in range(len(AR_AGEING_BUCKETS))]:
        grand[col] = detail[col].sum()

    display_df = pd.concat([detail, pd.DataFrame([grand])], ignore_index=True)

    # Format all amount columns
    for i in range(len(AR_AGEING_BUCKETS)):
        display_df[f"bucket_{i}"] = display_df[f"bucket_{i}"].apply(
            lambda x: fmt(x, currency, raw=raw_values) if pd.notnull(x) and x != "" else ""
        )
    display_df["total_outstanding"] = display_df["total_outstanding"].apply(
        lambda x: fmt(x, currency, raw=raw_values) if pd.notnull(x) and x != "" else ""
    )
    display_df["total_overdue"] = display_df["total_overdue"].apply(
        lambda x: fmt(x, currency, raw=raw_values) if pd.notnull(x) and x != "" else ""
    )

    # Rename columns
    rename_map = {
        "customer_ucc":         "UCC",
        "entity_id":            "Entity ID",
        "customer_name":        "Company Name",
        "client_buckets":       "Client Bucket",
        "collection_status":    "Collection Status",
        "client_journey_stage": "Customer Journey",
        "total_outstanding":    "Total Outstanding",
        "total_overdue":        "Total Overdue",
    }
    for i, (label, _) in enumerate(AR_AGEING_BUCKETS):
        rename_map[f"bucket_{i}"] = label

    display_df = display_df.rename(columns=rename_map)

    # Column order: identity → dimensions → buckets → totals
    col_order = (
        ["UCC", "Entity ID", "Company Name", "Client Bucket",
         "Collection Status", "Customer Journey"]
        + [label for label, _ in AR_AGEING_BUCKETS]
        + ["Total Outstanding", "Total Overdue"]
    )
    display_df = display_df[col_order]

    st.dataframe(display_df, width='stretch', hide_index=True)
else:
    st.info("No AR data found for the selected filters.")