"""
nl_filter.py
Natural language filter parser for DataFrame results.
No Claude API calls — pure Python regex + pandas.

Supported patterns:
  Comparison : "greater than 1M", "less than 500K", "above 5 Cr", "below 10%"
  Between    : "between 1M and 5M"
  Top/Bottom : "top 5", "bottom 10"
  Include    : "only India", "only DB India", "show Issue"
  Exclude    : "exclude Unassigned", "not Churned", "remove 0"
  Combined   : "only APAC greater than 2M", "exclude Unassigned top 10"
"""

import re
import pandas as pd

# ─────────────────────────────────────────────
# NUMBER PARSING
# ─────────────────────────────────────────────

def parse_number(s: str) -> float | None:
    """
    Parse a human number string into a float.
    Handles: 1M, 5.5Mn, 2K, 3.2Cr, 1.5L, 50%, 1000
    """
    s = s.strip().lower().replace(",", "")
    multipliers = {
        "bn": 1_000_000_000,
        "b":  1_000_000_000,
        "cr": 10_000_000,
        "mn": 1_000_000,
        "m":  1_000_000,
        "l":  100_000,
        "lk": 100_000,
        "k":  1_000,
    }
    m = re.match(r"^([\d.]+)\s*([a-z]*)%?$", s)
    if not m:
        return None
    num    = float(m.group(1))
    suffix = m.group(2)

    if s.endswith("%"):
        return num / 100

    for key, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if suffix == key:
            return num * mult

    return num if suffix == "" else None


# ─────────────────────────────────────────────
# COLUMN SELECTION HELPERS
# ─────────────────────────────────────────────

def get_primary_numeric_col(df: pd.DataFrame) -> str | None:
    """Return the most likely 'main metric' column for comparison filters."""
    candidates = df.select_dtypes(include="number").columns.tolist()
    # Prefer columns with metric-sounding names
    priority = ["outstanding", "overdue", "amount", "collection",
                "revenue", "billed", "total"]
    for p in priority:
        for c in candidates:
            if p in c.lower():
                return c
    return candidates[0] if candidates else None


def find_numeric_col(df: pd.DataFrame, hint: str) -> str | None:
    """
    Find a numeric column by name hint.
    e.g. hint='outstanding' matches 'Total Outstanding', 'Amount Outstanding'
    """
    hint = hint.lower().strip()
    for col in df.select_dtypes(include="number").columns:
        if hint in col.lower():
            return col
    return None


def find_string_col(df: pd.DataFrame, value: str) -> str | None:
    """
    Find which string column contains the given value.
    Tries exact match first, then partial.
    """
    for col in df.select_dtypes(include=["object", "str"]).columns:
        col_vals = df[col].dropna().astype(str)
        # Exact match
        if col_vals.str.lower().eq(value.lower()).any():
            return col
        # Partial match
        if col_vals.str.lower().str.contains(value.lower(), regex=False).any():
            return col
    return None


# ─────────────────────────────────────────────
# FILTER RESULT DATACLASS
# ─────────────────────────────────────────────

class FilterResult:
    def __init__(self, df: pd.DataFrame, description: str,
                 ambiguous_col: str = None, candidates: list = None):
        self.df           = df            # filtered DataFrame
        self.description  = description  # human-readable summary
        self.ambiguous_col = ambiguous_col  # set if user needs to pick column
        self.candidates   = candidates or []  # column options for disambiguation


# ─────────────────────────────────────────────
# MAIN PARSER
# ─────────────────────────────────────────────

def parse_nl_filter(text: str, df: pd.DataFrame,
                    target_col: str = None) -> FilterResult:
    """
    Parse a natural language filter string and apply it to df.

    target_col: if provided, override column selection for numeric filters
                (used after user resolves ambiguity).

    Returns FilterResult with:
      .df            — filtered DataFrame (original if nothing matched)
      .description   — what was applied, e.g. "Showing 3 of 8 rows (only India)"
      .ambiguous_col — set when multiple numeric cols could match; caller shows picker
      .candidates    — list of column names to choose from
    """
    if not text or not text.strip():
        return FilterResult(df, "")

    raw   = text.strip()
    lower = raw.lower()
    result_df = df.copy()
    applied   = []

    # ── 1. TOP / BOTTOM N ────────────────────────────────────────────────────
    top_m    = re.search(r"\btop\s+(\d+)\b",    lower)
    bottom_m = re.search(r"\bbottom\s+(\d+)\b", lower)
    n_filter = None
    n_dir    = None
    if top_m:
        n_filter = int(top_m.group(1))
        n_dir    = "top"
        lower    = re.sub(r"\btop\s+\d+\b", "", lower).strip()
    elif bottom_m:
        n_filter = int(bottom_m.group(1))
        n_dir    = "bottom"
        lower    = re.sub(r"\bbottom\s+\d+\b", "", lower).strip()

    # ── 2. BETWEEN ───────────────────────────────────────────────────────────
    between_m = re.search(
        r"\bbetween\s+([\d.,]+\s*[a-z%]*)\s+and\s+([\d.,]+\s*[a-z%]*)\b",
        lower
    )
    if between_m:
        lo = parse_number(between_m.group(1))
        hi = parse_number(between_m.group(2))
        if lo is not None and hi is not None:
            col = target_col or _resolve_numeric_col(lower, df)
            if isinstance(col, list):
                return FilterResult(df, "",
                                    ambiguous_col=raw,
                                    candidates=col)
            if col and col in result_df.columns:
                result_df = result_df[
                    result_df[col].between(lo, hi)
                ]
                applied.append(
                    f"{col} between {between_m.group(1)} and {between_m.group(2)}"
                )
        lower = re.sub(
            r"\bbetween\s+[\d.,]+\s*[a-z%]*\s+and\s+[\d.,]+\s*[a-z%]*\b",
            "", lower
        ).strip()

    # ── 3. COMPARISON (greater/less/above/below/more/fewer) ──────────────────
    cmp_pattern = re.compile(
        r"\b(greater\s+than|more\s+than|above|over|"
        r"less\s+than|fewer\s+than|below|under)\s+"
        r"([\d.,]+\s*[a-z%]*)\b"
    )
    for m in cmp_pattern.finditer(lower):
        direction = m.group(1).replace(" ", "_")
        num       = parse_number(m.group(2))
        if num is None:
            continue
        col = target_col or _resolve_numeric_col(lower, df, hint_from=m.group(0))
        if isinstance(col, list):
            return FilterResult(df, "", ambiguous_col=raw, candidates=col)
        if col and col in result_df.columns:
            if direction in ("greater_than", "more_than", "above", "over"):
                result_df = result_df[result_df[col] > num]
                applied.append(f"{col} > {m.group(2)}")
            else:
                result_df = result_df[result_df[col] < num]
                applied.append(f"{col} < {m.group(2)}")

    # ── 4. EXCLUDE ───────────────────────────────────────────────────────────
    excl_pattern = re.compile(
        r"\b(?:exclude|not|remove|without|except)\s+['\"]?([^,\n]+?)['\"]?"
        r"(?=\s+(?:greater|less|above|below|top|bottom|only|and)|$)"
    )
    for m in excl_pattern.finditer(lower):
        val = m.group(1).strip().rstrip(".,")
        col = find_string_col(result_df, val)
        if col:
            mask = result_df[col].astype(str).str.lower() != val.lower()
            result_df = result_df[mask]
            applied.append(f"exclude {val}")

    # ── 5. INCLUDE (only/show/filter to) ─────────────────────────────────────
    incl_pattern = re.compile(
        r"\b(?:only|show|filter\s+to|just)\s+['\"]?([^,\n]+?)['\"]?"
        r"(?=\s+(?:greater|less|above|below|top|bottom|exclude|and)|$)"
    )
    for m in incl_pattern.finditer(lower):
        val = m.group(1).strip().rstrip(".,")
        # Skip if it's a number (e.g. "top 5" already handled)
        if re.match(r"^\d+$", val):
            continue
        col = find_string_col(result_df, val)
        if col:
            mask = (
                result_df[col].astype(str).str.lower().str.contains(
                    val.lower(), regex=False
                )
            )
            result_df = result_df[mask]
            applied.append(f"only {val}")

    # ── 6. TOP / BOTTOM N (apply after row filters) ──────────────────────────
    if n_filter is not None:
        num_col = get_primary_numeric_col(result_df)
        if num_col:
            result_df = result_df.nlargest(n_filter, num_col) \
                        if n_dir == "top" \
                        else result_df.nsmallest(n_filter, num_col)
            applied.append(f"{n_dir} {n_filter}")

    # ── BUILD DESCRIPTION ────────────────────────────────────────────────────
    if applied:
        desc = (f"Showing {len(result_df):,} of {len(df):,} rows "
                f"· {' · '.join(applied)}")
    else:
        desc = f"No filter matched — showing all {len(df):,} rows"

    return FilterResult(result_df, desc)


# ─────────────────────────────────────────────
# INTERNAL: NUMERIC COLUMN RESOLVER
# ─────────────────────────────────────────────

def _resolve_numeric_col(text: str, df: pd.DataFrame,
                         hint_from: str = "") -> str | list:
    """
    Return the numeric column to filter on.
    - If the text contains a column name hint, use that column.
    - If there's only one numeric column, use it.
    - If multiple numeric columns exist and no hint, return list for disambiguation.
    """
    num_cols = df.select_dtypes(include="number").columns.tolist()
    if not num_cols:
        return None
    if len(num_cols) == 1:
        return num_cols[0]

    # Try to match a column name from the filter text
    for col in num_cols:
        col_lower = col.lower()
        words     = re.findall(r"\w+", col_lower)
        for word in words:
            if len(word) > 3 and word in text.lower():
                return col

    # Prefer primary metric columns
    primary = get_primary_numeric_col(df)
    if primary:
        return primary

    # Ambiguous — return list for user to pick
    return num_cols