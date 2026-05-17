# ─────────────────────────────────────────────────────────────────────────────
# SEMANTIC MODELS
# One model per domain: billing, collections, AR.
# Each model covers: defaults, metrics, dimensions, query patterns, SQL rules,
# display rules, and — critically — SUMMARY TABLE and DETAIL QUERY patterns
# that always use SELECT * to return all columns.
#
# COLUMN_DISPLAY_NAMES is imported from schema_context and rendered once here.
# It is embedded into every domain model so Claude always has the full lookup.
# Python imports the same dict directly as a fallback for any unknown aliases.
# ─────────────────────────────────────────────────────────────────────────────

from schema_context import render_column_display_names, render_currency_filter_rule, render_dimension_values

_DISPLAY_NAMES_BLOCK   = render_column_display_names()
_CURRENCY_FILTER_BLOCK = render_currency_filter_rule()
_DIMENSION_VALUES_BLOCK = render_dimension_values()


# ═════════════════════════════════════════════
# BILLING
# ═════════════════════════════════════════════

BILLING_SEMANTIC_MODEL = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BILLING SEMANTIC MODEL
Table: billing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DEFAULT RULES:
  - Default currency: USD. Use INR only when user asks.
  - All amount / tax / fee columns are in transaction currency.
    Convert to reporting currency using exchange rate columns.
  - Default filter: inter_company_status = 'F' (external customers only).
  - Intercompany: inter_company_status = 'T'.
  - No tds_flag in billing. Tax is handled via transaction_tax column arithmetic only.

{_CURRENCY_FILTER_BLOCK}

{_DIMENSION_VALUES_BLOCK}

────────────────────────────────────────────
TAX HANDLING:
────────────────────────────────────────────
  billing_amount (= transaction_amount) already INCLUDES tax.
  - Default (tax inclusive)   : SUM(billing_amount * rate)
  - "excluding tax" / "ex-tax": SUM((billing_amount - COALESCE(transaction_tax,0)) * rate)
  - "tax amount" / "show tax" : SUM(COALESCE(transaction_tax,0) * rate)
  Never filter rows for tax — use column arithmetic only.
  Always use COALESCE(transaction_tax, 0).

────────────────────────────────────────────
METRICS:
────────────────────────────────────────────
  1. Billed revenue (tax inclusive — DEFAULT):
       USD: SUM(billing_amount * usd_exchangerate)           AS billed_revenue_usd
       INR: SUM(billing_amount * inr_exchangerate)           AS billed_revenue_inr

  2. Billed revenue excluding tax:
       USD: SUM((billing_amount - COALESCE(transaction_tax,0)) * usd_exchangerate)  AS billed_revenue_excl_tax_usd
       INR: SUM((billing_amount - COALESCE(transaction_tax,0)) * inr_exchangerate)  AS billed_revenue_excl_tax_inr

  3. Tax amount:
       USD: SUM(COALESCE(transaction_tax,0) * usd_exchangerate)  AS tax_amount_usd
       INR: SUM(COALESCE(transaction_tax,0) * inr_exchangerate)  AS tax_amount_inr

  4. Subscription revenue:
       USD: SUM(subscriptionfee * usd_exchangerate)          AS subscription_revenue_usd
       INR: SUM(subscriptionfee * inr_exchangerate)          AS subscription_revenue_inr

  5. Implementation revenue:
       USD: SUM(implementationfee * usd_exchangerate)        AS implementation_revenue_usd
       INR: SUM(implementationfee * inr_exchangerate)        AS implementation_revenue_inr

  6. Integration revenue:
       USD: SUM(integrationfee * usd_exchangerate)           AS integration_revenue_usd
       INR: SUM(integrationfee * inr_exchangerate)           AS integration_revenue_inr

  7. Studio revenue:
       USD: SUM(studiofee * usd_exchangerate)                AS studio_revenue_usd
       INR: SUM(studiofee * inr_exchangerate)                AS studio_revenue_inr

  8. Other services revenue (AMS + other + opening split):
       USD: SUM((COALESCE(amsfee,0) + COALESCE(otherservicesfee,0) + COALESCE(openingsplitfee,0)) * usd_exchangerate)  AS other_services_revenue_usd
       INR: SUM((COALESCE(amsfee,0) + COALESCE(otherservicesfee,0) + COALESCE(openingsplitfee,0)) * inr_exchangerate)  AS other_services_revenue_inr

────────────────────────────────────────────
DIMENSIONS:
────────────────────────────────────────────
  customer / customer name / account    = customer_name
  entity id                             = entity_id
  customer ucc / ucc                    = customer_ucc
  parent / ucc parent                   = ucc_parent
  region / region wise                  = region
  country                               = country
  client journey / journey stage / CJS  = client_journey_stage
    Values: Churned, Customer Success, Implementation, One Time, Potential Churn
  client bucket / account health        = client_buckets
    Values: Churned Account, Non-Issue, Issue
  collection status                     = collection_status
  quarter / QoQ / quarterly             = transaction_fy_quarter
  currency / transaction currency       = currency_symbol
  subsidiary / billing entity           = subsidiary_name
  paying entity / billed entity         = paying_entity  (intercompany only)
  transaction type / payment type    = transaction_type  (CustInvc = invoice, CustCred = credit note)
    NOTE: "invoice type" does NOT map here — it triggers the TYPE SPLIT (fee breakdown).
  transaction date / billing date       = transaction_date
  due date                              = duedate
  transaction number / invoice number   = transaction_number

DIMENSION VALIDATION — only these may appear in GROUP BY:
  customer_name, entity_id, customer_ucc, ucc_parent,
  region, country, client_journey_stage, client_buckets,
  collection_status, transaction_fy_quarter, currency_symbol,
  subsidiary_name, paying_entity, transaction_type,
  transaction_date, duedate, transaction_number

ID COLUMN RULES:
  Never SELECT customer_id, transaction_id, subsidiary_id,
  transaction_currency_id unless explicitly requested.

NULL CUSTOMER RULE:
  When GROUP BY includes any customer dimension (customer_name, customer_ucc,
  entity_id, ucc_parent), ALWAYS add to WHERE:
    AND customer_name IS NOT NULL
  Applies to: top N customers, billing by customer, any pivot with a customer
  dimension, and detail queries filtered by customer.
  Do NOT add for overall / aggregate queries with no customer GROUP BY.

────────────────────────────────────────────
TIME RULES:
────────────────────────────────────────────
  Use transaction_fy_quarter for all FY and quarter filtering.
  Available data: FY25, FY26, FY27 (YTD).  Format: 'FY26 Q1', 'FY27 Q2'.
  - No time mentioned (DEFAULT)  → transaction_fy_quarter LIKE '<current_fy>%'
  - "last year" / "FY26"         → transaction_fy_quarter LIKE '<previous_fy>%'
  - "FY25" / "two years ago"     → transaction_fy_quarter LIKE '<two_years_ago_fy>%'
  - "this quarter"               → transaction_fy_quarter = '<current_quarter>'
  - "last quarter"               → transaction_fy_quarter = '<last_quarter>'
  - "all time" / "all years"     → no time filter
  - "by year"                    → GROUP BY LEFT(transaction_fy_quarter, 4) AS fy_year
  - "by quarter" / "QoQ"         → GROUP BY transaction_fy_quarter
  Use transaction_date only for custom date ranges not expressible as FY / quarter.

────────────────────────────────────────────
TYPE SPLIT RULES:
────────────────────────────────────────────
  TRIGGERS — any of these phrases activates the fee type split:
    "invoice type", "by invoice type", "type split", "invoice type split",
    "revenue split", "revenue by type", "fee split", "fee breakdown",
    "billing by type", "split by type", "type of billing", "types of revenue"

  CRITICAL: "invoice type" means the fee/revenue category split
  (subscription, implementation, etc.) — NOT transaction_type (CustInvc/CustCred).
  Never GROUP BY transaction_type when these triggers are used.

  ALWAYS include ALL of these fee metrics (STRICT_METRIC_SELECTION_RULES does NOT apply):
    - subscription revenue   (subscriptionfee * usd_exchangerate)
    - implementation revenue (implementationfee * usd_exchangerate)
    - integration revenue    (integrationfee * usd_exchangerate)
    - studio revenue         (studiofee * usd_exchangerate)
    - other services revenue (amsfee + otherservicesfee + openingsplitfee) * usd_exchangerate
    - tax amount             (COALESCE(transaction_tax,0) * usd_exchangerate)
  visualization = "pivot_table", pivot_type = "metric"
  rows = [dimension] if user specifies a dimension, else rows = []

────────────────────────────────────────────
SUMMARY TABLE:
────────────────────────────────────────────
  Triggers: "show billing table", "billing summary", "show all billing columns",
  "show me billing data", "billing raw data", "full billing table", "all billing rows",
  "billing details" (without a specific customer), "list billing transactions",
  "show billing", "export billing"

  - ALWAYS use SELECT * — never list individual columns.
  - Apply default filters + optional time filter.
  - Default LIMIT 100 unless user specifies otherwise.
  - visualization = "table"
  - display.columns must map key aliases to clean names; unknown columns are shown as-is.

  SQL template:
    SELECT *
    FROM billing
    WHERE inter_company_status = 'F'
      AND transaction_fy_quarter LIKE '<current_fy>%'   -- default time filter
    LIMIT 100

  User specifies customer → use DETAIL QUERY pattern below instead.
  User says "all rows" / "no limit" → omit LIMIT.
  User says "intercompany" → swap inter_company_status = 'T'.

────────────────────────────────────────────
DETAIL QUERY (customer-specific):
────────────────────────────────────────────
  Triggers: "show billing for [customer]", "list invoices for [customer]",
  "billing data for [customer]", "show transactions for [customer]",
  "invoices for top customer"

  - ALWAYS use SELECT * — never list individual columns.
  - visualization = "table"
  - No GROUP BY, no aggregation, no Row %, no Grand Total.
  - Use ILIKE for name filtering; = for exact match from subquery.
  - Default: no LIMIT on outer query unless user specifies.

  Simple lookup:
    SELECT *
    FROM billing
    WHERE inter_company_status = 'F'
      AND customer_name ILIKE '%XYZ%'

  Derived (e.g. "transactions for top customer"):
    WITH derived AS (
      SELECT customer_name FROM billing
      WHERE inter_company_status = 'F'
      GROUP BY customer_name
      ORDER BY SUM(billing_amount * usd_exchangerate) DESC LIMIT 1
    )
    SELECT *
    FROM billing
    WHERE inter_company_status = 'F'
      AND customer_name = (SELECT customer_name FROM derived)

────────────────────────────────────────────
SORTING & LIMIT RULES:
────────────────────────────────────────────
  - Do NOT add ORDER BY to SQL. Python handles all sorting.
  - Exception: top N / bottom N → add ORDER BY alias DESC/ASC + LIMIT N.
  - Top N without number → default LIMIT 10.
  - Full breakdowns → no LIMIT.

────────────────────────────────────────────
SQL OPTIMISATION RULES:
────────────────────────────────────────────
  - No ORDER BY unless top N. Python sorts.
  - Never repeat SUM expressions; use SELECT aliases.
  - All metric aliases MUST include currency suffix: _usd or _inr.
  - Display names must NOT include currency suffix in brackets.
  - Keep SQL minimal: SELECT, FROM, WHERE, GROUP BY only.

────────────────────────────────────────────
NAMED DASHBOARD REPORTS:
────────────────────────────────────────────
  These are pre-defined report patterns. Match trigger phrases exactly and
  generate the specified SQL + visualization every time.

  ── 1. QoQ / YoY REVENUE TREND ───────────────────────────────────────────
  Triggers: "billing trend", "revenue trend", "QoQ billing", "quarterly trend",
            "billing by quarter", "YoY billing", "billing over time",
            "quarterly billing", "billing trend by quarter"

  visualization: line_chart
  x_axis: transaction_fy_quarter
  Default: current FY quarters. "last 3 years" / "all time" → remove time filter.
  "by year" → GROUP BY LEFT(transaction_fy_quarter,4) AS fy_year, use bar_chart.

  SQL (current FY default):
    SELECT
        transaction_fy_quarter,
        SUM(billing_amount * usd_exchangerate) AS billed_revenue_usd
    FROM billing
    WHERE inter_company_status = 'F'
      AND transaction_fy_quarter LIKE '<current_fy>%'
    GROUP BY transaction_fy_quarter

  display:
    title: "Billing Trend - <FY>"
    columns: {{ "transaction_fy_quarter": "Quarter", "billed_revenue_usd": "Billed Revenue" }}
    formatting: {{ "billed_revenue_usd": {{ "type": "currency", "currency": "USD", "decimals": 0 }} }}

  ── 2. TOP 10 CUSTOMERS ───────────────────────────────────────────────────
  Triggers: "top 10 customers", "top customers", "top 10 by billing",
            "largest customers", "biggest customers", "top customers by revenue",
            "top 10 accounts", "highest billing customers"

  visualization: bar_chart
  orientation: horizontal (largest at top)
  Default: current FY, external only, customer_name IS NOT NULL.
  N is configurable — "top 5" → LIMIT 5, "top 20" → LIMIT 20.

  SQL:
    SELECT
        customer_name,
        SUM(billing_amount * usd_exchangerate) AS billed_revenue_usd
    FROM billing
    WHERE inter_company_status = 'F'
      AND transaction_fy_quarter LIKE '<current_fy>%'
      AND customer_name IS NOT NULL
    GROUP BY customer_name
    ORDER BY billed_revenue_usd DESC
    LIMIT 10

  display:
    title: "Top 10 Customers by Billing - <FY>"
    columns: {{ "customer_name": "Customer", "billed_revenue_usd": "Billed Revenue" }}
    formatting: {{ "billed_revenue_usd": {{ "type": "currency", "currency": "USD", "decimals": 0 }} }}

  ── 3. BILLING BY CURRENCY ────────────────────────────────────────────────
  Triggers: "billing by currency", "revenue by currency", "currency breakdown",
            "billing currency split", "billing per currency",
            "which currencies are we billing in", "currency wise billing"

  visualization: bar_chart
  Default: current FY, external only.

  SQL:
    SELECT
        currency_symbol,
        SUM(billing_amount * usd_exchangerate)                              AS billed_revenue_usd,
        SUM((billing_amount - COALESCE(transaction_tax,0)) * usd_exchangerate) AS billed_revenue_excl_tax_usd
    FROM billing
    WHERE inter_company_status = 'F'
      AND transaction_fy_quarter LIKE '<current_fy>%'
    GROUP BY currency_symbol

  display:
    title: "Billing by Currency - <FY>"
    columns: {{ "currency_symbol": "Currency", "billed_revenue_usd": "Billed Revenue",
                "billed_revenue_excl_tax_usd": "Billed Revenue (Ex-Tax)" }}
    formatting: both amount cols → type: currency, currency: USD, decimals: 0

  ── 4. INVOICE TYPE SPLIT ─────────────────────────────────────────────────
  Triggers: "invoice type split", "billing type split", "revenue split",
            "fee split", "type of billing", "revenue by type",
            "subscription vs implementation", "billing breakdown by type"
  (See also TYPE SPLIT RULES above for dimension variants)

  visualization: pivot_table, pivot_type: metric
  rows: [] (no dimension) unless user specifies one
  Default: current FY, external only.

  SQL (no dimension):
    SELECT
        SUM(subscriptionfee    * usd_exchangerate)                                                AS subscription_revenue_usd,
        SUM(implementationfee  * usd_exchangerate)                                                AS implementation_revenue_usd,
        SUM(integrationfee     * usd_exchangerate)                                                AS integration_revenue_usd,
        SUM(studiofee          * usd_exchangerate)                                                AS studio_revenue_usd,
        SUM((COALESCE(amsfee,0)+COALESCE(otherservicesfee,0)+COALESCE(openingsplitfee,0)) * usd_exchangerate) AS other_services_revenue_usd,
        SUM(COALESCE(transaction_tax,0) * usd_exchangerate)                                       AS tax_amount_usd
    FROM billing
    WHERE inter_company_status = 'F'
      AND transaction_fy_quarter LIKE '<current_fy>%'

  With dimension (e.g. "by region"):
    Add dimension to SELECT + GROUP BY. Keep same 6 metrics + tax.
    rows: ["region"] (or whichever dimension)

  display:
    title: "Billing by Invoice Type - <FY>"
    metric_columns: [subscription_revenue_usd, implementation_revenue_usd,
                     integration_revenue_usd, studio_revenue_usd,
                     other_services_revenue_usd, tax_amount_usd]
    formatting: all → type: currency, currency: USD, decimals: 0

  ── 5. REVENUE BY REGION / SUBSIDIARY ────────────────────────────────────
  Triggers: "billing by region", "revenue by region", "region wise billing",
            "billing by subsidiary", "revenue by subsidiary", "entity wise billing",
            "billing by billing entity", "subsidiary breakdown",
            "region breakdown", "which region bills the most"

  visualization: bar_chart
  Dimension: region (default) or subsidiary_name if user says "subsidiary"/"entity"
  Default: current FY, external only.

  SQL (by region):
    SELECT
        region,
        SUM(billing_amount * usd_exchangerate) AS billed_revenue_usd
    FROM billing
    WHERE inter_company_status = 'F'
      AND transaction_fy_quarter LIKE '<current_fy>%'
    GROUP BY region

  SQL (by subsidiary):
    SELECT
        subsidiary_name,
        SUM(billing_amount * usd_exchangerate) AS billed_revenue_usd
    FROM billing
    WHERE inter_company_status = 'F'
      AND transaction_fy_quarter LIKE '<current_fy>%'
    GROUP BY subsidiary_name

  display (region):
    title: "Billing by Region - <FY>"
    columns: {{ "region": "Region", "billed_revenue_usd": "Billed Revenue" }}
  display (subsidiary):
    title: "Billing by Billing Entity - <FY>"
    columns: {{ "subsidiary_name": "Billing Entity", "billed_revenue_usd": "Billed Revenue" }}
  formatting: billed_revenue_usd → type: currency, currency: USD, decimals: 0

────────────────────────────────────────────
OTHER REPORTS (ad hoc):
────────────────────────────────────────────
  - YTD total billing         : single-row KPI, SUM(billing_amount * usd_exchangerate)
  - Billing by client bucket  : GROUP BY client_buckets
  - Billing by customer journey : GROUP BY client_journey_stage
  - Intercompany billing      : inter_company_status='T', pivot subsidiary_name × paying_entity
  - Billing summary table     : SELECT * with default filters (see SUMMARY TABLE above)

────────────────────────────────────────────
DISPLAY RULES:
────────────────────────────────────────────
  - display.title: short, report-like.
  - display.currency: USD (or INR if user asks).
  - display.columns: always use the COLUMN DISPLAY NAMES lookup below.
    For any alias not in the list, Python will auto-format it as a fallback.
  - display.formatting: define currency type for all amount columns.

{_DISPLAY_NAMES_BLOCK}
"""


# ═════════════════════════════════════════════
# COLLECTIONS
# ═════════════════════════════════════════════

COLLECTIONS_SEMANTIC_MODEL = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COLLECTIONS SEMANTIC MODEL
Table: collections
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DEFAULT RULES:
  - Default currency: INR. Use USD only when user asks.
  - collection_amount is in transaction currency. Always convert using exchange rates.
  - Default filters: inter_company_status = 'F' AND tds_flag = 'F' (net, external only).
  - TDS excluded by default. Override only when user says "including TDS" or "gross collections".
  - Intercompany: inter_company_status = 'T'.

{_CURRENCY_FILTER_BLOCK}

{_DIMENSION_VALUES_BLOCK}

────────────────────────────────────────────
TDS HANDLING:
────────────────────────────────────────────
  "TDS deducted" / "net" / "excluding TDS" → default (tds_flag = 'F')
  "including TDS" / "gross" / "with TDS"   → remove tds_flag filter entirely
  "TDS amount" / "only TDS"                → WHERE tds_flag = 'T'
  "total and TDS" / "show both"            → two metrics: net (tds='F') + TDS (tds='T')

────────────────────────────────────────────
METRICS:
────────────────────────────────────────────
  CRITICAL: Always use collection_amount — NEVER transaction_amount — for collection metrics.

  1. Net collections (DEFAULT — TDS excluded):
       INR: SUM(collection_amount * inr_exchangerate)  AS collection_inr
       USD: SUM(collection_amount * usd_exchangerate)  AS collection_usd
       (tds_flag = 'F' already in default filter)

  2. Gross collections (user must explicitly ask):
       INR: SUM(collection_amount * inr_exchangerate)  AS gross_collection_inr
       USD: SUM(collection_amount * usd_exchangerate)  AS gross_collection_usd
       (remove tds_flag filter)

  3. TDS amount only:
       INR: SUM(collection_amount * inr_exchangerate)  AS tds_amount_inr   WHERE tds_flag = 'T'
       USD: SUM(collection_amount * usd_exchangerate)  AS tds_amount_usd   WHERE tds_flag = 'T'

────────────────────────────────────────────
DIMENSIONS:
────────────────────────────────────────────
  customer / customer name / account    = customer_name
  entity id                             = entity_id
  customer ucc / ucc                    = customer_ucc
  parent / ucc parent                   = ucc_parent
  region / region wise                  = region
  country                               = country
  client journey / journey stage / CJS  = client_journey_stage
    Values: Churned, Customer Success, Implementation, One Time, Potential Churn
  client bucket / account health        = client_buckets
    Values: Churned Account, Non-Issue, Issue
  collection status                     = collection_status
  quarter / QoQ / quarterly             = transaction_fy_quarter
  currency / transaction currency       = currency_symbol
  subsidiary / billing entity           = subsidiary_name
  paying entity / billed entity         = paying_entity  (intercompany only)
  transaction type / type               = transaction_type
  transaction date / payment date       = transaction_date
  due date                              = duedate
  collection due date / invoice due     = collection_due_date
  transaction number                    = transaction_number
  ageing bucket                         = ageingbucket  (pre-computed — GROUP BY directly)

ID COLUMN RULES:
  Never SELECT customer_id, transaction_id, subsidiary_id,
  transaction_currency_id unless explicitly requested.

NULL CUSTOMER RULE:
  When GROUP BY includes any customer dimension (customer_name, customer_ucc,
  entity_id, ucc_parent), ALWAYS add to WHERE:
    AND customer_name IS NOT NULL
  Applies to: top N customers, collections by customer, any pivot with a customer
  dimension, and detail queries filtered by customer.
  Do NOT add for overall / aggregate queries with no customer GROUP BY.

────────────────────────────────────────────
AGEING BUCKET RULES:
────────────────────────────────────────────
  ageingbucket is pre-computed in the view. GROUP BY ageingbucket directly.
  Valid values and display order:
    'Within CP' → '1-15 days' → '16-30 days' → '31-45 days' →
    '46-60 days' → '61-90 days' → '>90 days'
  Never sort ageingbucket alphabetically. Use Python AGEING_ORDER for sorting.

────────────────────────────────────────────
TIME RULES:
────────────────────────────────────────────
  Use transaction_fy_quarter (payment date quarter) for all FY / quarter filtering.
  Available data: FY25, FY26, FY27 (YTD).
  - No time mentioned (DEFAULT)  → transaction_fy_quarter LIKE '<current_fy>%'
  - "last year" / "FY26"         → transaction_fy_quarter LIKE '<previous_fy>%'
  - "FY25" / "two years ago"     → transaction_fy_quarter LIKE '<two_years_ago_fy>%'
  - "this quarter"               → transaction_fy_quarter = '<current_quarter>'
  - "last quarter"               → transaction_fy_quarter = '<last_quarter>'
  - "all time" / "all years"     → no time filter
  - "by year"                    → GROUP BY LEFT(transaction_fy_quarter, 4) AS fy_year
  - "by quarter" / "QoQ"         → GROUP BY transaction_fy_quarter
  Use transaction_date only for custom date ranges.

────────────────────────────────────────────
SUMMARY TABLE:
────────────────────────────────────────────
  Triggers: "show collections table", "collections summary", "show all collections columns",
  "show me collections data", "collections raw data", "full collections table",
  "all collections rows", "collections details" (without a specific customer),
  "list collections", "list payments", "show collections", "export collections"

  - ALWAYS use SELECT * — never list individual columns.
  - Apply default filters + optional time filter.
  - Default LIMIT 100 unless user specifies otherwise.
  - visualization = "table"

  SQL template:
    SELECT *
    FROM collections
    WHERE inter_company_status = 'F'
      AND tds_flag = 'F'
      AND transaction_fy_quarter LIKE '<current_fy>%'   -- default time filter
    LIMIT 100

  User specifies customer → use DETAIL QUERY pattern below instead.
  User says "all rows" / "no limit" → omit LIMIT.
  User says "including TDS" → remove tds_flag filter.

────────────────────────────────────────────
DETAIL QUERY (customer-specific):
────────────────────────────────────────────
  Triggers: "show collections for [customer]", "list payments for [customer]",
  "collections data for [customer]"

  - ALWAYS use SELECT * — never list individual columns.
  - visualization = "table"
  - No GROUP BY, no aggregation.
  - Default filters: inter_company_status = 'F' AND tds_flag = 'F'
  - Use ILIKE for name filtering.
  - No LIMIT on outer query unless user specifies.

  SQL template:
    SELECT *
    FROM collections
    WHERE inter_company_status = 'F'
      AND tds_flag = 'F'
      AND customer_name ILIKE '%XYZ%'

────────────────────────────────────────────
SORTING & LIMIT RULES:
────────────────────────────────────────────
  - Do NOT add ORDER BY to SQL. Python handles all sorting.
  - Exception: top N / bottom N → ORDER BY alias DESC/ASC + LIMIT N.
  - Top N without number → default LIMIT 10.
  - Full breakdowns → no LIMIT.

────────────────────────────────────────────
SQL OPTIMISATION RULES:
────────────────────────────────────────────
  - No ORDER BY unless top N. Python sorts.
  - Never repeat SUM expressions; use SELECT aliases.
  - All metric aliases MUST include currency suffix: _inr or _usd.
  - Display names must NOT include currency suffix in brackets.
  - Keep SQL minimal: SELECT, FROM, WHERE, GROUP BY only.

────────────────────────────────────────────
COMMON DASHBOARD REPORTS:
────────────────────────────────────────────
  1.  YTD Collections           : SUM(collection_amount * inr_exchangerate), current FY
  2.  QoQ Collections           : GROUP BY transaction_fy_quarter
  3.  Collections by Ageing     : GROUP BY ageingbucket
  4.  Collections by Region     : GROUP BY region
  5.  Collections by Subsidiary : GROUP BY subsidiary_name
  6.  Collections by Customer   : GROUP BY customer_name (top 10 default)
  7.  Collections by Currency   : GROUP BY currency_symbol
  8.  Collections by Client Bucket     : GROUP BY client_buckets
  9.  Collections by Customer Journey  : GROUP BY client_journey_stage
  10. Intercompany Collections   : inter_company_status='T', tds_flag='F'
      visualization = pivot_table, pivot_type = dimension
      rows = [subsidiary_name], columns = [paying_entity]
      values = [collection_inr]              ← single metric (default)
      values = [collection_inr, collection_usd]  ← when user asks for both currencies
      SQL must SELECT all values listed. The frontend renders multiple values as
      grouped column headers (top = paying entity, sub = INR / USD).
      SQL: SELECT subsidiary_name, TRIM(paying_entity) AS paying_entity,
               SUM(collection_amount * inr_exchangerate) AS collection_inr,
               SUM(collection_amount * usd_exchangerate) AS collection_usd  ← only if requested
           FROM collections WHERE inter_company_status='T' AND tds_flag='F'
           GROUP BY subsidiary_name, TRIM(paying_entity)
  11. Cumulative Ageing by Quarter : dimension pivot rows=transaction_fy_quarter cols=ageingbucket
  12. Collections Summary Table  : SELECT * with default filters (see SUMMARY TABLE above)

────────────────────────────────────────────
DISPLAY RULES:
────────────────────────────────────────────
  - display.title: short, report-like.
  - display.currency: INR (or USD if user asks).
  - display.columns: always use the COLUMN DISPLAY NAMES lookup below.
    For any alias not in the list, Python will auto-format it as a fallback.
  - display.formatting: define currency type for all amount columns.

{_DISPLAY_NAMES_BLOCK}
"""


# ═════════════════════════════════════════════
# ACCOUNTS RECEIVABLE (AR)
# ═════════════════════════════════════════════

AR_SEMANTIC_MODEL = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AR SEMANTIC MODEL
Table: ar
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DEFAULT RULES:
  - Default currency: USD. Use INR only when user asks.
  - open_amount is in transaction currency. Always convert using exchange rate columns.
  - Default filter: inter_company_status = 'F'.
  - AR is a real-time snapshot as of today. Do NOT add time-period WHERE filters.
  - transaction_fy_quarter is a GROUP BY dimension only (invoice creation quarter) — NEVER use in WHERE.
  - open_amount is signed: positive = invoice, negative = credit / payment.
    SUM(open_amount * rate) gives net AR position naturally.
  - No tds_flag in AR.

{_CURRENCY_FILTER_BLOCK}

{_DIMENSION_VALUES_BLOCK}

────────────────────────────────────────────
DEFAULT METRIC BEHAVIOUR:
────────────────────────────────────────────
  User says "AR" / "receivables" / "open AR" / "how much is owed" / no metric
    → BOTH outstanding_usd AND overdue_usd

  User says "outstanding" (without also saying "AR" / "receivables")
    → ONLY outstanding_usd

  User says "overdue" / "past due"
    → ONLY overdue_usd

  User says "current" / "not yet due"
    → ONLY current_usd

  Ageing bucket queries override the above — use bucket metrics instead.
  KPI / summary queries always include all relevant metrics regardless.

────────────────────────────────────────────
METRICS:
────────────────────────────────────────────
  1. Net Outstanding / Total AR / Open AR:
       USD: SUM(open_amount * usd_exchangerate)  AS outstanding_usd
       INR: SUM(open_amount * inr_exchangerate)  AS outstanding_inr

  2. Gross Outstanding (invoices only):
       USD: SUM(open_amount * usd_exchangerate)  AS outstanding_usd
            WHERE transaction_type = 'CustInvc'

  3. Amount Overdue:
       USD: SUM(CASE WHEN open_days >= 1 THEN open_amount * usd_exchangerate ELSE 0 END)  AS overdue_usd
       INR: SUM(CASE WHEN open_days >= 1 THEN open_amount * inr_exchangerate ELSE 0 END)  AS overdue_inr

  4. Amount Current (not yet due):
       USD: SUM(CASE WHEN open_days < 1 THEN open_amount * usd_exchangerate ELSE 0 END)  AS current_usd
       INR: SUM(CASE WHEN open_days < 1 THEN open_amount * inr_exchangerate ELSE 0 END)  AS current_inr

  5. Invoice Count:
       COUNT(DISTINCT transaction_id)  AS invoice_count

  DUAL-METRIC SQL PATTERN (default for most AR by dimension queries):
    SELECT
        <dimension>,
        SUM(open_amount * usd_exchangerate)                                              AS outstanding_usd,
        SUM(CASE WHEN open_days >= 1 THEN open_amount * usd_exchangerate ELSE 0 END)    AS overdue_usd
    FROM ar
    WHERE inter_company_status = 'F'
      AND customer_name IS NOT NULL   -- when grouping by customer dimension
    GROUP BY <dimension>

AGEING BUCKET METRICS (metric pivot / wide format — USD default):
  bucket_current_usd    : SUM(CASE WHEN open_days < 1               THEN open_amount * usd_exchangerate ELSE 0 END)
  bucket_1_30_usd       : SUM(CASE WHEN open_days BETWEEN 1 AND 30  THEN open_amount * usd_exchangerate ELSE 0 END)
  bucket_31_60_usd      : SUM(CASE WHEN open_days BETWEEN 31 AND 60 THEN open_amount * usd_exchangerate ELSE 0 END)
  bucket_61_90_usd      : SUM(CASE WHEN open_days BETWEEN 61 AND 90 THEN open_amount * usd_exchangerate ELSE 0 END)
  bucket_91_180_usd     : SUM(CASE WHEN open_days BETWEEN 91 AND 180 THEN open_amount * usd_exchangerate ELSE 0 END)
  bucket_over_180_usd   : SUM(CASE WHEN open_days > 180             THEN open_amount * usd_exchangerate ELSE 0 END)

  Display names for ageing buckets:
    bucket_current_usd   → "Current"
    bucket_1_30_usd      → "1-30 Days"
    bucket_31_60_usd     → "31-60 Days"
    bucket_61_90_usd     → "61-90 Days"
    bucket_91_180_usd    → "91-180 Days"
    bucket_over_180_usd  → ">180 Days"

────────────────────────────────────────────
DIMENSIONS:
────────────────────────────────────────────
  customer / customer name / account      = customer_name
  entity id / customer entity             = entity_id
  customer ucc / ucc                      = customer_ucc
  parent / ucc parent                     = ucc_parent
  region / region wise                    = region
  country                                 = country
  client journey / journey stage / CJS    = client_journey_stage
    Values: Churned, Customer Success, Implementation, One Time, Potential Churn
  client bucket / account health / bucket = client_buckets
    Values: Churned Account, Non-Issue, Issue
  collection status / follow-up status    = collection_status
  billing entity / subsidiary             = subsidiary_name
  paying entity                           = paying_entity  (intercompany only)
  currency / transaction currency         = currency_symbol
  transaction type / type                 = transaction_type
  transaction quarter / invoice quarter   = transaction_fy_quarter  (GROUP BY only)
  transaction date / invoice date         = transaction_date
  due date                                = duedate
  ageing bucket                           = derived via CASE WHEN on open_days

DIMENSION VALIDATION — only these may appear in GROUP BY:
  customer_name, entity_id, customer_ucc, ucc_parent,
  region, country, client_journey_stage, client_buckets,
  collection_status, subsidiary_name, paying_entity,
  currency_symbol, transaction_type, transaction_fy_quarter,
  transaction_date, duedate, ageing_bucket (derived)

ID COLUMN RULES:
  Never SELECT customer_id, transaction_id, subsidiary_id,
  transaction_currency_id unless explicitly requested.

NULL CUSTOMER RULE:
  When GROUP BY includes any customer dimension (customer_name, customer_ucc,
  entity_id, ucc_parent), ALWAYS add to WHERE:
    AND customer_name IS NOT NULL
  Applies to: top N customers, AR by customer, AR aging summary, any pivot with
  a customer dimension, and detail queries filtered by customer.
  Do NOT add for overall / aggregate queries with no customer GROUP BY.

────────────────────────────────────────────
AGEING BUCKET QUERY RULES:
────────────────────────────────────────────
  Bucket as row dimension (long format):
    SELECT
      CASE
        WHEN open_days < 1              THEN 'Current'
        WHEN open_days BETWEEN 1 AND 30  THEN '1-30 days'
        WHEN open_days BETWEEN 31 AND 60 THEN '31-60 days'
        WHEN open_days BETWEEN 61 AND 90 THEN '61-90 days'
        WHEN open_days BETWEEN 91 AND 180 THEN '91-180 days'
        WHEN open_days > 180             THEN '>180 days'
      END AS ageing_bucket,
      SUM(open_amount * usd_exchangerate) AS outstanding_usd
    FROM ar
    WHERE inter_company_status = 'F'
    GROUP BY ageing_bucket

  Bucket as columns (metric pivot):
    visualization = "pivot_table", pivot_type = "metric"
    rows = [dimension], metric_columns = [bucket_current_usd, bucket_1_30_usd, ...]
    Ageing bucket display order: Current → 1-30 → 31-60 → 61-90 → 91-180 → >180

────────────────────────────────────────────
AR AGING SUMMARY REPORT:
────────────────────────────────────────────
  Trigger: "AR aging summary", "AR summary", "aging summary", "AR report"
  visualization = "table"
  CRITICAL: Use entity_id. Do NOT use subsidiary_id or subsidiary_name as a row key.

  SQL:
    SELECT
        entity_id,
        customer_name,
        client_buckets,
        collection_status,
        client_journey_stage,
        SUM(CASE WHEN open_days < 1              THEN open_amount * usd_exchangerate ELSE 0 END) AS bucket_current_usd,
        SUM(CASE WHEN open_days BETWEEN 1 AND 30  THEN open_amount * usd_exchangerate ELSE 0 END) AS bucket_1_30_usd,
        SUM(CASE WHEN open_days BETWEEN 31 AND 60 THEN open_amount * usd_exchangerate ELSE 0 END) AS bucket_31_60_usd,
        SUM(CASE WHEN open_days BETWEEN 61 AND 90 THEN open_amount * usd_exchangerate ELSE 0 END) AS bucket_61_90_usd,
        SUM(CASE WHEN open_days BETWEEN 91 AND 180 THEN open_amount * usd_exchangerate ELSE 0 END) AS bucket_91_180_usd,
        SUM(CASE WHEN open_days > 180             THEN open_amount * usd_exchangerate ELSE 0 END) AS bucket_over_180_usd,
        SUM(open_amount * usd_exchangerate) AS total_outstanding_usd,
        SUM(CASE WHEN open_days >= 1 THEN open_amount * usd_exchangerate ELSE 0 END) AS total_overdue_usd
    FROM ar
    WHERE inter_company_status = 'F'
    GROUP BY entity_id, customer_name, client_buckets, collection_status, client_journey_stage

  display.columns:
    entity_id             → "Entity ID"
    customer_name         → "Customer"
    client_buckets        → "Client Bucket"
    collection_status     → "Collection Status"
    client_journey_stage  → "Customer Journey"
    bucket_current_usd    → "Current"
    bucket_1_30_usd       → "1-30 Days"
    bucket_31_60_usd      → "31-60 Days"
    bucket_61_90_usd      → "61-90 Days"
    bucket_91_180_usd     → "91-180 Days"
    bucket_over_180_usd   → ">180 Days"
    total_outstanding_usd → "Total Outstanding"
    total_overdue_usd     → "Total Overdue"
  display.formatting: currency (USD) for all bucket and total columns.
  Sort by total_outstanding_usd DESC.

────────────────────────────────────────────
AR KPI REPORT:
────────────────────────────────────────────
  Triggers: "AR KPIs", "AR overview", "AR dashboard", "show me AR summary"
  ONE row with all key KPIs.

  SQL:
    SELECT
        SUM(open_amount * usd_exchangerate) AS total_outstanding_usd,
        SUM(CASE WHEN open_days >= 1 THEN open_amount * usd_exchangerate ELSE 0 END) AS total_overdue_usd,
        SUM(CASE WHEN client_buckets = 'Issue'            THEN open_amount * usd_exchangerate ELSE 0 END) AS outstanding_issue_usd,
        SUM(CASE WHEN client_buckets = 'Non-Issue'        THEN open_amount * usd_exchangerate ELSE 0 END) AS outstanding_non_issue_usd,
        SUM(CASE WHEN client_journey_stage = 'Customer Success'  THEN open_amount * usd_exchangerate ELSE 0 END) AS outstanding_cs_usd,
        SUM(CASE WHEN client_journey_stage = 'Implementation'    THEN open_amount * usd_exchangerate ELSE 0 END) AS outstanding_impl_usd,
        SUM(CASE WHEN client_journey_stage = 'Potential Churn'   THEN open_amount * usd_exchangerate ELSE 0 END) AS outstanding_churn_usd
    FROM ar WHERE inter_company_status = 'F'

  display.columns: Total Outstanding, Total Overdue, Outstanding - Issue,
    Outstanding - Non-Issue, Outstanding - Customer Success,
    Outstanding - Implementation, Outstanding - Potential Churn
  visualization = "table"  (frontend renders as KPI cards — single row, multiple metrics)

────────────────────────────────────────────
DUAL-METRIC TABLE PATTERN (Outstanding + Overdue + Ratio):
────────────────────────────────────────────
  Use this CTE pattern for AR by dimension reports:

    WITH base AS (
        SELECT
            <dimension>,
            SUM(open_amount * usd_exchangerate) AS outstanding_usd,
            SUM(CASE WHEN open_days >= 1 THEN open_amount * usd_exchangerate ELSE 0 END) AS overdue_usd
        FROM ar
        WHERE inter_company_status = 'F'
        GROUP BY <dimension>
    )
    SELECT
        <dimension>,
        outstanding_usd,
        overdue_usd,
        ROUND(overdue_usd / NULLIF(outstanding_usd, 0), 3) AS overdue_pct_of_outstanding
    FROM base
    -- overdue_pct_of_outstanding is a decimal (0.773 = 77.3%). Frontend formats as {{x:.1%}}.

  display.columns:
    outstanding_usd             → "Amount Outstanding"
    overdue_usd                 → "Amount Overdue"
    overdue_pct_of_outstanding  → "Overdue as % of Outstanding"
  display.formatting:
    outstanding_usd / overdue_usd → type: currency, currency: USD
    overdue_pct_of_outstanding    → type: percentage, decimals: 1
  visualization = "table"

  Apply this pattern to:
    AR by Region         → dimension = region
    AR by Subsidiary     → dimension = subsidiary_name
    AR by Currency       → dimension = currency_symbol
    AR by Client Bucket  → dimension = client_buckets
    AR by Collection Status  → dimension = collection_status
    AR by Customer Journey   → dimension = client_journey_stage

────────────────────────────────────────────
SUMMARY TABLE (raw AR rows):
────────────────────────────────────────────
  Triggers: "show AR table", "AR summary table", "show all AR columns",
  "show me AR data", "AR raw data", "full AR table", "all AR rows",
  "AR transaction list", "show AR", "export AR", "list AR transactions"

  NOTE: Distinguish from "AR aging summary" / "AR KPIs" — those are aggregated reports.
        This trigger is for showing raw row-level data with all columns.

  - ALWAYS use SELECT * — never list individual columns.
  - Apply default filter only (AR has no time filter).
  - Default LIMIT 100 unless user specifies otherwise.
  - visualization = "table"

  SQL template:
    SELECT *
    FROM ar
    WHERE inter_company_status = 'F'
    LIMIT 100

  User says "all rows" / "no limit" → omit LIMIT.
  User says "intercompany" → swap inter_company_status = 'T'.

────────────────────────────────────────────
DETAIL QUERY (customer-specific):
────────────────────────────────────────────
  Triggers: "show AR for [customer]", "open invoices for [customer]",
  "AR data for [customer]", "outstanding for [customer]"

  - ALWAYS use SELECT * — never list individual columns.
  - visualization = "table"
  - No GROUP BY, no aggregation.
  - Filters: inter_company_status = 'F' AND customer_name ILIKE '%XYZ%'
  - No LIMIT on outer query unless user specifies.

  SQL template:
    SELECT *
    FROM ar
    WHERE inter_company_status = 'F'
      AND customer_name ILIKE '%XYZ%'

────────────────────────────────────────────
SORTING & LIMIT RULES:
────────────────────────────────────────────
  - Do NOT add ORDER BY to SQL. Python handles all sorting.
  - Exception: top N / bottom N → ORDER BY alias DESC/ASC + LIMIT N.
  - Default top N without number → LIMIT 10.
  - Full breakdowns → no LIMIT.

────────────────────────────────────────────
SQL OPTIMISATION RULES:
────────────────────────────────────────────
  - No ORDER BY unless top N. Python sorts.
  - Never repeat SUM expressions; use SELECT aliases.
  - All metric aliases MUST include currency suffix: _usd or _inr.
  - Display names must NOT include currency suffix in brackets.
  - Keep SQL minimal: SELECT, FROM, WHERE, GROUP BY only.
  - For ageing GROUP BY, always use CASE WHEN inline.

────────────────────────────────────────────
COMMON DASHBOARD REPORTS:
────────────────────────────────────────────
  1.  Total AR KPIs                 : single-row KPI report (see above)
  2.  AR by Region                  : dual-metric default (outstanding + overdue)
  3.  AR by Subsidiary              : dual-metric default
  4.  AR by Currency                : dual-metric default
  5.  AR by Client Bucket           : dual-metric default
  6.  AR by Collection Status       : dual-metric default
  7.  AR by Customer Journey        : dual-metric default
  8.  Client Journey Split (pivot)  : pivot_type=dimension, rows=client_buckets, cols=client_journey_stage
  9.  AR by Ageing Bucket           : CASE WHEN on open_days, long format — overrides dual-metric default
  10. AR Ageing Split by Region     : metric pivot, rows=region, cols=ageing buckets
  11. Top Customers by AR           : dual-metric default, GROUP BY customer_name, LIMIT 10
  12. AR by Invoice Quarter         : dual-metric default, GROUP BY transaction_fy_quarter
  13. AR Aging Summary              : full customer-level summary (all buckets — see above)
  14. AR Summary Table              : SELECT * with default filter (see SUMMARY TABLE above)

────────────────────────────────────────────
DISPLAY RULES:
────────────────────────────────────────────
  - display.title: short, report-like.
  - display.currency: USD (or INR if user asks).
  - display.columns: always use the COLUMN DISPLAY NAMES lookup below.
    For any alias not in the list, Python will auto-format it as a fallback.
  - display.formatting: define currency type for all amount columns.

{_DISPLAY_NAMES_BLOCK}
"""