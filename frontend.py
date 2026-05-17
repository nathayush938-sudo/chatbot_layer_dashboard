import streamlit as st
import requests
import pandas as pd

try:
    import plotly.express as px
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

st.set_page_config(
    page_title="Finance AI Chatbot",
    layout="wide"
)

st.title("Finance AI Chatbot")

# ── Session state initialisation ─────────────────────────────────────────────
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []   # API context: [{"user":..,"assistant":..}]
if "exchanges" not in st.session_state:
    st.session_state.exchanges = []      # Display: list of rendered exchange dicts
if "raw_values" not in st.session_state:
    st.session_state.raw_values = False

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Display Settings")

    st.session_state.raw_values = st.toggle(
        "Show raw values",
        value=st.session_state.raw_values,
        help="USD: $1.23 Mn / $1.23 K  |  INR: ₹1.23 Cr / ₹1.23 L / ₹1.23 K"
    )
    if st.session_state.raw_values:
        st.caption("Showing full unformatted numbers")
    else:
        st.caption("USD: Bn / Mn / K  |  INR: Cr / L / K")

    st.divider()
    if st.button("🗑️ Clear conversation", width='stretch'):
        st.session_state.exchanges    = []
        st.session_state.chat_history = []
        st.rerun()

BACKEND_URL = "http://127.0.0.1:8000/chat"


def get_currency_symbol(currency):
    currency = (currency or "").upper()
    if currency == "USD":
        return "$"
    elif currency == "INR":
        return "₹"
    elif currency == "EUR":
        return "€"
    return ""


def format_currency_value(x, currency, decimals=2):
    """
    Formats a numeric value with dynamic denomination based on magnitude.

    Raw mode (toggle on):  full number with thousand separators, no symbol.

    Formatted mode (default):
      USD / other : Bn → Mn → K → raw
        >= 1,000,000,000  →  $1.23 Bn
        >= 1,000,000      →  $1.23 Mn
        >= 1,000          →  $1.23 K
        < 1,000           →  $123

      INR : Cr → L → K → raw  (standard Indian financial notation)
        >= 10,000,000     →  ₹1.23 Cr   (crore)
        >= 100,000        →  ₹1.23 L    (lakh)
        >= 1,000          →  ₹1.23 K
        < 1,000           →  ₹123
    """
    if not isinstance(x, (int, float)) or not pd.notnull(x):
        return ""

    if st.session_state.get("raw_values", False):
        return f"{x:,.0f}"

    symbol   = get_currency_symbol(currency)
    currency = (currency or "").upper()
    abs_x    = abs(x)

    if currency == "INR":
        if abs_x >= 10_000_000:
            return f"{symbol}{x / 10_000_000:,.{decimals}f} Cr"
        if abs_x >= 100_000:
            return f"{symbol}{x / 100_000:,.{decimals}f} L"
        if abs_x >= 1_000:
            return f"{symbol}{x / 1_000:,.{decimals}f} K"
        return f"{symbol}{x:,.0f}"
    else:
        if abs_x >= 1_000_000_000:
            return f"{symbol}{x / 1_000_000_000:,.{decimals}f} Bn"
        if abs_x >= 1_000_000:
            return f"{symbol}{x / 1_000_000:,.{decimals}f} Mn"
        if abs_x >= 1_000:
            return f"{symbol}{x / 1_000:,.{decimals}f} K"
        return f"{symbol}{x:,.0f}"


QUARTER_SORT_KEYWORDS = ["quarter", "fy", "month", "year", "date", "period", "annual"]

AGEING_ORDER = [
    'Within CP', '1-15 days', '16-30 days', '31-45 days',
    '46-60 days', '61-90 days', '>90 days'
]

AR_AGEING_ORDER = [
    'Current', '1-30 days', '31-60 days',
    '61-90 days', '91-180 days', '>180 days'
]

# Combined order for detection across both collections and AR
ALL_AGEING_VALUES = set(AGEING_ORDER + AR_AGEING_ORDER)

def is_id_column(col):
    """Returns True if column looks like an internal ID (should go last / not be summed)."""
    c = col.lower()
    return c.endswith("_id") or c == "id" or c.endswith(" id")


def strip_currency_suffix(name):
    """Remove redundant currency labels from column headers."""
    for suffix in [" (USD)", " (INR)", " (usd)", " (inr)", " (Usd)", " (Inr)"]:
        name = name.replace(suffix, "")
    return name.strip()


def deduplicate_column_map(column_map: dict) -> dict:
    """
    If two SQL columns map to the same display name, append (INR) / (USD)
    based on the column suffix so df.rename() never produces duplicate headers.
    Works on both Claude-supplied and auto-generated display names.
    """
    name_counts: dict[str, int] = {}
    for name in column_map.values():
        name_counts[name] = name_counts.get(name, 0) + 1

    result = {}
    for col, name in column_map.items():
        if name_counts[name] > 1:
            if col.endswith("_inr"):
                result[col] = f"{name} (INR)"
            elif col.endswith("_usd"):
                result[col] = f"{name} (USD)"
            else:
                result[col] = f"{name} ({col})"
        else:
            result[col] = name
    return result


def format_date_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detects string columns containing dates and formats them for display:
      - All date values are 1st of month  → "Apr 2025"  (monthly grouping)
      - Other date values                  → "01 Apr 2025"
    Non-date values in the same column (e.g. "Grand Total") are left untouched.
    """
    DATE_RE = r'^\d{4}-\d{2}-\d{2}$'
    IGNORE  = {'', 'grand total', 'Grand Total'}

    for col in df.columns:
        if not (pd.api.types.is_object_dtype(df[col]) or
                pd.api.types.is_string_dtype(df[col])):
            continue

        str_vals = df[col].fillna('').astype(str)
        date_mask = str_vals.str.match(DATE_RE)

        # Must have at least one date; all non-empty, non-label values must be dates
        date_vals = str_vals[date_mask]
        non_date  = str_vals[~date_mask & ~str_vals.isin(IGNORE)]
        if date_vals.empty or not non_date.empty:
            continue

        try:
            parsed = pd.to_datetime(date_vals, errors='coerce').dropna()
            if parsed.empty:
                continue
            fmt = '%b %Y' if (parsed.dt.day == 1).all() else '%d %b %Y'
            # Only reformat the cells that are date strings; leave labels as-is
            full_parsed = pd.to_datetime(df[col], errors='coerce')
            df = df.copy()
            df.loc[date_mask, col] = full_parsed[date_mask].dt.strftime(fmt)
        except Exception:
            pass

    return df

def is_time_column(col):
    """Returns True if column looks like a time/period dimension."""
    col_lower = col.lower()
    return any(kw in col_lower for kw in QUARTER_SORT_KEYWORDS)

def is_metric_column(col):
    col_lower = col.lower()
    # Exclude known dimension column names even if they contain metric keywords
    # e.g. "Billing Entity", "Collection Status", "Client Bucket"
    dimension_exclusions = ["entity", "status", "bucket", "journey", "region",
                            "currency", "country", "subsidiary"]
    if any(pat in col_lower for pat in dimension_exclusions):
        return False
    return any(word in col_lower for word in [
        "amount", "revenue", "billing", "billed", "tax", "fee", "total",
        "collection", "receipt", "outstanding", "overdue"
    ])


def reorder_columns(df):
    cols = df.columns.tolist()

    # "Row %" is a single-metric companion — handled separately at the end.
    # Named pct cols (e.g. "Outstanding %", "Overdue %") must be interleaved
    # immediately after their matching metric column.
    row_pct_cols   = [c for c in cols if c == "Row %"]
    named_pct_cols = [c for c in cols if c.endswith(" %") and c != "Row %"]
    all_pct_cols   = set(row_pct_cols + named_pct_cols)

    id_cols = [
        c for c in cols
        if "id" in c.lower()
        and c not in all_pct_cols
    ]

    name_cols = [
        c for c in cols
        if "name" in c.lower()
        and c not in id_cols
        and c not in all_pct_cols
    ]

    total_cols = [c for c in cols if c == "Total"]

    metric_cols = [
        c for c in cols
        if is_metric_column(c)
        and c not in id_cols
        and c not in name_cols
        and c not in total_cols
        and c not in all_pct_cols
    ]

    # Interleave each metric with its named pct partner (if one exists).
    # Match rule: the keyword in "X %" (e.g. "outstanding" from "Outstanding %")
    # must appear somewhere in the metric column name (e.g. "Amount Outstanding").
    interleaved_metrics = []
    used_pct = set()
    for metric in metric_cols:
        interleaved_metrics.append(metric)
        for pct in named_pct_cols:
            if pct in used_pct:
                continue
            keyword = pct.replace(" %", "").strip().lower()
            if keyword in metric.lower():
                interleaved_metrics.append(pct)
                used_pct.add(pct)
                break

    # Any unmatched named pct cols go after all metrics
    for pct in named_pct_cols:
        if pct not in used_pct:
            interleaved_metrics.append(pct)

    used = set(id_cols + name_cols + interleaved_metrics + total_cols + row_pct_cols)
    other_cols = [c for c in cols if c not in used]

    # Final order: dims | other | metric+pct pairs | Row % | Total
    ordered_cols = (
        id_cols
        + name_cols
        + other_cols
        + interleaved_metrics
        + row_pct_cols
        + total_cols
    )

    return df[ordered_cols]


def apply_detail_formatting(df, metadata):
    """
    Formats a detail/drilldown table (individual rows, no GROUP BY).
    Works with SELECT * — auto-detects and formats amount columns.
    Column order: non-IDs in SQL order, IDs last.
    No Row %, no Grand Total.
    """
    display    = metadata.get("display", {})
    column_map = deduplicate_column_map(
                    {k: strip_currency_suffix(v)
                     for k, v in display.get("columns", {}).items()})
    currency   = display.get("currency", "INR")
    formatting = display.get("formatting", {})

    df = df.rename(columns=column_map)
    df = format_date_columns(df)

    # Apply explicit formatting from metadata
    for original_col, rule in formatting.items():
        mapped_col = strip_currency_suffix(column_map.get(original_col, original_col))
        if mapped_col not in df.columns:
            continue
        if rule.get("type") == "currency":
            df[mapped_col] = df[mapped_col].apply(
                lambda x: format_currency_value(x, currency)
            )
        elif rule.get("type") == "percentage":
            decimals = rule.get("decimals", 1)
            df[mapped_col] = df[mapped_col].apply(
                lambda x: f"{x:.{decimals}%}"
                if isinstance(x, (int, float)) and pd.notnull(x) else ""
            )

    # Auto-format numeric columns not already formatted by metadata
    # Amount/fee columns → format as currency; exchange rate cols → round to 4dp
    formatted_cols = {strip_currency_suffix(column_map.get(c, c)) for c in formatting}
    amount_keywords = ["amount", "fee", "billing_amount", "collection_amount",
                       "open_amount", "transaction_amount", "tax"]
    rate_keywords   = ["exchangerate", "exchange_rate"]

    for col in df.columns:
        if col in formatted_cols:
            continue
        col_lower = col.lower()
        if any(k in col_lower for k in amount_keywords):
            if pd.api.types.is_numeric_dtype(df[col]):
                df[col] = df[col].apply(
                    lambda x: format_currency_value(x, currency)
                )
        elif any(k in col_lower for k in rate_keywords):
            if pd.api.types.is_numeric_dtype(df[col]):
                df[col] = df[col].apply(
                    lambda x: f"{x:.4f}" if isinstance(x, (int, float)) and pd.notnull(x) else ""
                )

    # IDs last — keep everything else in SQL column order
    cols    = df.columns.tolist()
    id_cols = [c for c in cols if is_id_column(c)]
    non_ids = [c for c in cols if c not in id_cols]
    df = df[non_ids + id_cols]

    return df


def apply_display_formatting(df, metadata):
    display = metadata.get("display", {})
    column_map = display.get("columns", {})
    formatting = display.get("formatting", {})

    numeric_cols = df.select_dtypes(include="number").columns.tolist()

    metric_candidates = [
        col for col in numeric_cols
        if is_metric_column(col)
    ]

    if metric_candidates:
        # Primary sort column — prefer "outstanding", then "total", then last metric
        sort_col = next(
            (c for c in metric_candidates if "outstanding" in c.lower()),
            next((c for c in metric_candidates if "total" in c.lower()),
                 metric_candidates[-1])
        )

        # Detect dual-metric: both outstanding and overdue present
        outstanding_col = next((c for c in metric_candidates if "outstanding" in c.lower()), None)
        overdue_col     = next((c for c in metric_candidates if "overdue" in c.lower()), None)

        if outstanding_col and overdue_col and pd.api.types.is_numeric_dtype(df[outstanding_col]):
            # Add Outstanding % and Overdue % columns (each as % of their own grand total)
            total_outstanding = df[outstanding_col].sum()
            total_overdue     = df[overdue_col].sum()
            df["Outstanding %"] = df[outstanding_col].apply(
                lambda x: x / total_outstanding
                if isinstance(x, (int, float)) and pd.notnull(x) and total_outstanding else 0
            )
            df["Overdue %"] = df[overdue_col].apply(
                lambda x: x / total_overdue
                if isinstance(x, (int, float)) and pd.notnull(x) and total_overdue else 0
            )
            formatting["Outstanding %"] = {"type": "percentage", "decimals": 0}
            formatting["Overdue %"]     = {"type": "percentage", "decimals": 0}

        # Row % only makes sense for single-metric tables
        if len(metric_candidates) == 1:
            value_col   = metric_candidates[0]
            total_value = df[value_col].sum()
            df["Row %"] = df[value_col].apply(
                lambda x: x / total_value if (isinstance(x, (int, float)) and total_value) else 0
            )
            formatting["Row %"] = {"type": "percentage", "decimals": 1}
            sort_col = value_col

        # Sort: ageing order → chronological ASC → value DESC
        dim_cols = [c for c in df.columns if not is_metric_column(c) and c != "Row %"]
        if dim_cols:
            sample_vals = df[dim_cols[0]].astype(str).tolist()
            is_ageing   = any(v in ALL_AGEING_VALUES for v in sample_vals)
            if is_ageing:
                active_order = AR_AGEING_ORDER if any(v in AR_AGEING_ORDER for v in sample_vals) else AGEING_ORDER
                order_map   = {v: i for i, v in enumerate(active_order)}
                df["_sort"] = df[dim_cols[0]].map(lambda x: order_map.get(x, len(AGEING_ORDER)))
                df = df.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)
            elif is_time_column(dim_cols[0]):
                df = df.sort_values(by=dim_cols[0], ascending=True).reset_index(drop=True)
            else:
                df = df.sort_values(by=sort_col, ascending=False).reset_index(drop=True)
        else:
            df = df.sort_values(by=sort_col, ascending=False).reset_index(drop=True)

        # Grand Total row
        # Ratio columns (overdue as % of outstanding) can't be summed
        ratio_cols = [c for c in df.columns
                      if "pct_of" in c.lower() or "as % of" in c.lower()]

        if len(df) > 1:
            # Named pct cols (e.g. "Outstanding %", "Overdue %") represent each
            # row's share of the total — grand total is always 100% (= 1.0).
            named_pct_set = {c for c in df.columns if c.endswith(" %") and c != "Row %"}

            grand_row = {}
            for col in df.columns:
                if col == "Row %" or col in named_pct_set:
                    grand_row[col] = 1.0
                elif is_id_column(col) or col in ratio_cols:
                    grand_row[col] = ""   # never sum IDs or ratios
                elif pd.api.types.is_numeric_dtype(df[col]):
                    grand_row[col] = df[col].sum()
                else:
                    grand_row[col] = "Grand Total" if col == df.columns[0] else ""
            df = pd.concat([df, pd.DataFrame([grand_row])], ignore_index=True)

    for original_col, rule in formatting.items():
        if original_col in df.columns:
            if rule.get("type") == "currency":
                currency = rule.get("currency", display.get("currency", ""))
                df[original_col] = df[original_col].apply(
                    lambda x: format_currency_value(x, currency)
                )

            elif rule.get("type") == "percentage":
                decimals = rule.get("decimals", 1)

                df[original_col] = df[original_col].apply(
                    lambda x: f"{x:.{decimals}%}"
                    if isinstance(x, (int, float)) and pd.notnull(x) else ""
                )

    clean_map = deduplicate_column_map({k: strip_currency_suffix(v) for k, v in column_map.items()})
    df = df.rename(columns=clean_map)
    df = format_date_columns(df)
    df = reorder_columns(df)

    return df


def add_pivot_totals_and_sort(pivot_df, row_cols):
    numeric_cols = pivot_df.select_dtypes(include="number").columns.tolist()

    pivot_df = pivot_df.copy()
    pivot_df["Total"] = pivot_df[numeric_cols].sum(axis=1)

    grand_total_value = pivot_df["Total"].sum()
    pivot_df["Row %"] = pivot_df["Total"].apply(
        lambda x: x / grand_total_value if grand_total_value else 0
    )

    # Sort: ageing order → chronological → value DESC
    if row_cols:
        sample_vals = pivot_df[row_cols[0]].astype(str).tolist()
        is_ageing_rows = any(v in ALL_AGEING_VALUES for v in sample_vals)

        if is_ageing_rows:
            # Pick the right order list based on which values are present
            active_order = AR_AGEING_ORDER if any(v in AR_AGEING_ORDER for v in sample_vals) else AGEING_ORDER
            order_map  = {v: i for i, v in enumerate(active_order)}
            pivot_df   = pivot_df.copy()
            pivot_df["_sort"] = pivot_df[row_cols[0]].map(
                lambda x: order_map.get(x, len(AGEING_ORDER))
            )
            pivot_df = pivot_df.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)
        elif is_time_column(row_cols[0]):
            pivot_df = pivot_df.sort_values(by=row_cols[0], ascending=True).reset_index(drop=True)
        else:
            pivot_df = pivot_df.sort_values(by="Total", ascending=False).reset_index(drop=True)

    # Build Grand Total row and append via pd.concat (avoids index corruption)
    grand_total = {}
    for col in pivot_df.columns:
        if col in row_cols:
            grand_total[col] = "Grand Total"
        elif col == "Row %":
            grand_total[col] = 1.0
        elif pd.api.types.is_numeric_dtype(pivot_df[col]):
            grand_total[col] = pivot_df[col].sum()
        else:
            grand_total[col] = ""

    pivot_df = pd.concat(
        [pivot_df, pd.DataFrame([grand_total])],
        ignore_index=True
    )

    return pivot_df


def format_pivot_values(pivot_df, metadata, row_cols):
    display  = metadata.get("display", {})
    currency = display.get("currency", "USD")

    # ── Format values ────────────────────────────────────────────────────
    for col in pivot_df.columns:
        if col == "Row %":
            pivot_df[col] = pivot_df[col].apply(
                lambda x: f"{x:.1%}" if pd.notnull(x) else ""
            )
        elif col not in row_cols:
            pivot_df[col] = pivot_df[col].apply(
                lambda x: format_currency_value(x, currency)
            )

    # ── Column order: row dim(s) | Row % | value cols | Total ────────────
    special    = set(row_cols + ["Row %", "Total"])
    value_cols = [c for c in pivot_df.columns if c not in special]

    # Enforce ageing bucket order when applicable
    ageing_in_vals = [c for c in AGEING_ORDER if c in value_cols]
    ar_ageing_in_vals = [c for c in AR_AGEING_ORDER if c in value_cols]
    if ar_ageing_in_vals:
        other_vals = [c for c in value_cols if c not in AR_AGEING_ORDER]
        value_cols = ar_ageing_in_vals + other_vals
    elif ageing_in_vals:
        other_vals = [c for c in value_cols if c not in AGEING_ORDER]
        value_cols = ageing_in_vals + other_vals

    row_pct   = ["Row %"] if "Row %" in pivot_df.columns else []
    total_col = ["Total"] if "Total" in pivot_df.columns else []
    ordered   = row_cols + row_pct + value_cols + total_col
    pivot_df  = pivot_df[[c for c in ordered if c in pivot_df.columns]]

    return pivot_df



def apply_metric_pivot_formatting(df, metadata):
    """
    Two display modes depending on whether a row dimension exists:

    A) No dimension (overall split, e.g. "invoice type split"):
       Transposes to: Invoice Type | Amount | Percentage
       Sorted by Amount DESC with a Grand Total row.

    B) With dimension (e.g. "region and invoice type split"):
       dimension(s) | Row % | metric cols | Total
       Sorted by Total DESC with a Grand Total row.
    """
    display         = metadata.get("display", {})
    column_map      = display.get("columns", {})
    currency        = display.get("currency", "USD")
    symbol          = get_currency_symbol(currency)
    row_dims        = metadata.get("rows", [])
    metric_cols_raw = metadata.get("metric_columns", [])

    # Rename SQL aliases to display names (strip currency suffix from headers)
    column_map = deduplicate_column_map({k: strip_currency_suffix(v) for k, v in column_map.items()})
    df = df.rename(columns=column_map)
    renamed_rows    = [column_map.get(r, r) for r in row_dims]
    renamed_metrics = [column_map.get(m, m) for m in metric_cols_raw]
    existing_metrics = [c for c in renamed_metrics if c in df.columns]

    # ── MODE A: no grouping dimension → transpose ──────────────────────────
    if not renamed_rows or all(r not in df.columns for r in renamed_rows):
        # Aggregate each metric across all rows (handles the single-row case too)
        totals = {col: df[col].sum() for col in existing_metrics if col in df.columns}
        grand_total = sum(totals.values())

        rows = []
        for metric_name, amount in totals.items():
            # Strip redundant currency suffix — symbol already shows currency
            clean_name = metric_name.replace(" (USD)", "").replace(" (INR)", "").replace(" (usd)", "").replace(" (inr)", "")
            rows.append({
                "Invoice Type": clean_name,
                "Amount":       amount,
                "Percentage":   amount / grand_total if grand_total else 0,
            })

        result_df = pd.DataFrame(rows)

        # Sort by Amount DESC
        result_df = result_df.sort_values(by="Amount", ascending=False).reset_index(drop=True)

        # Append Grand Total row
        result_df.loc[len(result_df)] = {
            "Invoice Type": "Grand Total",
            "Amount":       grand_total,
            "Percentage":   1.0,
        }

        # Format
        result_df["Amount"] = result_df["Amount"].apply(
            lambda x: format_currency_value(x, currency)
        )
        result_df["Percentage"] = result_df["Percentage"].apply(
            lambda x: f"{x:.1%}"
            if isinstance(x, (int, float)) and pd.notnull(x) else ""
        )

        return result_df

    # ── MODE B: has grouping dimension → wide table ────────────────────────
    # Compute Total and Row % as numeric before formatting
    df["Total"]  = df[existing_metrics].sum(axis=1)
    grand_total  = df["Total"].sum()
    df["Row %"]  = df["Total"].apply(
        lambda x: x / grand_total if grand_total else 0
    )

    # Sort: chronological for time dimensions, by Total DESC otherwise
    if renamed_rows and is_time_column(renamed_rows[0]):
        df = df.sort_values(by=renamed_rows[0], ascending=True).reset_index(drop=True)
    else:
        df = df.sort_values(by="Total", ascending=False).reset_index(drop=True)

    # Grand Total row
    grand_row = {}
    for col in df.columns:
        if col in renamed_rows:
            grand_row[col] = "Grand Total"
        elif col == "Row %":
            grand_row[col] = 1.0
        elif pd.api.types.is_numeric_dtype(df[col]):
            grand_row[col] = df[col].sum()
        else:
            grand_row[col] = ""
    df.loc[len(df)] = grand_row

    # Format Row %
    df["Row %"] = df["Row %"].apply(
        lambda x: f"{x:.1%}"
        if isinstance(x, (int, float)) and pd.notnull(x) else ""
    )

    # Format metric columns and Total
    for col in existing_metrics + ["Total"]:
        if col in df.columns:
            df[col] = df[col].apply(
                lambda x: format_currency_value(x, currency)
            )

    # Column order: dimension(s) | Row % | metrics | Total
    ordered   = renamed_rows + ["Row %"] + existing_metrics + ["Total"]
    remaining = [c for c in df.columns if c not in ordered]
    df = df[ordered + remaining]

    # Combined header: "Region ↓  |  Revenue Type →"
    # Derive column label from metric column names
    if renamed_rows:
        sample_metrics = [m.lower() for m in existing_metrics]
        if any(w in " ".join(sample_metrics) for w in ["revenue", "subscription", "implementation", "collection", "amount"]):
            col_label = "Revenue Type →" if any("revenue" in m or "subscription" in m for m in sample_metrics) else "Type →"
        else:
            col_label = "Type →"
        row_label      = renamed_rows[0]
        combined       = f"{row_label} ↓  |  {col_label}"
        df             = df.rename(columns={row_label: combined})

    return df



def apply_ageing_pivot_formatting(pivot_df, metadata, row_cols):
    """
    Cumulative ageing pivot:
    For each dimension row (e.g. quarter), renders two rows:
      1. Collection amounts per ageing bucket  +  Row Total  +  Row %
      2. Cumulative % sub-row (running % across buckets)
    Followed by Grand Total + Total (Cumulative %) rows.
    """
    display  = metadata.get("display", {})
    currency = display.get("currency", "INR")
    row_dim  = row_cols[0] if row_cols else pivot_df.columns[0]

    # Only include buckets that actually exist in data, in logical order
    # Auto-detect which ageing order applies
    if any(c in AR_AGEING_ORDER for c in pivot_df.columns):
        active_ageing_order = AR_AGEING_ORDER
    else:
        active_ageing_order = AGEING_ORDER
    ageing_cols = [c for c in active_ageing_order if c in pivot_df.columns]

    # Numeric row total for sorting
    pivot_df = pivot_df.copy()
    pivot_df['_row_total'] = pivot_df[ageing_cols].sum(axis=1)

    if is_time_column(row_dim):
        pivot_df = pivot_df.sort_values(by=row_dim, ascending=True).reset_index(drop=True)
    else:
        pivot_df = pivot_df.sort_values(by='_row_total', ascending=False).reset_index(drop=True)

    grand_total = pivot_df['_row_total'].sum()
    result_rows = []

    for _, row in pivot_df.iterrows():
        row_total = float(row['_row_total'])
        row_pct   = row_total / grand_total if grand_total else 0

        # ── Amount row ──────────────────────────────────────────────────
        amt = {row_dim: str(row[row_dim])}
        for col in ageing_cols:
            amt[col] = format_currency_value(float(row[col]), currency)
        amt['Row Total'] = format_currency_value(row_total, currency)
        amt['Row %']     = f"**{row_pct:.1%}**"   # bold for emphasis
        result_rows.append(amt)

        # ── Cumulative % sub-row ────────────────────────────────────────
        cum = {row_dim: f"{row[row_dim]} (Cumulative %)"}
        running = 0.0
        for col in ageing_cols:
            running += float(row[col]) if isinstance(row[col], (int, float)) else 0
            cum[col] = f"{running / row_total:.1%}" if row_total else "0.0%"
        cum['Row Total'] = "100.0%"
        cum['Row %']     = ""
        result_rows.append(cum)

    # ── Grand Total row ─────────────────────────────────────────────────
    gt = {row_dim: 'Grand Total'}
    gt_cum = {row_dim: 'Total (Cumulative %)'}
    running_gt = 0.0
    for col in ageing_cols:
        col_sum     = float(pivot_df[col].sum())
        gt[col]     = format_currency_value(col_sum, currency)
        running_gt += col_sum
        gt_cum[col] = f"{running_gt / grand_total:.1%}" if grand_total else "0.0%"
    gt['Row Total']     = format_currency_value(grand_total, currency)
    gt['Row %']         = "**100.0%**"
    gt_cum['Row Total'] = "100.0%"
    gt_cum['Row %']     = ""
    result_rows.extend([gt, gt_cum])

    result_df = pd.DataFrame(result_rows)

    # Final column order
    col_order = [row_dim] + ageing_cols + ['Row Total', 'Row %']
    result_df = result_df[[c for c in col_order if c in result_df.columns]]
    result_df = result_df.fillna("")

    return result_df


user_input = st.chat_input("Ask something")

def render_exchange(exchange, idx: int = 0):
    """Re-render a stored exchange (user + assistant response). Pure display — no state mutation."""
    with st.chat_message("user"):
        st.write(exchange["user_input"])

    if exchange.get("error"):
        with st.chat_message("assistant"):
            st.warning(exchange["error"])
        return

    result   = exchange["result"]
    metadata = result["metadata"]
    data     = result["data"]
    df       = pd.DataFrame(data)

    with st.chat_message("assistant"):
        display     = metadata.get("display", {})
        title       = display.get("title")
        explanation = metadata.get("explanation", "")

        if title:       st.subheader(title)
        if explanation: st.write(explanation)

        with st.expander("Generated SQL"):
            st.code(metadata.get("sql", ""), language="sql")

        render_result(df, metadata, result, view_key=f"exchange_{idx}")

        with st.expander("Token usage"):
            st.json(result.get("usage", {}))


def render_chart(df, metadata, view_key: str = "default"):
    """
    Render a Plotly chart from the raw (unformatted) DataFrame.
    Falls back to the table view if plotly is not installed.
    Respects st.session_state.raw_values for number formatting.
    """
    if not PLOTLY_AVAILABLE:
        st.warning("Plotly is not installed. Run `pip install plotly` to enable charts.")
        render_result(df, metadata, {}, view_key=view_key)
        return

    viz          = metadata.get("visualization", "table")
    pivot_type   = metadata.get("pivot_type", "metric")
    display      = metadata.get("display", {})
    currency     = display.get("currency", "USD")
    symbol       = get_currency_symbol(currency)
    title        = display.get("title", "")
    col_map      = {k: strip_currency_suffix(v)
                    for k, v in display.get("columns", {}).items()}

    df_chart     = df.rename(columns=col_map)
    numeric_cols = df_chart.select_dtypes(include="number").columns.tolist()
    string_cols  = df_chart.select_dtypes(include=["object", "str"]).columns.tolist()

    raw_values    = st.session_state.get("raw_values", False)
    PLOTLY_COLORS = px.colors.qualitative.Set2
    tick_fmt      = ",.0f" if raw_values else ".2s"
    label_fmt     = ",.0f" if raw_values else ".2s"

    # ── LINE CHART ────────────────────────────────────────────────────────────
    if viz == "line_chart":
        dim_col = string_cols[0] if string_cols else None
        if not dim_col or not numeric_cols:
            st.info("Not enough data to draw a chart.")
            return
        if is_time_column(dim_col):
            df_chart = df_chart.sort_values(dim_col, ascending=True).reset_index(drop=True)
        fig = px.line(
            df_chart, x=dim_col, y=numeric_cols,
            title=title, markers=True, color_discrete_sequence=PLOTLY_COLORS,
            height=400,
        )
        fig.update_layout(
            xaxis_title="", yaxis_title=f"Amount ({symbol})",
            legend_title="Metric", hovermode="x unified",
            yaxis=dict(tickformat=tick_fmt),
        )
        fig.update_traces(hovertemplate=f"%{{y:{tick_fmt}}}")
        st.plotly_chart(fig, width='stretch', key=f"chart_{view_key}_{id(fig)}")

    # ── BAR CHART ─────────────────────────────────────────────────────────────
    elif viz == "bar_chart":
        dim_col     = string_cols[0] if string_cols else None
        metric_list = [c for c in numeric_cols if c in df_chart.columns]
        if not dim_col or not metric_list:
            st.info("Not enough data to draw a chart.")
            return

        is_horizontal = any(kw in dim_col.lower()
                            for kw in ["customer", "account", "name"])

        if is_horizontal:
            # Top-N selector — only show when there are more rows than the minimum
            n_options  = [n for n in [10, 20, 50] if n < len(df_chart)] + ["All"]
            if len(n_options) > 1:
                sel = st.radio(
                    "Show top",
                    options=n_options,
                    index=0,
                    horizontal=True,
                    key=f"topn_{view_key}",
                )
                n_rows = len(df_chart) if sel == "All" else int(sel)
            else:
                n_rows = len(df_chart)

            plot_df = df_chart[[dim_col] + metric_list] \
                          .sort_values(metric_list[0], ascending=False) \
                          .head(n_rows) \
                          .sort_values(metric_list[0], ascending=True)  # flip for horizontal display

            chart_height = max(350, n_rows * 35 + 80)

            fig = px.bar(
                plot_df, x=metric_list[0], y=dim_col, orientation="h",
                title=title, color_discrete_sequence=PLOTLY_COLORS,
                text=plot_df[metric_list[0]].apply(lambda v: format_currency_value(v, currency)),
                height=chart_height,
            )
            fig.update_layout(
                xaxis=dict(title=f"Amount ({symbol})", tickformat=tick_fmt),
                yaxis_title="",
                margin=dict(l=10, r=10, t=40, b=10),
            )
            fig.update_traces(textposition="outside", cliponaxis=False)
        else:
            n_rows = len(df_chart)
            chart_height = max(350, min(600, n_rows * 45 + 80))

            # Sort by time dimension so quarters/dates appear in order
            if is_time_column(dim_col):
                df_chart = df_chart.sort_values(dim_col, ascending=True).reset_index(drop=True)

            if len(metric_list) > 1:
                fig = px.bar(
                    df_chart, x=dim_col, y=metric_list, barmode="group",
                    title=title, color_discrete_sequence=PLOTLY_COLORS,
                    height=chart_height,
                )
            else:
                fig = px.bar(
                    df_chart, x=dim_col, y=metric_list[0],
                    title=title, color_discrete_sequence=PLOTLY_COLORS,
                    text=df_chart[metric_list[0]].apply(lambda v: format_currency_value(v, currency)),
                    height=chart_height,
                )
            fig.update_layout(
                xaxis_title="",
                yaxis=dict(title=f"Amount ({symbol})", tickformat=tick_fmt),
                legend_title="Metric",
                margin=dict(l=10, r=10, t=40, b=10),
            )
        st.plotly_chart(fig, width='stretch', key=f"chart_{view_key}_{id(fig)}")

    # ── PIVOT TABLE ───────────────────────────────────────────────────────────
    elif viz == "pivot_table":

        if pivot_type == "metric":
            rows_meta       = metadata.get("rows", [])
            metric_cols_raw = metadata.get("metric_columns", [])
            renamed_rows    = [col_map.get(r, r) for r in rows_meta]
            renamed_metrics = [strip_currency_suffix(col_map.get(m, m))
                               for m in metric_cols_raw]
            existing        = [c for c in renamed_metrics if c in df_chart.columns]

            # No dimension → horizontal bar (e.g. invoice type split overall)
            if not renamed_rows or all(r not in df_chart.columns for r in renamed_rows):
                totals   = {m: float(df_chart[m].sum()) for m in existing}
                chart_df = pd.DataFrame({
                    "Type":   list(totals.keys()),
                    "Amount": list(totals.values()),
                }).sort_values("Amount", ascending=True)
                fig = px.bar(
                    chart_df, x="Amount", y="Type", orientation="h",
                    title=title, color_discrete_sequence=PLOTLY_COLORS,
                    text=chart_df["Amount"].apply(lambda v: format_currency_value(v, currency)),
                )
                fig.update_layout(
                    xaxis=dict(title=f"Amount ({symbol})", tickformat=tick_fmt),
                    yaxis_title="",
                )

            # With dimension → stacked bar (e.g. QoQ × fee type split)
            else:
                dim = next((r for r in renamed_rows if r in df_chart.columns), None)
                if not dim:
                    st.info("Chart not available for this result.")
                    return
                fig = px.bar(
                    df_chart, x=dim, y=existing,
                    barmode="stack",          # stacked — shows composition per period
                    title=title, color_discrete_sequence=PLOTLY_COLORS,
                )
                fig.update_layout(
                    xaxis_title="",
                    yaxis=dict(title=f"Amount ({symbol})", tickformat=tick_fmt),
                    legend_title="Revenue Type",
                )

            st.plotly_chart(fig, width='stretch', key=f"chart_{view_key}_{id(fig)}")

        elif pivot_type == "dimension":
            rows_meta   = metadata.get("rows", [])
            cols_meta   = metadata.get("columns", [])
            values_meta = (metadata.get("values") or [None])[0]
            if not (rows_meta and cols_meta and values_meta):
                st.info("Chart not available for this pivot.")
                return
            r = col_map.get(rows_meta[0],  rows_meta[0])
            c = col_map.get(cols_meta[0],  cols_meta[0])
            v = col_map.get(values_meta,    values_meta)
            if not all(x in df_chart.columns for x in [r, c, v]):
                st.info("Chart not available for this pivot.")
                return
            pivot_2d = df_chart.pivot_table(
                index=r, columns=c, values=v, aggfunc="sum", fill_value=0)

            # Heatmap text is always abbreviated — raw numbers overlap and defeat
            # the purpose of the visual. Raw values toggle applies to tables only.
            def abbrev(val):
                if abs(val) >= 1_000_000: return f"{val/1_000_000:.1f}M"
                if abs(val) >= 1_000:     return f"{val/1_000:.1f}K"
                return f"{val:,.0f}"

            text_matrix = [[abbrev(v) for v in row] for row in pivot_2d.values]

            fig = px.imshow(
                pivot_2d, title=title, aspect="auto",
                color_continuous_scale="Blues",
                text_auto=False,
            )
            for i, row in enumerate(text_matrix):
                for j, txt in enumerate(row):
                    fig.add_annotation(
                        x=j, y=i, text=txt,
                        showarrow=False, font=dict(size=11),
                        xref="x", yref="y",
                    )
            fig.update_layout(xaxis_title=c, yaxis_title=r)
            st.plotly_chart(fig, width='stretch', key=f"chart_{view_key}_{id(fig)}")

    else:
        st.info("Chart not available for this result type.")


def render_result(df, metadata, result, view_key: str = "default"):
    """Core rendering logic — shared between live and replay."""
    display       = metadata.get("display", {})
    visualization = metadata.get("visualization")

    if metadata.get("metric_columns"):
        visualization          = "pivot_table"
        metadata["pivot_type"] = "metric"

    # Empty result — show a clean message rather than crashing downstream
    if df.empty:
        st.info("No data found for this query. Try adjusting the filters or time period.")
        return

    sql_lower = metadata.get("sql", "").lower()
    is_detail = "group by" not in sql_lower
    chartable = visualization in ("bar_chart", "line_chart", "pivot_table") and not is_detail

    if chartable:
        toggle_key = f"view_mode_{view_key}"
        if toggle_key not in st.session_state:
            st.session_state[toggle_key] = "Table"
        col_toggle, _ = st.columns([2, 8])
        with col_toggle:
            view_mode = st.radio(
                "View",
                options=["Table", "Chart"],
                horizontal=True,
                label_visibility="collapsed",
                key=toggle_key,
            )
    else:
        view_mode = "Table"

    if chartable and view_mode == "Chart":
        render_chart(df, metadata, view_key=view_key)
        return

    try:
        if visualization == "pivot_table" and metadata.get("pivot_type") == "metric":
            df = apply_metric_pivot_formatting(df, metadata)
            st.dataframe(df, width='stretch', hide_index=True)

        elif visualization == "pivot_table" and metadata.get("pivot_type") == "dimension":
            rows        = metadata["rows"]
            columns     = metadata["columns"]
            aggregation = metadata.get("aggregation", "sum")

            # Resolve all requested value columns against actual df columns
            col_display  = {v: k for k, v in display.get("columns", {}).items()}
            raw_values   = metadata.get("values") or []
            dim_set      = set(rows + columns)

            resolved = []
            for candidate in raw_values:
                if candidate in df.columns:
                    resolved.append(candidate)
                else:
                    raw = col_display.get(candidate)
                    if raw and raw in df.columns:
                        resolved.append(raw)

            # Fall back to first numeric non-dimension column
            if not resolved:
                resolved = [c for c in df.select_dtypes(include="number").columns
                            if c not in dim_set][:1]
            if not resolved:
                st.error("Could not determine a value column for this pivot.")
                return

            column_map = deduplicate_column_map(
                            {k: strip_currency_suffix(v)
                             for k, v in display.get("columns", {}).items()})

            # ── Single value → standard flat pivot ─────────────────────────
            if len(resolved) == 1:
                pivot_df = df.pivot_table(
                    index=rows, columns=columns, values=resolved[0],
                    aggfunc=aggregation, fill_value=0
                ).reset_index()
                pivot_df.columns = [str(col) for col in pivot_df.columns]
                pivot_df     = pivot_df.rename(columns=column_map)
                renamed_rows = [column_map.get(r, r) for r in rows]

            # ── Multiple values → MultiIndex pivot (grouped column headers) ─
            else:
                pivot_df = df.pivot_table(
                    index=rows, columns=columns, values=resolved,
                    aggfunc=aggregation, fill_value=0
                )
                # Swap levels: top = paying entity, bottom = metric label
                pivot_df = pivot_df.swaplevel(axis=1).sort_index(axis=1)

                # Clean metric sub-labels: collection_inr → INR, collection_usd → USD
                def clean_metric_label(col):
                    if col.endswith("_inr"): return "INR"
                    if col.endswith("_usd"): return "USD"
                    return strip_currency_suffix(column_map.get(col, col))

                pivot_df.columns = pd.MultiIndex.from_tuples(
                    [(str(top), clean_metric_label(bot))
                     for top, bot in pivot_df.columns]
                )
                pivot_df = pivot_df.reset_index()

                # Rename the row dimension column
                pivot_df = pivot_df.rename(
                    columns={rows[0]: column_map.get(rows[0], rows[0])}
                )
                renamed_rows = [column_map.get(r, r) for r in rows]

                # Grand total row (sum numeric cols)
                grand = {col: "" for col in pivot_df.columns}
                grand[pivot_df.columns[0]] = "Grand Total"
                for col in pivot_df.columns[1:]:
                    try:
                        grand[col] = pivot_df[col].sum()
                    except TypeError:
                        grand[col] = ""
                pivot_df = pd.concat(
                    [pivot_df, pd.DataFrame([grand])], ignore_index=True
                )
                st.dataframe(pivot_df, width='stretch', hide_index=True)
                return   # skip the shared formatting path below

            row_label = column_map.get(rows[0], rows[0]) if rows else ""
            col_label = column_map.get(columns[0], columns[0]) if columns else ""
            if row_label and col_label:
                combined_header = f"{row_label} ↓  |  {col_label} →"
                pivot_df        = pivot_df.rename(columns={row_label: combined_header})
                renamed_rows    = [combined_header if r == row_label else r
                                   for r in renamed_rows]

            ageing_cols_in_pivot = [c for c in AGEING_ORDER if c in pivot_df.columns]
            ar_ageing_in_pivot   = [c for c in AR_AGEING_ORDER if c in pivot_df.columns]

            if ageing_cols_in_pivot or ar_ageing_in_pivot:
                pivot_df = apply_ageing_pivot_formatting(pivot_df, metadata, renamed_rows)
            else:
                pivot_df = add_pivot_totals_and_sort(pivot_df, renamed_rows)
                pivot_df = format_pivot_values(pivot_df, metadata, renamed_rows)

            st.dataframe(pivot_df, width='stretch', hide_index=True)

        else:
            sql_lower = metadata.get("sql", "").lower()
            is_detail = "group by" not in sql_lower
            if is_detail and len(df) > 1:
                df = apply_detail_formatting(df, metadata)
                st.dataframe(df, width='stretch', hide_index=True)
            elif len(df) == 1:
                display_meta = metadata.get("display", {})
                currency     = display_meta.get("currency", "USD")
                col_map      = {k: strip_currency_suffix(v)
                                for k, v in display_meta.get("columns", {}).items()}
                numeric_cols = df.select_dtypes(include="number").columns.tolist()
                metric_cols  = [c for c in numeric_cols if is_metric_column(c)]
                if metric_cols:
                    kpi_cols = st.columns(len(metric_cols))
                    for i, col in enumerate(metric_cols):
                        label = strip_currency_suffix(col_map.get(col, col))
                        value = format_currency_value(float(df[col].iloc[0]), currency)
                        kpi_cols[i].metric(label=label, value=value)
                else:
                    df = apply_display_formatting(df, metadata)
                    st.dataframe(df, width='stretch', hide_index=True)
            else:
                df = apply_display_formatting(df, metadata)
                st.dataframe(df, width='stretch', hide_index=True)

    except Exception as render_err:
        st.error(f"Rendering error: {render_err}")
        with st.expander("Debug — raw metadata from Claude"):
            st.json(metadata)
        with st.expander("Debug — raw data columns"):
            st.write(list(df.columns))


# ── Conversation: replay all previous exchanges, then handle new input ─────────

for idx, exchange in enumerate(st.session_state.exchanges):
    render_exchange(exchange, idx=idx)

if user_input:
    # Show the user bubble immediately
    with st.chat_message("user"):
        st.write(user_input)

    # ── Backend call ────────────────────────────────────────────────────────
    try:
        response = requests.post(
            BACKEND_URL,
            json={
                "message": user_input,
                "history": st.session_state.chat_history,
            },
            timeout=300,
        )
    except requests.exceptions.ReadTimeout:
        st.error("Request timed out after 300 s. The query or Claude response took too long.")
        st.stop()
    except requests.exceptions.ConnectionError:
        st.error("Could not connect to backend at " + BACKEND_URL + ". Is the FastAPI server running?")
        st.stop()

    # ── Error handling ──────────────────────────────────────────────────────
    if response.status_code != 200:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text

        with st.chat_message("assistant"):
            if response.status_code == 400 and "GROUP BY" in detail:
                import re
                dim_match = re.search(r"dimensions [(](.+?)[)]", detail)
                bad_dims  = dim_match.group(1).replace("'", "").strip() if dim_match else "unknown"
                st.warning(
                    f"I couldn't find **{bad_dims}** as a valid grouping dimension. "
                    f"Try rephrasing using one of: **region, customer, quarter, "
                    f"currency, subsidiary, billing entity**."
                )
            else:
                st.error("Something went wrong. Please try rephrasing your question.")
                with st.expander("Details"):
                    st.code(detail)

        # Save the error exchange so it appears in conversation history on rerun
        st.session_state.exchanges.append({
            "user_input": user_input,
            "result":     None,
            "error":      detail,
        })
        st.stop()

    # ── Successful response ─────────────────────────────────────────────────
    result   = response.json()
    metadata = result["metadata"]
    data     = result["data"]
    df       = pd.DataFrame(data)

    with st.chat_message("assistant"):
        display     = metadata.get("display", {})
        title       = display.get("title")
        explanation = metadata.get("explanation", "")

        if title:       st.subheader(title)
        if explanation: st.write(explanation)

        with st.expander("Generated SQL"):
            st.code(metadata.get("sql", ""), language="sql")

        render_result(df, metadata, result, view_key=f"exchange_{len(st.session_state.exchanges)}")

        with st.expander("Token usage"):
            st.json(result.get("usage", {}))

    # ── Save to session state (must happen AFTER rendering) ─────────────────
    st.session_state.exchanges.append({
        "user_input": user_input,
        "result":     result,
        "error":      None,
    })

    st.session_state.chat_history.append({
        "user":      user_input,
        "assistant": result.get("assistant_summary", ""),
        "domain":    result.get("domain", "billing"),
    })