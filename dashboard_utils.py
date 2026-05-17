"""
dashboard_utils.py
Shared utilities for all dashboard pages.
No Claude API calls — pure SQL → DataFrame → Streamlit.
"""

from dotenv import load_dotenv
load_dotenv()

import os
import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import create_engine, text
from datetime import date

# ─────────────────────────────────────────────
# DB CONNECTION
# ─────────────────────────────────────────────

@st.cache_resource
def get_engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        st.error("DATABASE_URL not set in environment.")
        st.stop()
    return create_engine(url)


@st.cache_data(ttl=300, show_spinner=False)
def run_query(sql: str) -> pd.DataFrame:
    """Run a SQL query and return a DataFrame. Results cached for 5 minutes."""
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql_query(text(sql), conn)


# ─────────────────────────────────────────────
# FINANCIAL YEAR HELPERS
# ─────────────────────────────────────────────

def get_fy_info() -> dict:
    today = date.today()
    cur_end_year = today.year + 1 if today.month >= 4 else today.year
    current_fy   = f"FY{str(cur_end_year)[-2:]}"
    previous_fy  = f"FY{str(cur_end_year - 1)[-2:]}"
    two_yrs_ago  = f"FY{str(cur_end_year - 2)[-2:]}"
    month_to_q   = {4:1,5:1,6:1,7:2,8:2,9:2,10:3,11:3,12:3,1:4,2:4,3:4}
    cur_q        = month_to_q[today.month]
    current_quarter = f"{current_fy} Q{cur_q}"
    last_quarter    = (f"{previous_fy} Q4" if cur_q == 1
                       else f"{current_fy} Q{cur_q - 1}")
    return {
        "current_fy":       current_fy,
        "previous_fy":      previous_fy,
        "two_years_ago_fy": two_yrs_ago,
        "current_quarter":  current_quarter,
        "last_quarter":     last_quarter,
    }


# ─────────────────────────────────────────────
# NUMBER FORMATTING
# ─────────────────────────────────────────────

def fmt(value, currency="USD", decimals=2):
    """Format a number with dynamic denomination (Bn/Mn/K for USD, Cr/L/K for INR)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    x      = float(value)
    abs_x  = abs(x)
    sym    = "₹" if currency == "INR" else "$"
    if currency == "INR":
        if abs_x >= 10_000_000: return f"{sym}{x/10_000_000:,.{decimals}f} Cr"
        if abs_x >= 100_000:    return f"{sym}{x/100_000:,.{decimals}f} L"
        if abs_x >= 1_000:      return f"{sym}{x/1_000:,.{decimals}f} K"
        return f"{sym}{x:,.0f}"
    else:
        if abs_x >= 1_000_000_000: return f"{sym}{x/1_000_000_000:,.{decimals}f} Bn"
        if abs_x >= 1_000_000:     return f"{sym}{x/1_000_000:,.{decimals}f} Mn"
        if abs_x >= 1_000:         return f"{sym}{x/1_000:,.{decimals}f} K"
        return f"{sym}{x:,.0f}"


def fmt_pct(value, decimals=1):
    """Format a decimal ratio as percentage string. e.g. 0.741 → '74.1%'"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{float(value)*100:.{decimals}f}%"


def fmt_delta(current, previous):
    """
    Returns (delta_str, delta_color) for a vs-prior-year comparison.
    e.g. current=102, previous=65 → ('+56.9%', 'green')
    """
    if not previous or previous == 0:
        return "—", "gray"
    delta = (current - previous) / abs(previous)
    sign  = "▲" if delta >= 0 else "▼"
    color = "green" if delta >= 0 else "red"
    return f"{sign} {abs(delta)*100:.1f}%", color


# ─────────────────────────────────────────────
# KPI CARD RENDERER
# ─────────────────────────────────────────────

def render_kpi_card(title: str, value, previous=None,
                    currency="USD", vs_label="vs prior year"):
    """
    Renders a single KPI metric card with:
      - Title
      - Large formatted value
      - Optional % delta vs prior period with colour
    """
    delta_str, delta_color = ("—", "gray")
    if previous is not None:
        delta_str, delta_color = fmt_delta(float(value), float(previous))

    color_map = {"green": "#22c55e", "red": "#ef4444", "gray": "#9ca3af"}
    color_hex  = color_map.get(delta_color, "#9ca3af")

    st.markdown(f"""
    <div style="
        background:#ffffff;
        border:1px solid #e5e7eb;
        border-radius:10px;
        padding:16px 20px;
        height:100%;
    ">
        <div style="font-size:12px;color:#6b7280;font-weight:500;
                    text-transform:uppercase;letter-spacing:0.05em;
                    margin-bottom:6px;">{title}</div>
        <div style="font-size:26px;font-weight:700;color:#111827;
                    margin-bottom:4px;">{fmt(value, currency)}</div>
        <div style="font-size:13px;color:{color_hex};font-weight:600;">
            {delta_str}
            <span style="color:#9ca3af;font-weight:400;"> {vs_label}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# TABLE RENDERER
# ─────────────────────────────────────────────

def render_dashboard_table(df: pd.DataFrame, title: str,
                           currency="USD", pct_cols: list = None,
                           amount_cols: list = None):
    """
    Renders a formatted table with a section title.
    pct_cols:    column names to format as percentages
    amount_cols: column names to format as currency amounts
    """
    if df.empty:
        st.info(f"{title} — no data.")
        return

    st.markdown(f"#### {title}")
    df = df.copy()

    for col in (pct_cols or []):
        if col in df.columns:
            df[col] = df[col].apply(
                lambda x: fmt_pct(x) if pd.notnull(x) and x != "" else x
            )
    for col in (amount_cols or []):
        if col in df.columns:
            df[col] = df[col].apply(
                lambda x: fmt(x, currency) if pd.notnull(x) and x != "" else x
            )

    st.dataframe(df, width='stretch', hide_index=True)


# ─────────────────────────────────────────────
# CHART RENDERER
# ─────────────────────────────────────────────

def render_bar_chart(df: pd.DataFrame, x_col: str, y_col: str,
                     title: str, currency="USD",
                     horizontal=False, height=400):
    """Simple bar chart for dashboard panels."""
    if df.empty:
        st.info("No data.")
        return
    sym = "₹" if currency == "INR" else "$"
    tick_fmt = ",.0f" if False else ".2s"   # always abbreviated on charts
    if horizontal:
        fig = px.bar(df.sort_values(y_col, ascending=True),
                     x=y_col, y=x_col, orientation="h",
                     title=title, height=height,
                     color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_layout(xaxis=dict(tickformat=tick_fmt,
                                     title=f"Amount ({sym})"), yaxis_title="")
    else:
        fig = px.bar(df, x=x_col, y=y_col, title=title, height=height,
                     color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_layout(xaxis_title="",
                          yaxis=dict(tickformat=tick_fmt, title=f"Amount ({sym})"))
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, width='stretch', key=f"chart_{title.replace(' ','_')}")


def render_line_chart(df: pd.DataFrame, x_col: str, y_cols: list,
                      title: str, currency="USD", height=350):
    """Line chart for trend panels."""
    if df.empty:
        st.info("No data.")
        return
    sym = "₹" if currency == "INR" else "$"
    fig = px.line(df, x=x_col, y=y_cols, title=title,
                  markers=True, height=height,
                  color_discrete_sequence=px.colors.qualitative.Set2)
    fig.update_layout(
        xaxis_title="", hovermode="x unified",
        yaxis=dict(tickformat=".2s", title=f"Amount ({sym})"),
        legend_title="Metric",
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(fig, width='stretch', key=f"chart_{title.replace(' ','_')}")