"""
dashboard_unified.py  (place in pages/ as  6_🔗_Billing_vs_Collections.py)
Billing + Collections unified dashboard — uses finance_unified_txn view.
No Claude API calls.
"""

import streamlit as st
import pandas as pd
from dashboard_utils import (
    run_query, get_fy_info, fmt, fmt_pct,
    render_kpi_card, render_bar_chart, render_line_chart,
)

st.set_page_config(page_title="Billing vs Collections", layout="wide")

# ─────────────────────────────────────────────
# FY + FILTER OPTIONS
# ─────────────────────────────────────────────

fy     = get_fy_info()
CUR_FY = fy["current_fy"]
PREV_FY = fy["previous_fy"]

@st.cache_data(ttl=3600, show_spinner=False)
def load_filter_options():
    def vals(col, include_unassigned=False):
        cond = f"WHERE {col} IS NOT NULL" if include_unassigned \
               else f"WHERE {col} IS NOT NULL AND {col} != 'Unassigned'"
        df = run_query(
            f"SELECT DISTINCT {col} FROM finance_unified_txn {cond} ORDER BY {col}"
        )
        return df[col].tolist()
    return {
        "region":               vals("region", include_unassigned=True),
        "subsidiary_name":      vals("subsidiary_name"),
        "client_journey_stage": vals("client_journey_stage", include_unassigned=True),
        "client_buckets":       vals("client_buckets", include_unassigned=True),
        "collection_status":    vals("collection_status", include_unassigned=True),
    }

with st.spinner("Loading filters…"):
    opts = load_filter_options()

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────

with st.sidebar:
    st.header("Filters")
    currency = st.radio("Currency", ["USD", "INR"], horizontal=True)
    raw_values = st.toggle("Show raw values", value=False)
    suf      = "usd" if currency == "USD" else "inr"

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
            v = ", ".join(f"'{s}'" for s in selections)
            clauses.append(f"{col} IN ({v})")
    in_clause("region",               sel_region)
    in_clause("subsidiary_name",      sel_entity)
    in_clause("client_journey_stage", sel_cjs)
    in_clause("client_buckets",       sel_bucket)
    in_clause("collection_status",    sel_status)


def build_where(fy_filter, include_ic=False):
    ic = "'T'" if include_ic else "'F'"
    clauses = [
        f"inter_company_status = {ic}",
        f"fy_quarter LIKE '{fy_filter}%'",
    ]
    _add_dim_clauses(clauses)
    return "WHERE " + "\n  AND ".join(clauses)


def build_dim_filters(include_ic=False):
    ic = "'T'" if include_ic else "'F'"
    clauses = [f"inter_company_status = {ic}"]
    _add_dim_clauses(clauses)
    return "WHERE " + "\n  AND ".join(clauses)


# ─────────────────────────────────────────────
# PAGE HEADER + DIMENSION FILTERS
# ─────────────────────────────────────────────

selected_fy = st.session_state.get("bvc_fy", CUR_FY)
PREV = PREV_FY if selected_fy == CUR_FY else fy["two_years_ago_fy"]

st.title(f"🔗 Billing vs Collections — {selected_fy}")
st.caption(f"External customers · {currency} · finance_unified_txn")
st.divider()

with st.expander("🔽 Filters", expanded=True):
    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    with r1c1:
        selected_fy = st.selectbox("Financial Year", options=[CUR_FY, PREV_FY, fy["two_years_ago_fy"]], index=0, key="bvc_fy")
    with r1c2:
        sel_region = st.multiselect("Region", opts["region"], placeholder="All regions")
    with r1c3:
        sel_entity = st.multiselect("Billing Entity", opts["subsidiary_name"], placeholder="All entities")
    with r1c4:
        sel_cjs = st.multiselect("Client Journey Stage", opts["client_journey_stage"], placeholder="All stages")
    r2c1, r2c2 = st.columns(2)
    with r2c1:
        sel_bucket = st.multiselect("Client Bucket", opts["client_buckets"], placeholder="All buckets")
    with r2c2:
        sel_status = st.multiselect("Collection Status", opts["collection_status"], placeholder="All statuses")

dim_cache_key = (
    currency, selected_fy,
    tuple(sel_region), tuple(sel_entity), tuple(sel_cjs),
    tuple(sel_bucket), tuple(sel_status),
)

st.divider()

# ─────────────────────────────────────────────
# SECTION 1 — KPI CARDS
# ─────────────────────────────────────────────

st.subheader("Key Metrics")

@st.cache_data(ttl=300, show_spinner=False)
def load_kpis(fy_filter, prev_filter, suf, dim_key):
    where = build_dim_filters()
    return run_query(f"""
        SELECT
            SUM(CASE WHEN fy_quarter LIKE '{fy_filter}%' THEN billed_{suf}          ELSE 0 END) AS billed,
            SUM(CASE WHEN fy_quarter LIKE '{fy_filter}%' THEN collected_net_{suf}   ELSE 0 END) AS collected,
            SUM(CASE WHEN fy_quarter LIKE '{fy_filter}%' THEN billed_{suf} - collected_net_{suf} ELSE 0 END) AS gap,
            SUM(CASE WHEN fy_quarter LIKE '{prev_filter}%' THEN billed_{suf}        ELSE 0 END) AS prev_billed,
            SUM(CASE WHEN fy_quarter LIKE '{prev_filter}%' THEN collected_net_{suf} ELSE 0 END) AS prev_collected,
            ROUND(
                SUM(CASE WHEN fy_quarter LIKE '{fy_filter}%' THEN collected_net_{suf} ELSE 0 END) /
                NULLIF(SUM(CASE WHEN fy_quarter LIKE '{fy_filter}%' THEN billed_{suf} ELSE 0 END), 0), 4
            ) AS efficiency
        FROM finance_unified_txn
        {where}
    """).iloc[0]

with st.spinner("Loading KPIs…"):
    kpi = load_kpis(selected_fy, PREV, suf, dim_cache_key)

c1, c2, c3, c4 = st.columns(4)
with c1:
    render_kpi_card("YTD Billed", kpi["billed"], kpi["prev_billed"], currency, raw=raw_values)
with c2:
    render_kpi_card("YTD Collected (Net)", kpi["collected"], kpi["prev_collected"], currency)
with c3:
    render_kpi_card("Billing-Collection Gap", kpi["gap"], currency=currency, vs_label="", raw=raw_values)
with c4:
    eff = float(kpi["efficiency"] or 0)
    st.markdown(f"""
    <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;padding:16px 20px;">
        <div style="font-size:12px;color:#6b7280;font-weight:500;text-transform:uppercase;
                    letter-spacing:0.05em;margin-bottom:6px;">Collection Efficiency</div>
        <div style="font-size:26px;font-weight:700;
                    color:{'#22c55e' if eff >= 0.9 else '#f59e0b' if eff >= 0.7 else '#ef4444'};">
            {eff*100:.1f}%</div>
        <div style="font-size:13px;color:#9ca3af;">collected / billed</div>
    </div>
    """, unsafe_allow_html=True)

st.divider()

# ─────────────────────────────────────────────
# SECTION 2 — QoQ TREND
# ─────────────────────────────────────────────

st.subheader(f"QoQ Billing vs Collections — {selected_fy}")

@st.cache_data(ttl=300, show_spinner=False)
def load_qoq(fy_filter, suf, dim_key):
    return run_query(f"""
        SELECT fy_quarter,
               SUM(billed_{suf})        AS billed,
               SUM(collected_net_{suf}) AS collected
        FROM finance_unified_txn
        {build_where(fy_filter)}
        GROUP BY fy_quarter ORDER BY fy_quarter
    """)

with st.spinner("Loading QoQ…"):
    qoq = load_qoq(selected_fy, suf, dim_cache_key)

if not qoq.empty:
    view = st.radio("View", ["Table", "Chart"], horizontal=True,
                    key="qoq_view", label_visibility="collapsed")
    if view == "Chart":
        render_line_chart(qoq, "fy_quarter", ["billed", "collected"],
                         f"QoQ Billing vs Collections — {selected_fy}", currency, raw=raw_values)
    else:
        qoq_d = qoq.copy()
        qoq_d["efficiency"] = (qoq_d["collected"] / qoq_d["billed"].replace(0, pd.NA)).apply(
            lambda x: f"{x*100:.1f}%" if pd.notnull(x) else "—"
        )
        grand = {"fy_quarter": "Grand Total",
                 "billed": qoq["billed"].sum(),
                 "collected": qoq["collected"].sum()}
        grand["efficiency"] = f"{grand['collected']/grand['billed']*100:.1f}%" if grand["billed"] else "—"
        qoq_d = pd.concat([qoq_d, pd.DataFrame([grand])], ignore_index=True)
        qoq_d["billed"]    = qoq_d["billed"].apply(lambda x: fmt(x, currency, raw=raw_values) if isinstance(x, (int,float)) else x)
        qoq_d["collected"] = qoq_d["collected"].apply(lambda x: fmt(x, currency, raw=raw_values) if isinstance(x, (int,float)) else x)
        qoq_d.columns = ["Quarter", "Billed", "Net Collections", "Efficiency"]
        st.dataframe(qoq_d, width='stretch', hide_index=True)

st.divider()

# ─────────────────────────────────────────────
# SECTION 3 — BY BILLING ENTITY
# ─────────────────────────────────────────────

st.subheader("Billing vs Collections — By Entity")

@st.cache_data(ttl=300, show_spinner=False)
def load_by_entity(fy_filter, suf, dim_key):
    return run_query(f"""
        SELECT subsidiary_name,
               SUM(billed_{suf})        AS billed,
               SUM(collected_net_{suf}) AS collected,
               ROUND(SUM(collected_net_{suf}) / NULLIF(SUM(billed_{suf}), 0), 4) AS efficiency
        FROM finance_unified_txn
        {build_where(fy_filter)}
        GROUP BY subsidiary_name ORDER BY billed DESC
    """)

with st.spinner("Loading entity breakdown…"):
    ent = load_by_entity(selected_fy, suf, dim_cache_key)

if not ent.empty:
    view = st.radio("View", ["Table", "Chart"], horizontal=True,
                    key="entity_view", label_visibility="collapsed")
    if view == "Table":
        ent_d = ent.copy()
        grand = {"subsidiary_name": "Grand Total",
                 "billed": ent["billed"].sum(), "collected": ent["collected"].sum()}
        grand["efficiency"] = grand["collected"] / grand["billed"] if grand["billed"] else 0
        ent_d = pd.concat([ent_d, pd.DataFrame([grand])], ignore_index=True)
        ent_d["efficiency"] = ent_d["efficiency"].apply(lambda x: f"{float(x)*100:.1f}%" if pd.notnull(x) else "—")
        ent_d["billed"]     = ent_d["billed"].apply(lambda x: fmt(x, currency, raw=raw_values) if isinstance(x, (int,float)) else x)
        ent_d["collected"]  = ent_d["collected"].apply(lambda x: fmt(x, currency, raw=raw_values) if isinstance(x, (int,float)) else x)
        ent_d.columns = ["Billing Entity", "Billed", "Net Collections", "Efficiency"]
        st.dataframe(ent_d, width='stretch', hide_index=True)
    else:
        import plotly.express as px
        fig = px.bar(ent, x="subsidiary_name", y=["billed", "collected"],
                     barmode="group", title=f"Billing vs Collections by Entity — {selected_fy}",
                     color_discrete_sequence=px.colors.qualitative.Set2, height=380)
        fig.update_layout(xaxis_title="", yaxis_title=f"Amount ({'$' if currency=='USD' else '₹'})",
                          legend_title="Metric", margin=dict(l=10,r=10,t=40,b=10))
        st.plotly_chart(fig, width='stretch', key="entity_chart")

st.divider()

# ─────────────────────────────────────────────
# SECTION 4 — BY REGION
# ─────────────────────────────────────────────

st.subheader("Billing vs Collections — By Region")

@st.cache_data(ttl=300, show_spinner=False)
def load_by_region(fy_filter, suf, dim_key):
    return run_query(f"""
        SELECT region,
               SUM(billed_{suf})        AS billed,
               SUM(collected_net_{suf}) AS collected,
               ROUND(SUM(collected_net_{suf}) / NULLIF(SUM(billed_{suf}), 0), 4) AS efficiency
        FROM finance_unified_txn
        {build_where(fy_filter)}
        GROUP BY region ORDER BY billed DESC
    """)

with st.spinner("Loading region breakdown…"):
    reg = load_by_region(selected_fy, suf, dim_cache_key)

if not reg.empty:
    view = st.radio("View", ["Table", "Chart"], horizontal=True,
                    key="region_view", label_visibility="collapsed")
    if view == "Table":
        reg_d = reg.copy()
        grand = {"region": "Grand Total",
                 "billed": reg["billed"].sum(), "collected": reg["collected"].sum()}
        grand["efficiency"] = grand["collected"] / grand["billed"] if grand["billed"] else 0
        reg_d = pd.concat([reg_d, pd.DataFrame([grand])], ignore_index=True)
        reg_d["efficiency"] = reg_d["efficiency"].apply(lambda x: f"{float(x)*100:.1f}%" if pd.notnull(x) else "—")
        reg_d["billed"]     = reg_d["billed"].apply(lambda x: fmt(x, currency, raw=raw_values) if isinstance(x, (int,float)) else x)
        reg_d["collected"]  = reg_d["collected"].apply(lambda x: fmt(x, currency, raw=raw_values) if isinstance(x, (int,float)) else x)
        reg_d.columns = ["Region", "Billed", "Net Collections", "Efficiency"]
        st.dataframe(reg_d, width='stretch', hide_index=True)
    else:
        render_bar_chart(reg, "region", "billed",
                         f"Billed by Region — {selected_fy}", currency, height=350, raw=raw_values)

st.divider()

# ─────────────────────────────────────────────
# SECTION 5 — TOP CUSTOMERS BY GAP
# ─────────────────────────────────────────────

st.subheader("Top 20 Customers — Largest Billing-Collection Gap")
st.caption("Customers billed the most but collected the least proportionally")

@st.cache_data(ttl=300, show_spinner=False)
def load_top_gap(fy_filter, suf, dim_key):
    return run_query(f"""
        SELECT customer_name,
               SUM(billed_{suf})        AS billed,
               SUM(collected_net_{suf}) AS collected,
               SUM(billed_{suf}) - SUM(collected_net_{suf}) AS gap,
               ROUND(SUM(collected_net_{suf}) / NULLIF(SUM(billed_{suf}), 0), 4) AS efficiency
        FROM finance_unified_txn
        {build_where(fy_filter)}
          AND customer_name IS NOT NULL
        GROUP BY customer_name
        HAVING SUM(billed_{suf}) > 0
        ORDER BY gap DESC LIMIT 20
    """)

with st.spinner("Loading gap analysis…"):
    gap = load_top_gap(selected_fy, suf, dim_cache_key)

if not gap.empty:
    tab_t, tab_c = st.tabs(["Table", "Chart"])
    with tab_t:
        gap_d = gap.copy()
        gap_d["efficiency"] = gap_d["efficiency"].apply(lambda x: f"{float(x)*100:.1f}%" if pd.notnull(x) else "—")
        for col in ["billed", "collected", "gap"]:
            gap_d[col] = gap_d[col].apply(lambda x: fmt(x, currency, raw=raw_values) if isinstance(x, (int,float)) else x)
        gap_d.columns = ["Customer", "Billed", "Collected", "Gap", "Efficiency"]
        st.dataframe(gap_d, width='stretch', hide_index=True)
    with tab_c:
        render_bar_chart(gap, "customer_name", "gap",
                         f"Top 20 Billing-Collection Gap — {selected_fy}",
                         currency, horizontal=True,
                         height=max(400, len(gap) * 38))

st.divider()

# ─────────────────────────────────────────────
# SECTION 6 — COLLECTION EFFICIENCY BY CLIENT BUCKET
# ─────────────────────────────────────────────

st.subheader("Collection Efficiency — By Client Bucket")

@st.cache_data(ttl=300, show_spinner=False)
def load_efficiency_bucket(fy_filter, suf, dim_key):
    return run_query(f"""
        SELECT client_buckets,
               SUM(billed_{suf})        AS billed,
               SUM(collected_net_{suf}) AS collected,
               ROUND(SUM(collected_net_{suf}) / NULLIF(SUM(billed_{suf}), 0), 4) AS efficiency
        FROM finance_unified_txn
        {build_where(fy_filter)}
        GROUP BY client_buckets ORDER BY billed DESC
    """)

with st.spinner("Loading bucket efficiency…"):
    bkt = load_efficiency_bucket(selected_fy, suf, dim_cache_key)

if not bkt.empty:
    cols_bkt = st.columns(len(bkt))
    for i, (_, row) in enumerate(bkt.iterrows()):
        label = row["client_buckets"] or "Unassigned"
        eff   = float(row["efficiency"] or 0)
        color = "#22c55e" if eff >= 0.9 else "#f59e0b" if eff >= 0.7 else "#ef4444"
        with cols_bkt[i]:
            st.markdown(f"""
            <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;
                        padding:16px;text-align:center;">
                <div style="font-size:12px;color:#6b7280;font-weight:500;
                            text-transform:uppercase;margin-bottom:6px;">{label}</div>
                <div style="font-size:22px;font-weight:700;color:{color};margin-bottom:4px;">
                    {eff*100:.1f}%</div>
                <div style="font-size:11px;color:#6b7280;">
                    {fmt(row['billed'], currency, raw=raw_values)} billed</div>
                <div style="font-size:11px;color:#6b7280;">
                    {fmt(row['collected'], currency, raw=raw_values)} collected</div>
            </div>
            """, unsafe_allow_html=True)

st.divider()

# ─────────────────────────────────────────────
# SECTION 7 — CUSTOMER RISK MATRIX (SCATTER)
# ─────────────────────────────────────────────

st.subheader("Customer Risk Matrix")
st.caption(
    "Each dot is a customer. X = billed revenue, Y = collection efficiency. "
    "Dashed lines = medians. Bottom-right quadrant = high billing, low efficiency → priority risk."
)

import plotly.express as px
import plotly.graph_objects as go

@st.cache_data(ttl=300, show_spinner=False)
def load_scatter(fy_filter, suf, dim_key):
    return run_query(f"""
        SELECT
            customer_name,
            COALESCE(client_buckets, 'Unassigned')       AS client_buckets,
            COALESCE(client_journey_stage, 'Unassigned') AS journey_stage,
            COALESCE(subsidiary_name, 'Unassigned')      AS entity,
            SUM(billed_{suf})                            AS billed,
            SUM(collected_net_{suf})                     AS collected,
            ROUND(
                SUM(collected_net_{suf}) /
                NULLIF(SUM(billed_{suf}), 0), 4
            )                                            AS efficiency
        FROM finance_unified_txn
        {build_where(fy_filter)}
          AND customer_name IS NOT NULL
        GROUP BY customer_name, client_buckets,
                 client_journey_stage, subsidiary_name
        HAVING SUM(billed_{suf}) > 0
    """)

with st.spinner("Loading risk matrix…"):
    sc = load_scatter(selected_fy, suf, dim_cache_key)

if not sc.empty:
    # Controls row
    ctrl1, ctrl2, ctrl3 = st.columns([2, 2, 2])
    with ctrl1:
        colour_by = st.selectbox(
            "Colour by",
            ["client_buckets", "journey_stage", "entity"],
            format_func=lambda x: {
                "client_buckets": "Client Bucket",
                "journey_stage":  "Client Journey Stage",
                "entity":         "Billing Entity",
            }[x],
            key="scatter_colour",
        )
    with ctrl2:
        min_billed = st.number_input(
            f"Min billed ({currency})",
            min_value=0,
            value=0,
            step=100_000,
            key="scatter_min",
        )
    with ctrl3:
        show_labels = st.toggle("Show customer names", value=False,
                                key="scatter_labels")

    sc_plot = sc[sc["billed"] >= min_billed].copy()
    sc_plot["efficiency_pct"] = (sc_plot["efficiency"] * 100).round(1)
    sc_plot["billed_fmt"]     = sc_plot["billed"].apply(lambda x: fmt(x, currency, raw=raw_values))
    sc_plot["eff_fmt"]        = sc_plot["efficiency_pct"].apply(lambda x: f"{x:.1f}%")

    COLOUR_MAP = {
        "Issue":             "#ef4444",
        "Non-Issue":         "#22c55e",
        "Churned Account":   "#9ca3af",
        "Unassigned":        "#d1d5db",
        "Customer Success":  "#3b82f6",
        "Implementation":    "#f59e0b",
        "Potential Churn":   "#f97316",
        "Churned":           "#6b7280",
    }

    sym = "₹" if currency == "INR" else "$"

    med_billed = sc_plot["billed"].quantile(0.75)  # top 25% by billing
    med_eff    = 0.8                                # 80% efficiency threshold

    fig = px.scatter(
        sc_plot,
        x="billed",
        y="efficiency",
        color=colour_by,
        hover_name="customer_name",
        custom_data=["billed_fmt", "eff_fmt", "entity"],
        color_discrete_map=COLOUR_MAP,
        title=f"Customer Risk Matrix — {selected_fy}",
        height=550,
    )

    fig.update_traces(
        marker=dict(size=9, opacity=0.75, line=dict(width=0.5, color="white")),
        hovertemplate=(
            "<b>%{hovertext}</b><br>"
            f"Billed: %{{customdata[0]}}<br>"
            "Efficiency: %{customdata[1]}<br>"
            "Entity: %{customdata[2]}<extra></extra>"
        ),
    )

    if show_labels:
        fig.update_traces(
            text=sc_plot["customer_name"],
            textposition="top center",
            textfont=dict(size=9),
            mode="markers+text",
        )

    # Quadrant lines
    x_max = sc_plot["billed"].max() * 1.05
    fig.add_vline(x=med_billed, line_dash="dash",
                  line_color="#94a3b8", opacity=0.6, line_width=1,
                  annotation_text="Top 25% billing",
                  annotation_position="top right",
                  annotation_font=dict(size=10, color="#94a3b8"))
    fig.add_hline(y=med_eff,    line_dash="dash",
                  line_color="#94a3b8", opacity=0.6, line_width=1,
                  annotation_text="80% efficiency",
                  annotation_position="bottom right",
                  annotation_font=dict(size=10, color="#94a3b8"))

    # Quadrant labels — positions relative to the median lines, not y_max
    eff_top = min(sc_plot["efficiency"].max() * 1.02, 1.6)
    eff_bot = 0.02   # just above 0
    for (x, y, txt, anchor) in [
        (x_max * 0.02, eff_top,  "Low billing<br>High efficiency",   "left"),
        (x_max * 0.98, eff_top,  "High billing<br>High efficiency ✓","right"),
        (x_max * 0.02, eff_bot,  "Low billing<br>Low efficiency",     "left"),
        (x_max * 0.98, eff_bot,  "⚠ High billing<br>Low efficiency",  "right"),
    ]:
        fig.add_annotation(
            x=x, y=y, text=txt, showarrow=False,
            font=dict(size=10, color="#94a3b8"),
            xanchor=anchor, yanchor="bottom",
        )

    fig.update_layout(
        xaxis=dict(title=f"Billed Revenue ({sym})", tickformat=".2s"),
        yaxis=dict(title="Collection Efficiency", tickformat=".0%",
                   range=[0, min(sc_plot["efficiency"].max() * 1.1, 1.6)]),
        legend_title=colour_by.replace("_", " ").title(),
        margin=dict(l=10, r=10, t=50, b=10),
        hovermode="closest",
    )

    st.plotly_chart(fig, width='stretch', key="scatter_risk")

    # Summary: bottom-right quadrant customers (risk)
    at_risk = sc_plot[
        (sc_plot["billed"] >= med_billed) &
        (sc_plot["efficiency"] < med_eff)
    ][["customer_name", "entity", "billed_fmt", "eff_fmt", "client_buckets"]]\
        .rename(columns={
            "customer_name": "Customer",
            "entity":        "Entity",
            "billed_fmt":    "Billed",
            "eff_fmt":       "Efficiency",
            "client_buckets":"Bucket",
        })

    if not at_risk.empty:
        with st.expander(f"⚠ At-Risk Customers — high billing, low efficiency ({len(at_risk)})"):
            st.dataframe(at_risk, width='stretch', hide_index=True)
else:
    st.info("No data available for the selected filters.")