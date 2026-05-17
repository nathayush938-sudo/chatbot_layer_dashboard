from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from anthropic import Anthropic
from sqlalchemy import create_engine, text
from datetime import date
import pandas as pd
import os

from schema_context import (
    BILLING_CONTEXT,
    COLLECTIONS_CONTEXT,
    AR_CONTEXT,
    PRESENTATION_RULES,
    STRICT_METRIC_SELECTION_RULES,
    COLUMN_DISPLAY_NAMES,
)
from semantic_model import BILLING_SEMANTIC_MODEL, COLLECTIONS_SEMANTIC_MODEL, AR_SEMANTIC_MODEL

app = FastAPI()

api_key = os.getenv("ANTHROPIC_API_KEY")
database_url = os.getenv("DATABASE_URL")

client = Anthropic(api_key=api_key)
engine = create_engine(database_url) if database_url else None


def format_column_name(col: str) -> str:
    """snake_case → Title Case fallback for unknown columns."""
    return col.replace("_", " ").title()


def fill_display_columns(display: dict, df_columns: list) -> dict:
    """
    Ensures every SQL column has a display name. Priority:
      1. Claude's explicit mapping (already in display.columns)
      2. COLUMN_DISPLAY_NAMES dict (known aliases, fee columns, abbreviations)
      3. format_column_name() title-case fallback

    Deduplication: if two columns resolve to the same display name, appends
    the currency suffix from the column name (_inr / _usd).
    e.g. collection_inr + collection_usd both → "Collections"
    becomes "Collections (INR)" and "Collections (USD)".
    """
    col_map = display.get("columns", {})

    for col in df_columns:
        if col not in col_map:
            col_map[col] = COLUMN_DISPLAY_NAMES.get(col, format_column_name(col))

    # Detect and fix duplicate display names
    name_counts: dict[str, int] = {}
    for name in col_map.values():
        name_counts[name] = name_counts.get(name, 0) + 1

    for col, name in list(col_map.items()):
        if name_counts[name] > 1:
            if col.endswith("_inr"):
                col_map[col] = f"{name} (INR)"
            elif col.endswith("_usd"):
                col_map[col] = f"{name} (USD)"
            else:
                col_map[col] = f"{name} ({col.upper()})"

    display["columns"] = col_map
    return display


def get_fy_info() -> dict:
    """
    Computes Indian financial year (April-March) context.
    Available data: FY25, FY26, FY27 (YTD).
    Default = current FY YTD.

    Indian FY quarters:
      Q1 = April - June      (months 4-6)
      Q2 = July  - September (months 7-9)
      Q3 = Oct   - December  (months 10-12)
      Q4 = Jan   - March     (months 1-3)
    """
    today = date.today()

    if today.month >= 4:
        cur_end_year = today.year + 1
    else:
        cur_end_year = today.year

    current_fy  = f"FY{str(cur_end_year)[-2:]}"       # e.g. FY27
    previous_fy = f"FY{str(cur_end_year - 1)[-2:]}"   # e.g. FY26
    two_yrs_ago = f"FY{str(cur_end_year - 2)[-2:]}"   # e.g. FY25

    # Current quarter in Indian FY
    month_to_q  = {4:1, 5:1, 6:1, 7:2, 8:2, 9:2, 10:3, 11:3, 12:3, 1:4, 2:4, 3:4}
    cur_q       = month_to_q[today.month]
    current_quarter = f"{current_fy} Q{cur_q}"
    last_quarter    = (f"{previous_fy} Q4" if cur_q == 1
                       else f"{current_fy} Q{cur_q - 1}")

    return {
        "current_fy":       current_fy,
        "previous_fy":      previous_fy,
        "two_years_ago_fy": two_yrs_ago,
        "current_quarter":  current_quarter,
        "last_quarter":     last_quarter,
        "today":            today.isoformat(),
    }


class ChatRequest(BaseModel):
    message: str
    history: list = []   # list of {"user": str, "assistant": str} dicts


TOOLS = [
    {
        "name": "generate_sql_response",
        "description": "Generate SQL and display metadata for finance analytics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "sql": {"type": "string"},
                "visualization": {
                    "type": "string",
                    "enum": ["table", "bar_chart", "line_chart", "pivot_table"]
                },
                "pivot_type": {
                    "type": "string",
                    "enum": ["dimension", "metric"]
                },
                "rows": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "values": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "metric_columns": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "aggregation": {"type": "string"},
                "explanation": {"type": "string"},
                "display": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "currency": {"type": "string"},
                        "columns": {
                            "type": "object",
                            "additionalProperties": {"type": "string"}
                        },
                        "formatting": {
                            "type": "object",
                            "additionalProperties": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string"},
                                    "currency": {"type": "string"},
                                    "decimals": {"type": "integer"}
                                }
                            }
                        }
                    },
                    "required": ["title", "columns"]
                }
            },
            "required": [
                "intent",
                "sql",
                "visualization",
                "explanation",
                "display"
            ]
        }
    }
]


# ─────────────────────────────────────────────
# DOMAIN ROUTING
# ─────────────────────────────────────────────

AR_KEYWORDS = [
    "ar", "a/r", "accounts receivable", "receivable", "receivables",
    "outstanding", "overdue", "open invoice", "open invoices",
    "open amount", "unpaid invoice", "unpaid", "days outstanding", "open days",
    "collection status", "client bucket", "client journey", "customer journey",
    "client journey stage", "cjs",
    "ar ageing", "ar aging", "invoice ageing", "invoice aging",
    "outstanding invoice", "due invoice", "pending invoice",
    "total ar", "total outstanding", "total overdue",
    "ucc", "customer ucc", "paying entity",
]

COLLECTION_KEYWORDS = [
    "collection", "collections", "collected",
    "receipt", "receipts",
    "payment received", "payments received",
    "ageing", "aging", "age bucket", "ageing bucket", "aging bucket",
    "dso", "days sales outstanding",
    "tds", "tax deducted",
    "net collection", "net collections",
    "delay", "delayed", "days late",
    "collection due", "past due",
    "collection by", "collect",
    "within cp", "credit period",
]

BILLING_KEYWORDS = [
    # "billing" alone is a strong billing signal AFTER neutral phrase stripping.
    # "billing entity" / "billing subsidiary" are stripped before scoring so
    # "collections for billing entity us" correctly scores zero here.
    "billing", "bill",
    "invoice", "invoices", "invoiced",
    "billed", "billed revenue", "billed amount",
    "invoice type", "invoice split", "revenue split",
    "subscription revenue", "implementation revenue",
    "integration revenue", "studio revenue",
    "subscriptionfee", "implementationfee",
    "integrationfee", "studiofee", "amsfee",
    "credit note",
]

# Terms that appear in ALL domains — strip before scoring so they don't skew routing
NEUTRAL_PHRASES = [
    "billing entity", "billing subsidiary",
    "subsidiary", "paying entity", "billed entity",
]


def classify_domain(message: str, history: list = []) -> str:
    """
    Returns 'ar', 'collections', or 'billing' based on keyword scoring.
    Neutral phrases are stripped first so "billing entity" doesn't score as billing.
    Falls back to last domain in history ONLY when score is truly zero across all domains.
    Defaults to 'billing' when no signal exists anywhere.
    """
    msg = message.lower()

    # Strip neutral phrases before scoring
    for phrase in NEUTRAL_PHRASES:
        msg = msg.replace(phrase, "")

    ar_score         = sum(1 for kw in AR_KEYWORDS if kw in msg)
    collection_score = sum(1 for kw in COLLECTION_KEYWORDS if kw in msg)
    billing_score    = sum(1 for kw in BILLING_KEYWORDS if kw in msg)

    # If any domain has a signal, pick the winner — don't fall back to history
    if ar_score > 0 or collection_score > 0 or billing_score > 0:
        if ar_score >= collection_score and ar_score >= billing_score:
            return "ar"
        if collection_score >= billing_score:
            return "collections"
        return "billing"

    # Truly no signal — fall back to last domain from conversation history
    if history:
        for turn in reversed(history):
            if turn.get("domain"):
                return turn["domain"]

    return "billing"


def build_system_prompt(domain: str) -> str:
    fy = get_fy_info()

    date_and_time_rules = f"""
Financial Year Context (computed at runtime):
  Current FY      : {fy["current_fy"]}  (YTD — available but year not complete)
  Previous FY     : {fy["previous_fy"]} (full year)
  Two FYs ago     : {fy["two_years_ago_fy"]} (full year)
  Current Quarter : {fy["current_quarter"]}
  Last Quarter    : {fy["last_quarter"]}
  Today           : {fy["today"]}
  Available data  : {fy["two_years_ago_fy"]}, {fy["previous_fy"]}, {fy["current_fy"]} (YTD)

Default Time Period Rules:
- If the user does NOT specify any time period, default to CURRENT FY YTD:
  transaction_fy_quarter LIKE '{fy["current_fy"]}%'
- "current year" / "this year" / "YTD"     → transaction_fy_quarter LIKE '{fy["current_fy"]}%'
- "last year" / "previous year" / "FY26"   → transaction_fy_quarter LIKE '{fy["previous_fy"]}%'
- "FY25" / "two years ago"                 → transaction_fy_quarter LIKE '{fy["two_years_ago_fy"]}%'
- "this quarter" / "current quarter"       → transaction_fy_quarter = '{fy["current_quarter"]}'
- "last quarter" / "previous quarter"      → transaction_fy_quarter = '{fy["last_quarter"]}'
- "last 2 years"                           → transaction_fy_quarter LIKE '{fy["previous_fy"]}%' OR transaction_fy_quarter LIKE '{fy["current_fy"]}%'
- "all time" / "all years" / QoQ/YoY      → no time filter
- Custom date range                        → use transaction_date

Year and Quarter as Dimensions:
- "by year" / "year-wise" / "annual"  → GROUP BY LEFT(transaction_fy_quarter, 4) AS fy_year
- "by quarter" / "QoQ" / "quarterly"  → GROUP BY transaction_fy_quarter
- fy_year sort: FY25 → FY26 → FY27 (chronological ASC)

transaction_fy_quarter Column:
- Pre-computed in views. Format: 'FY26 Q1', 'FY27 Q2', etc.
- Use for both WHERE filtering and GROUP BY.
"""

    if domain == "ar":
        return f"""
You are a finance analytics assistant specializing in Accounts Receivable (AR).

Use the following table/view context:

{AR_CONTEXT}

{PRESENTATION_RULES}

{STRICT_METRIC_SELECTION_RULES}

{AR_SEMANTIC_MODEL}

Core Rules:
- Generate PostgreSQL queries only.
- Only SELECT statements are allowed.
- Never generate INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, or CREATE.
- Use only the tables and columns provided in the context.
- SQL should be production-safe and readable.
- Do not use markdown.
- Do not generate text JSON.
- Always use the provided tool to return structured output.

AR-Specific Rules:
- AR is a real-time snapshot as of today. Do NOT add time-period WHERE filters.
- transaction_fy_quarter is a GROUP BY dimension only (invoice creation quarter) — not for WHERE.
- No tds_flag in AR.
- Always filter inter_company_status = 'F' unless user asks for intercompany.
- open_amount is signed (positive=invoice, negative=credit/payment). SUM gives net AR.
- open_amount is in transaction currency — always convert using exchange rate columns.
- Default currency is USD. Use INR only if user asks.
- Ageing buckets are derived via CASE WHEN on open_days — never filter a pre-computed column.
- Never SELECT customer_id, transaction_id, subsidiary_id unless explicitly requested.
- All columns use new unified names: region, client_journey_stage, subsidiary_name,
    currency_symbol, transaction_date, duedate, transaction_fy_quarter.

Display Rules:
- Always include display metadata.
- display.title should be user-friendly.
- display.currency should match the selected reporting currency.
- display.columns should map SQL aliases to clean column names (no currency suffix).
- display.formatting should define currency formatting for all amount columns.
"""

    if domain == "collections":
        return f"""
You are a finance analytics assistant specializing in collections.

Use the following table/view context:

{COLLECTIONS_CONTEXT}

{PRESENTATION_RULES}

{STRICT_METRIC_SELECTION_RULES}

{COLLECTIONS_SEMANTIC_MODEL}

{date_and_time_rules}

Core Rules:
- Generate PostgreSQL queries only.
- Only SELECT statements are allowed.
- Never generate INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, or CREATE.
- Use only the tables and columns provided in the context.
- SQL should be production-safe and readable.
- Do not use markdown.
- Do not generate text JSON.
- Always use the provided tool to return structured output.

Default Filters:
- Always apply inter_company_status = 'F' unless user asks for intercompany.
- Always apply tds_flag = 'F' by default (net collections — TDS excluded).
  Only remove when user says "including TDS" or "gross collections".

Currency Rules:
- Default reporting currency is INR unless user asks for USD.
- Use collection_amount (NOT transaction_amount) for all collection metrics.
- collection_amount is in transaction currency.
- Convert to INR using: collection_amount * inr_exchangerate
- Convert to USD using: collection_amount * usd_exchangerate
- Never use pre-computed currency columns; always compute inside SQL.

Key column names (updated schema):
- transaction_date: date of payment
- collection_amount: per-invoice collection amount (use this, not transaction_amount)
- collection_due_date: due date of linked invoice
- transaction_fy_quarter: FY quarter of payment
- region: customer region
- subsidiary_name: billing entity name
- paying_entity: paying entity (intercompany only)
- currency_symbol: transaction currency symbol

Ageing Bucket Rules:
- Valid buckets in order: 'Within CP', '1-15 days', '16-30 days', '31-45 days',
  '46-60 days', '61-90 days', '>90 days'.
- Never sort ageingbucket alphabetically.
- Always use CASE WHEN ORDER BY for ageing bucket reports.

Display Rules:
- Always include display metadata.
- display.title should be user-friendly.
- display.currency should match the selected reporting currency.
- display.columns should map SQL aliases to clean column names.
- display.formatting should define currency formatting for amount columns.
"""

    # Default: billing
    return f"""
You are a finance analytics assistant.

Use the following table/view context:

{BILLING_CONTEXT}

{PRESENTATION_RULES}

{STRICT_METRIC_SELECTION_RULES}

{BILLING_SEMANTIC_MODEL}

{date_and_time_rules}

Core Rules:
- Generate PostgreSQL queries only.
- Only SELECT statements are allowed.
- Never generate INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, or CREATE.
- Use only the tables and columns provided in the context.
- SQL should be production-safe and readable.
- Do not use markdown.
- Do not generate text JSON.
- Always use the provided tool to return structured output.

Currency Rules:
- Default currency is USD unless user asks for INR.
- billing_amount (= transaction_amount) and all fee columns are in transaction currency.
- Convert using usd_exchangerate or inr_exchangerate inside SQL.
- Tax: use COALESCE(transaction_tax,0) * rate. Never pre-computed tax columns.
- Excluding tax: billing_amount - COALESCE(transaction_tax,0), then multiply by rate.

Display Rules:
- Always include display metadata.
- display.title should be user-friendly.
- display.currency should match the selected reporting currency.
- display.columns should map SQL aliases to clean column names.
- display.formatting should define currency formatting for amount columns.
"""


# ─────────────────────────────────────────────
# VALIDATORS
# ─────────────────────────────────────────────

def validate_sql(sql: str, metadata: dict = None) -> str:
    cleaned = sql.strip().lower()

    blocked_words = [
        "insert", "update", "delete", "drop",
        "alter", "truncate", "create"
    ]

    if not cleaned.startswith("select") and not cleaned.startswith("with"):
        raise HTTPException(status_code=400, detail="Only SELECT queries are allowed.")

    if any(word in cleaned for word in blocked_words):
        raise HTTPException(status_code=400, detail="Unsafe SQL detected.")

    # If a pivot/table has row dimensions specified, SQL must GROUP BY something
    if metadata:
        rows = metadata.get("rows", [])
        viz  = metadata.get("visualization", "")
        if rows and "group by" not in cleaned:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid query: dimensions {rows} were requested but the generated "
                    f"SQL has no GROUP BY clause. The dimension(s) may not exist in the schema. "
                    f"Please rephrase using a valid dimension such as region, customer, quarter, "
                    f"currency, subsidiary, or billing entity."
                )
            )

    return sql


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.get("/")
def health_check():
    return {
        "status": "FastAPI is running",
        "api_key_loaded": api_key is not None,
        "database_loaded": database_url is not None
    }


@app.post("/chat")
def chat(request: ChatRequest):
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not loaded")

    if not engine:
        raise HTTPException(status_code=500, detail="DATABASE_URL is not loaded")

    domain = classify_domain(request.message, request.history)
    system_prompt = build_system_prompt(domain)

    import time

    try:
        print(f"\n[{domain.upper()}] Query: {request.message}")

        t0 = time.time()
        print(f"  → Calling Claude... (history turns: {len(request.history)})")

        # Build messages — inject conversation history before current message
        messages = []
        for turn in request.history:
            messages.append({"role": "user",      "content": turn["user"]})
            messages.append({"role": "assistant",  "content": turn["assistant"]})
        messages.append({"role": "user", "content": request.message})

        claude_response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=4096,
            temperature=0,
            system=system_prompt,
            messages=messages,
            tools=TOOLS,
            tool_choice={
                "type": "tool",
                "name": "generate_sql_response"
            }
        )
        t1 = time.time()
        print(f"  ✓ Claude responded in {t1 - t0:.1f}s "
              f"(in={claude_response.usage.input_tokens} "
              f"out={claude_response.usage.output_tokens} tokens)")

        parsed = None
        for block in claude_response.content:
            if block.type == "tool_use":
                parsed = block.input
                break

        if parsed is None:
            raise HTTPException(
                status_code=500,
                detail="Claude did not return structured tool output"
            )

        sql = validate_sql(parsed["sql"], parsed)
        print(f"  → Running SQL:\n{sql}")

        t2 = time.time()
        df = pd.read_sql_query(text(sql), engine)
        t3 = time.time()
        print(f"  ✓ DB returned {len(df)} rows in {t3 - t2:.1f}s")
        print(f"  ✓ Total: {t3 - t0:.1f}s")

        # Replace NaN/Inf/None in ALL column types before JSON serialization
        # astype(object) ensures string columns also get NaN replaced properly
        df = df.astype(object).where(pd.notnull(df), other=None)

        usage = {
            "input_tokens":  claude_response.usage.input_tokens,
            "output_tokens": claude_response.usage.output_tokens,
        }

        # Build a plain-text assistant summary for conversation history storage
        display  = parsed.get("display", {})
        display  = fill_display_columns(display, list(df.columns))
        parsed["display"] = display
        assistant_summary = (
            f"Report generated: {display.get('title', 'Untitled')}\n"
            f"{parsed.get('explanation', '')}\n"
            f"Visualization: {parsed.get('visualization', 'table')}"
            f"{' (' + parsed.get('pivot_type','') + ')' if parsed.get('pivot_type') else ''}\n"
            f"SQL used:\n{parsed.get('sql', '')}"
        )

        return {
            "metadata":          parsed,
            "data":              df.to_dict(orient="records"),
            "columns":           list(df.columns),
            "domain":            domain,
            "assistant_summary": assistant_summary,
            "usage":             usage,
        }

    except Exception as e:
        print(f"  ✗ Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))