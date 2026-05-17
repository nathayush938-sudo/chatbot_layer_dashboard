# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA CONTEXT
# One source of truth for table/view definitions, column catalogs, and
# currency/metric conversion rules.  Imported by backend.py and used in
# system prompts so Claude knows the exact schema for each domain.
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────
# COLUMN DISPLAY NAMES  (single source of truth)
#
# Used in two places:
#   1. Embedded into semantic model prompts so Claude sends correct names.
#   2. Imported by backend.py as a Python dict for the fallback formatter.
#
# Rule: include any column where .replace("_"," ").title() gives a wrong result.
#   - Fee columns with no underscores (openingsplitfee → "Opening Split Fee")
#   - Abbreviations that must stay uppercase (INR, USD, UCC, TDS, AMS, ID, FY)
#   - Business-specific renames (subsidiary_name → "Billing Entity")
#   - Compound words with no separator (duedate, ageingbucket, inr_exchangerate)
# ─────────────────────────────────────────────

# Columns to silently drop from every query result before returning to frontend.
# These are raw NetSuite amounts already captured in more useful derived columns
# (billing_amount, collection_amount, open_amount) and add noise to the output.
COLUMNS_TO_EXCLUDE: set[str] = {
    "transaction_amount",
    "transaction_amount_paid",
    "transaction_amount_unpaid",
}

# When any of these appear as a dimension column in a multi-row result,
# rows where customer_name IS NULL are dropped (null customers are noise in
# customer breakdowns but should be kept in single-row aggregate totals).
CUSTOMER_DIMENSION_COLUMNS: set[str] = {
    "customer_name",
    "customer_ucc",
    "entity_id",
    "ucc_parent",
}


CURRENCY_CODE_MAP: dict[str, str] = {
    "INR": "Indian Rupee",
    "USD": "US Dollar",
    "EUR": "Euro",
    "GBP": "British Pound",
    "CAD": "Canadian Dollar",
    "AED": "Emirati Dirham",
    "SGD": "Singapore Dollar",
    "SAR": "Saudi Riyal",
    "MYR": "Malaysian Ringgit",
    "IDR": "Indonesian Rupiah",
    "PHP": "Philippine Peso",
    "THB": "Thai Baht",
}


def render_currency_filter_rule() -> str:
    lines = [
        "CURRENCY FILTER RULE:",
        '  "billed in [currency]" / "invoiced in [currency]" / "transactions in [currency]"',
        "  → add WHERE currency_symbol = '<CODE>' to the query.",
        "  This filters to transactions raised in that currency — it is NOT a reporting",
        "  currency switch. The metric SUM still uses the appropriate exchange rate column.",
        "",
        "  currency_symbol stores the 3-letter ISO code. Mapping:",
    ]
    for code, name in CURRENCY_CODE_MAP.items():
        lines.append(f"    {name:<22} → currency_symbol = '{code}'")
    lines.append("")
    lines.append("  Examples:")
    lines.append('    "collections billed in INR"  → WHERE currency_symbol = \'INR\'')
    lines.append('    "billing in USD"             → WHERE currency_symbol = \'USD\'')
    lines.append('    "invoices raised in GBP"     → WHERE currency_symbol = \'GBP\'')
    return "\n".join(lines)


def render_dimension_values() -> str:
    return """
DIMENSION VALUES (exact strings stored in the database):
─────────────────────────────────────────────────────────

subsidiary_name  (billing entity — use these exact strings in WHERE / GROUP BY):
  'DB India'   — India subsidiary
  'DB MY'      — Malaysia
  'DB Mena'    — Middle East & North Africa
  'DB US'      — United States
  'DB SG'      — Singapore
  'DB PH'      — Philippines
  'DB TH'      — Thailand
  'DB ID'      — Indonesia
  Aliases: "India" → 'DB India', "Malaysia"/"MY" → 'DB MY', "MENA"/"Middle East" → 'DB Mena',
           "US"/"America" → 'DB US', "Singapore"/"SG" → 'DB SG',
           "Philippines"/"PH" → 'DB PH', "Thailand"/"TH" → 'DB TH',
           "Indonesia"/"ID" → 'DB ID'

paying_entity  (intercompany only — use TRIM() in WHERE due to trailing whitespace in data):
  'DB India', 'DB Mena', 'DB SG', 'DB PH', 'Compport Private Limited'
  ALWAYS use: WHERE TRIM(paying_entity) = '<value>'

region  (11 values):
  'APAC', 'EU', 'MENA', 'NORAM', 'HeadQuarter',
  'India - North', 'India - South', 'India - West',
  'India - Growth A', 'India - Growth B', 'Unassigned'
  Aliases: "North India" → 'India - North', "South India" → 'India - South',
           "West India" → 'India - West', "Europe" → 'EU',
           "North America" → 'NORAM', "Middle East" → 'MENA'

country  (exclude '0' — junk value):
  'APAC - ID', 'APAC - MY', 'APAC - PH', 'APAC - SG', 'APAC - TH',
  'EU', 'HeadQuarter', 'MENA', 'NORAM',
  'India - North', 'India - South', 'India - West', 'Unassigned'
  NOTE: '0' appears in data but is a junk value — add WHERE country != '0' if filtering.

client_journey_stage  (cjs — 5 active values + Unassigned):
  'Customer Success', 'Implementation', 'Potential Churn', 'Churned', 'One Time', 'Unassigned'
  Aliases: "CS" → 'Customer Success', "churn risk" → 'Potential Churn'

client_buckets  (3 active values + Unassigned):
  'Non-Issue', 'Issue', 'Churned Account', 'Unassigned'

collection_status  (10 active values + Unassigned — exclude '0'):
  'Acknowledged'
  'Pending Acknowledgement'
  'Payment Date'
  'Agreement / Renewal'
  'Invoice revision'
  'Implementation Issue / Implementation Delays'
  'Product Issue'
  'Other Issues'
  'Potential Churn'
  'Churned Account'
  'Unassigned'
  NOTE: '0' appears in data but is a junk value — exclude from filters.
  Aliases: "impl issue" → 'Implementation Issue / Implementation Delays',
           "pending" → 'Pending Acknowledgement', "renewal" → 'Agreement / Renewal'

GENERAL RULE: 'Unassigned' is a valid stored value (not NULL). Filter with
  WHERE <col> != 'Unassigned'  to exclude unassigned rows.
"""


    lines = [
        "CURRENCY FILTER RULE:",
        '  "billed in [currency]" / "invoiced in [currency]" / "transactions in [currency]"',
        "  → add WHERE currency_symbol = '<CODE>' to the query.",
        "  This filters to transactions raised in that currency — it is NOT a reporting",
        "  currency switch. The metric SUM still uses the appropriate exchange rate column.",
        "",
        "  currency_symbol stores the 3-letter ISO code. Mapping:",
    ]
    for code, name in CURRENCY_CODE_MAP.items():
        lines.append(f"    {name:<22} → currency_symbol = '{code}'")
    lines.append("")
    lines.append("  Examples:")
    lines.append('    "collections billed in INR"  → WHERE currency_symbol = \'INR\'')
    lines.append('    "billing in USD"             → WHERE currency_symbol = \'USD\'')
    lines.append('    "invoices raised in GBP"     → WHERE currency_symbol = \'GBP\'')
    return "\n".join(lines)




COLUMN_DISPLAY_NAMES: dict[str, str] = {
    # ── Identifier columns ────────────────────────────────────────────────────
    "transaction_id":           "Transaction ID",
    "transaction_currency_id":  "Currency ID",
    "customer_id":              "Customer ID",
    "subsidiary_id":            "Subsidiary ID",

    # ── Date / period columns ─────────────────────────────────────────────────
    "duedate":                  "Due Date",
    "transaction_fy_quarter":   "FY Quarter",
    "collection_due_date":      "Invoice Due Date",

    # ── Exchange rate columns ─────────────────────────────────────────────────
    "inr_exchangerate":         "INR Exchange Rate",
    "usd_exchangerate":         "USD Exchange Rate",

    # ── Customer / account columns ────────────────────────────────────────────
    "customer_ucc":             "Customer UCC",
    "ucc_parent":               "Parent UCC",
    "entity_id":                "Entity ID",

    # ── Entity / currency columns (business-specific renames) ─────────────────
    "subsidiary_name":          "Billing Entity",
    "currency_symbol":          "Currency",
    "inter_company_status":     "Intercompany",

    # ── Segmentation columns ──────────────────────────────────────────────────
    "client_journey_stage":     "Client Journey Stage",
    "client_buckets":           "Client Bucket",
    "collection_status":        "Collection Status",

    # ── Collections-specific ──────────────────────────────────────────────────
    "tds_flag":                 "TDS",
    "ageingbucket":             "Ageing Bucket",
    "collection_amount":        "Collection Amount",

    # ── AR-specific ───────────────────────────────────────────────────────────
    "open_days":                "Days Open",
    "ageing_bucket":            "Ageing Bucket",     # derived alias in AR queries

    # ── Billing raw amount columns ────────────────────────────────────────────
    "billing_amount":           "Billed Amount",
    "transaction_amount_paid":  "Amount Paid",
    "transaction_amount_unpaid":"Amount Unpaid",
    "transaction_tax":          "Tax Amount",
    "transaction_exchange_rate":"Exchange Rate",

    # ── Fee columns (no underscores — auto-formatter can't split these) ────────
    "subscriptionfee":          "Subscription Fee",
    "implementationfee":        "Implementation Fee",
    "integrationfee":           "Integration Fee",
    "studiofee":                "Studio Fee",
    "otherservicesfee":         "Other Services Fee",
    "openingsplitfee":          "Opening Split Fee",
    "amsfee":                   "AMS Fee",

    # ── Computed metric aliases: billing ──────────────────────────────────────
    "billed_revenue_usd":               "Billed Revenue",
    "billed_revenue_inr":               "Billed Revenue",
    "billed_revenue_excl_tax_usd":      "Billed Revenue (Ex-Tax)",
    "billed_revenue_excl_tax_inr":      "Billed Revenue (Ex-Tax)",
    "tax_amount_usd":                   "Tax Amount",
    "tax_amount_inr":                   "Tax Amount",
    "subscription_revenue_usd":         "Subscription Revenue",
    "subscription_revenue_inr":         "Subscription Revenue",
    "implementation_revenue_usd":       "Implementation Revenue",
    "implementation_revenue_inr":       "Implementation Revenue",
    "integration_revenue_usd":          "Integration Revenue",
    "integration_revenue_inr":          "Integration Revenue",
    "studio_revenue_usd":               "Studio Revenue",
    "studio_revenue_inr":               "Studio Revenue",
    "other_services_revenue_usd":       "Other Services Revenue",
    "other_services_revenue_inr":       "Other Services Revenue",
    "fy_year":                          "Financial Year",

    # ── Computed metric aliases: collections ──────────────────────────────────
    "collection_inr":           "Collections",
    "collection_usd":           "Collections",
    "gross_collection_inr":     "Gross Collections",
    "gross_collection_usd":     "Gross Collections",
    "tds_amount_inr":           "TDS Amount",
    "tds_amount_usd":           "TDS Amount",

    # ── Computed metric aliases: AR ───────────────────────────────────────────
    "outstanding_usd":                  "Amount Outstanding",
    "outstanding_inr":                  "Amount Outstanding",
    "overdue_usd":                      "Amount Overdue",
    "overdue_inr":                      "Amount Overdue",
    "current_usd":                      "Current Amount",
    "current_inr":                      "Current Amount",
    "invoice_count":                    "Invoice Count",
    "overdue_pct_of_outstanding":       "Overdue as % of Outstanding",
    "total_outstanding_usd":            "Total Outstanding",
    "total_outstanding_inr":            "Total Outstanding",
    "total_overdue_usd":                "Total Overdue",
    "total_overdue_inr":                "Total Overdue",
    "bucket_current_usd":               "Current",
    "bucket_1_30_usd":                  "1-30 Days",
    "bucket_31_60_usd":                 "31-60 Days",
    "bucket_61_90_usd":                 "61-90 Days",
    "bucket_91_180_usd":                "91-180 Days",
    "bucket_over_180_usd":              ">180 Days",
    "outstanding_issue_usd":            "Outstanding - Issue",
    "outstanding_non_issue_usd":        "Outstanding - Non-Issue",
    "outstanding_cs_usd":               "Outstanding - Customer Success",
    "outstanding_impl_usd":             "Outstanding - Implementation",
    "outstanding_churn_usd":            "Outstanding - Potential Churn",
}


def render_column_display_names() -> str:
    """
    Returns COLUMN_DISPLAY_NAMES as a formatted string block for embedding
    in semantic model prompts.  Claude reads this to know the correct display
    name for every known column alias before Python ever sees the response.
    """
    lines = ["COLUMN DISPLAY NAMES:"]
    lines.append("  Use these mappings in every display.columns object.")
    lines.append("  For any alias not listed here, Python will auto-format it.")
    lines.append("")
    for col, label in COLUMN_DISPLAY_NAMES.items():
        lines.append(f"  {col:<35} → \"{label}\"")
    return "\n".join(lines)


STRICT_METRIC_SELECTION_RULES = """
METRIC SELECTION RULES:
- Only return metrics explicitly requested by the user.
- Do NOT add billed tax, counts, averages, or percentages unless explicitly requested.
- Do NOT add explanatory KPIs automatically.
- Keep output minimal and aligned to user request.

EXCEPTION — Invoice / Revenue Type Split:
  Tax amount is ALWAYS included when user asks for any type split / invoice split /
  revenue split. It is a core component of the split definition.

Examples:
  "Show billing by region"            → billed_revenue_usd only
  "Show billing by currency with tax" → billed_revenue_usd + tax_amount_usd
  "Show billing type split"           → all 6 fee types + tax (exception above)
"""


PRESENTATION_RULES = """
VISUALIZATION TYPES:
  table        — detailed records, raw data, summary rows
  bar_chart    — rankings, comparisons (e.g. top customers, billing by region)
  line_chart   — trends over time (e.g. QoQ, monthly trend)
  pivot_table  — cross-tab / matrix views

STANDARD TABLE RULES:
  - table  → detailed records / summary rows
  - bar_chart → rankings / comparisons
  - line_chart → trends over time

PIVOT TABLE RULES:
  Use visualization = "pivot_table" when user says: pivot, matrix, cross tab,
  rows and columns, "X in rows and Y in columns".

  TWO pivot types:

  1. DIMENSION PIVOT — both rows and columns are dimensions/categories:
     {
       "visualization": "pivot_table",
       "pivot_type": "dimension",
       "rows": ["<row_dimension>"],
       "columns": ["<col_dimension>"],
       "values": ["<metric_alias>"],
       "aggregation": "sum"
     }
     - SQL returns LONG format. Python frontend pivots dynamically.
     - Do NOT generate CASE WHEN pivot SQL.

  2. METRIC PIVOT — rows are dimension(s), columns are multiple metrics:
     {
       "visualization": "pivot_table",
       "pivot_type": "metric",
       "rows": ["<dimension>"],
       "metric_columns": ["<alias1>", "<alias2>", ...]
     }
     - SQL returns one row per dimension with all metric columns.

DISPLAY OBJECT (always required):
  display must contain:
  - title      : short, user-friendly report title
  - currency   : "USD" or "INR"
  - columns    : { "<sql_alias>": "<clean display name>" }  — no currency suffix in display names
  - formatting : { "<alias>": { "type": "currency"|"percentage"|"number",
                                "currency": "USD"|"INR",
                                "decimals": 0|1|2 } }

  Example:
  "display": {
    "title": "Billing by Region",
    "currency": "USD",
    "columns": { "region": "Region", "billed_revenue_usd": "Billed Revenue" },
    "formatting": { "billed_revenue_usd": { "type": "currency", "currency": "USD", "decimals": 0 } }
  }

GENERAL RULES:
  - PostgreSQL syntax only.
  - Only SELECT statements. Never INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE.
  - Do not use markdown or code fences.
  - Only include JSON fields relevant to the query type.
"""


# ─────────────────────────────────────────────
# BILLING
# ─────────────────────────────────────────────

BILLING_CONTEXT = """
TABLE / VIEW: billing

Business purpose:
  Invoice and credit note billing data. Analyse billed revenue, tax, invoice type
  splits, customers, regions, subsidiaries, currencies, and inter-company billing.

Grain: One row per billing transaction (CustInvc or CustCred).

Default filter: inter_company_status = 'F'  (external customers only).
Default currency: USD.

─── COMPLETE COLUMN CATALOG ────────────────────────────────────────────────────
Identifier columns (never SELECT unless explicitly requested):
  transaction_id          — Internal ID of the billing transaction.
  customer_id             — Internal customer ID.
  subsidiary_id           — Internal subsidiary ID.
  transaction_currency_id — Internal currency ID.

Dimension columns:
  transaction_number      — Human-readable transaction number (e.g. INV-00123).
  transaction_type        — CustInvc or CustCred.
  transaction_date        — Date the transaction was created.
  duedate                 — Due date of the invoice.
  transaction_fy_quarter  — FY quarter of transaction date (e.g. FY26 Q1).
  memo                    — Transaction memo field.
  customer_ucc            — Unique customer code.
  customer_name           — Customer company name.
  ucc_parent              — UCC of parent company.
  entity_id               — Customer entity ID (use in customer-level detail).
  region                  — Mapped region of the customer.
  country                 — Country of the customer.
  client_journey_stage    — Churned | Customer Success | Implementation | One Time | Potential Churn
  client_buckets          — Churned Account | Non-Issue | Issue
  collection_status       — Collection follow-up status.
  subsidiary_name         — Name of billing entity / subsidiary.
  paying_entity           — Paying entity name (intercompany only).
  currency_symbol         — Symbol of transaction currency.
  inter_company_status    — T = intercompany, F = external.

Raw amount columns (in transaction currency — always convert via exchange rate):
  transaction_amount      — Total amount. Aliased as billing_amount; use billing_amount.
  billing_amount          — Same as transaction_amount. Primary metric column.
  transaction_amount_paid   — Amount paid so far.
  transaction_amount_unpaid — Amount still outstanding.
  transaction_tax           — Tax amount. Use COALESCE(transaction_tax, 0).
  transaction_exchange_rate — Base exchange rate (used internally for fee splits).
  subscriptionfee         — Subscription revenue in transaction currency.
  implementationfee       — Implementation revenue in transaction currency.
  integrationfee          — Integration revenue in transaction currency.
  studiofee               — Studio revenue in transaction currency.
  otherservicesfee        — Other services revenue in transaction currency.
  openingsplitfee         — Opening split revenue in transaction currency.
  amsfee                  — AMS revenue in transaction currency.

Exchange rate columns:
  inr_exchangerate        — Rate: transaction currency → INR.
  usd_exchangerate        — Rate: transaction currency → USD.
────────────────────────────────────────────────────────────────────────────────

METRIC CONVERSION RULES:
  Billed revenue (incl tax) USD : SUM(billing_amount * usd_exchangerate)
  Billed revenue (incl tax) INR : SUM(billing_amount * inr_exchangerate)
  Billed revenue excl tax USD   : SUM((billing_amount - COALESCE(transaction_tax,0)) * usd_exchangerate)
  Billed revenue excl tax INR   : SUM((billing_amount - COALESCE(transaction_tax,0)) * inr_exchangerate)
  Tax USD                       : SUM(COALESCE(transaction_tax,0) * usd_exchangerate)
  Tax INR                       : SUM(COALESCE(transaction_tax,0) * inr_exchangerate)
  Subscription USD              : SUM(subscriptionfee * usd_exchangerate)
  Implementation USD            : SUM(implementationfee * usd_exchangerate)
  Integration USD               : SUM(integrationfee * usd_exchangerate)
  Studio USD                    : SUM(studiofee * usd_exchangerate)
  Other services USD            : SUM((COALESCE(amsfee,0)+COALESCE(otherservicesfee,0)+COALESCE(openingsplitfee,0)) * usd_exchangerate)

SELECT * for billing returns these columns (in this order):
  transaction_id, transaction_number, transaction_type, transaction_currency_id,
  transaction_date, duedate, transaction_amount, transaction_amount_paid,
  transaction_amount_unpaid, transaction_tax, transaction_exchange_rate, memo,
  transaction_fy_quarter, inr_exchangerate, usd_exchangerate, customer_id,
  customer_ucc, customer_name, ucc_parent, entity_id, region, country,
  client_journey_stage, client_buckets, collection_status, subsidiary_id,
  subsidiary_name, paying_entity, currency_symbol, inter_company_status,
  billing_amount, subscriptionfee, implementationfee, integrationfee,
  studiofee, otherservicesfee, openingsplitfee, amsfee
"""


# ─────────────────────────────────────────────
# COLLECTIONS
# ─────────────────────────────────────────────

COLLECTIONS_CONTEXT = """
TABLE / VIEW: collections

Business purpose:
  Payment/collection data linked to invoices. Analyse collected amounts, collection
  timelines, ageing buckets, customers, regions, subsidiaries, and inter-company
  collections.

Grain: One row per payment-to-invoice link.

Default filters: inter_company_status = 'F' AND tds_flag = 'F'  (net, external only).
Default currency: INR.

─── COMPLETE COLUMN CATALOG ────────────────────────────────────────────────────
Identifier columns (never SELECT unless explicitly requested):
  transaction_id          — Internal ID of the collection/payment transaction.
  customer_id             — Internal customer ID.
  subsidiary_id           — Internal subsidiary ID.
  transaction_currency_id — Internal currency ID.

Dimension columns:
  transaction_number      — Human-readable transaction number.
  transaction_type        — CustPymt | Deposit | Journal.
  transaction_date        — Date of the payment / collection.
  duedate                 — Due date of the payment transaction.
  transaction_fy_quarter  — FY quarter of payment date (e.g. FY26 Q1).
  memo                    — Memo field (source for tds_flag).
  collection_due_date     — Due date of the linked invoice.
  customer_ucc            — Unique customer code.
  customer_name           — Customer company name.
  ucc_parent              — UCC of parent company.
  entity_id               — Customer entity ID.
  region                  — Mapped region of the customer.
  country                 — Country of the customer.
  client_journey_stage    — Churned | Customer Success | Implementation | One Time | Potential Churn
  client_buckets          — Churned Account | Non-Issue | Issue
  collection_status       — Collection follow-up status.
  subsidiary_name         — Name of billing entity / subsidiary.
  paying_entity           — Paying entity name (intercompany only).
  currency_symbol         — Symbol of transaction currency.
  inter_company_status    — T = intercompany, F = external.
  tds_flag                — T = TDS payment (memo contains 'tds'), F = regular.
  ageingbucket            — Pre-computed ageing relative to invoice due date.
    Values (in order): 'Within CP', '1-15 days', '16-30 days', '31-45 days',
                       '46-60 days', '61-90 days', '>90 days'

Raw amount columns (in transaction currency — always convert via exchange rate):
  transaction_amount        — Total of the payment transaction.
  transaction_amount_paid   — Amount paid.
  transaction_amount_unpaid — Amount unpaid.
  transaction_tax           — Tax on the transaction.
  collection_amount         — Amount applied to this specific invoice.
                              *** ALWAYS USE THIS for collection metrics, not transaction_amount ***

Exchange rate columns:
  inr_exchangerate          — Rate: transaction currency → INR.
  usd_exchangerate          — Rate: transaction currency → USD.
────────────────────────────────────────────────────────────────────────────────

METRIC CONVERSION RULES:
  Net collections INR (default) : SUM(collection_amount * inr_exchangerate)  [tds_flag='F' already in default filter]
  Net collections USD           : SUM(collection_amount * usd_exchangerate)
  Gross collections INR (TDS)   : SUM(collection_amount * inr_exchangerate)  [remove tds_flag filter]
  TDS amount INR                : SUM(collection_amount * inr_exchangerate) WHERE tds_flag = 'T'

SELECT * for collections returns these columns (in this order):
  transaction_id, transaction_number, transaction_type, transaction_currency_id,
  transaction_date, duedate, transaction_amount, transaction_amount_paid,
  transaction_amount_unpaid, transaction_tax, memo, transaction_fy_quarter,
  collection_due_date, collection_amount, inr_exchangerate, usd_exchangerate,
  customer_id, customer_ucc, customer_name, ucc_parent, entity_id, region,
  country, client_journey_stage, client_buckets, collection_status,
  subsidiary_id, subsidiary_name, paying_entity, currency_symbol,
  inter_company_status, tds_flag, ageingbucket
"""


# ─────────────────────────────────────────────
# ACCOUNTS RECEIVABLE (AR)
# ─────────────────────────────────────────────

AR_CONTEXT = """
TABLE / VIEW: ar

Business purpose:
  Open AR transactions — invoices, credit notes, and payments representing the net
  outstanding receivable position as of today.

Grain: One row per open transaction. open_amount is signed (positive = invoice,
       negative = credit/payment). SUM(open_amount) gives net AR naturally.

Default filter: inter_company_status = 'F'.
AR is a real-time snapshot — no time-period WHERE filtering.
transaction_fy_quarter is a GROUP BY dimension only (invoice creation quarter).
Default currency: USD.

─── COMPLETE COLUMN CATALOG ────────────────────────────────────────────────────
Identifier columns (never SELECT unless explicitly requested):
  transaction_id          — Internal ID.
  customer_id             — Internal customer ID.
  subsidiary_id           — Internal subsidiary ID.
  transaction_currency_id — Internal currency ID.

Dimension columns:
  transaction_number      — Human-readable transaction number.
  transaction_type        — CustInvc | CustCred | CustPymt | Deposit | Journal.
  transaction_date        — Date transaction was created.
  duedate                 — Due date of the invoice.
  transaction_fy_quarter  — FY quarter the transaction was raised. GROUP BY only — never WHERE.
  customer_ucc            — Unique customer code.
  customer_name           — Customer company name.
  ucc_parent              — UCC of parent company.
  entity_id               — Customer entity ID (use in customer-level reports).
  region                  — Mapped region of the customer.
  country                 — Country of the customer.
  client_journey_stage    — Churned | Customer Success | Implementation | One Time | Potential Churn
  client_buckets          — Churned Account | Non-Issue | Issue
  collection_status       — Collection follow-up status.
    Values: Acknowledged, Churned Account, Potential Churn, Agreement / Renewal,
            Implementation Issue / Implementation Delays, Invoice revision,
            Other Issues, Payment Date, Pending Acknowledgement, Product Issue
  subsidiary_name         — Name of billing entity / subsidiary.
  paying_entity           — Paying entity name (intercompany only).
  currency_symbol         — Symbol of transaction currency.
  inter_company_status    — T = intercompany, F = external.

Raw amount columns (in transaction currency — always convert via exchange rate):
  transaction_amount        — Total amount of the transaction.
  transaction_amount_paid   — Amount paid so far.
  transaction_amount_unpaid — Amount still outstanding.
  transaction_tax           — Tax on the transaction.

Computed columns (available directly, no conversion needed at row level):
  open_days   — CURRENT_DATE - COALESCE(duedate, transaction_date). Positive = overdue.
  open_amount — Net open amount in transaction currency. Positive=invoice, negative=credit.
                Always multiply by exchange rate for reporting.

Exchange rate columns:
  inr_exchangerate — Rate: transaction currency → INR.
  usd_exchangerate — Rate: transaction currency → USD.
────────────────────────────────────────────────────────────────────────────────

METRIC CONVERSION RULES:
  Net Outstanding USD : SUM(open_amount * usd_exchangerate)
  Net Outstanding INR : SUM(open_amount * inr_exchangerate)
  Overdue USD         : SUM(open_amount * usd_exchangerate) WHERE open_days >= 1
  Current USD         : SUM(open_amount * usd_exchangerate) WHERE open_days < 1

AGEING BUCKET DEFINITIONS (derive via CASE WHEN on open_days):
  Current   : open_days < 1
  1-30 days : open_days BETWEEN 1 AND 30
  31-60 days: open_days BETWEEN 31 AND 60
  61-90 days: open_days BETWEEN 61 AND 90
  91-180 days: open_days BETWEEN 91 AND 180
  >180 days : open_days > 180

SELECT * for ar returns these columns (in this order):
  transaction_id, transaction_number, transaction_type, transaction_currency_id,
  transaction_date, duedate, transaction_amount, transaction_amount_paid,
  transaction_amount_unpaid, transaction_tax, transaction_fy_quarter,
  inr_exchangerate, usd_exchangerate, customer_id, customer_ucc, customer_name,
  ucc_parent, entity_id, region, country, client_journey_stage, client_buckets,
  collection_status, subsidiary_id, subsidiary_name, paying_entity,
  currency_symbol, inter_company_status, open_days, open_amount
"""