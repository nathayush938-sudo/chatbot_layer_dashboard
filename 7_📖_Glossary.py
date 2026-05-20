"""
glossary.py  (place in pages/ as  7_📖_Glossary.py)
Static reference page — no DB queries, no Claude API calls.
"""

import streamlit as st

st.set_page_config(page_title="Glossary & Reference", layout="wide")

st.title("📖 Glossary & Reference")
st.caption("Caveats, assumptions, default behaviour, terminology and column definitions.")

# ─────────────────────────────────────────────
st.divider()
st.header("1. Default Behaviour")
# ─────────────────────────────────────────────

st.markdown("""
| Setting | Default | How to override |
|---|---|---|
| **Currency** | USD | Say "in INR" or "in rupees" |
| **Financial Year** | Current FY (YTD) | Say "FY26", "last year", "previous FY" |
| **Time period** | Current FY YTD | Say "Q4", "March 2026", "last quarter" |
| **Intercompany** | Excluded (`inter_company_status = 'F'`) | Say "include intercompany" or "intercompany only" |
| **TDS (Collections)** | Excluded (`tds_flag = 'F'`) | Say "include TDS" or "gross collections" |
| **Tax (Billing)** | Included in `billing_amount` | Say "excluding tax" or "net of tax" |
| **Top N** | 10 rows when unspecified | Say "top 5", "top 20", "show all" |
""")

# ─────────────────────────────────────────────
st.divider()
st.header("2. Key Terminology")
# ─────────────────────────────────────────────

col1, col2 = st.columns(2)

with col1:
    st.subheader("Billing")
    st.markdown("""
**Billing Amount** — The invoiced amount in transaction currency. Equivalent to `transaction_amount` in NetSuite. Always includes tax unless "excl. tax" is specified.

**Billed Revenue (Excl. Tax)** — `billing_amount - transaction_tax`. Used for revenue recognition.

**Tax Amount** — `COALESCE(transaction_tax, 0)`. May be zero for non-taxable invoices.

**Fee Types:**
- **Subscription Revenue** — Recurring SaaS fees (`subscriptionfee`)
- **Implementation Revenue** — Onboarding/setup fees (`implementationfee`)
- **Integration Revenue** — API/system integration fees (`integrationfee`)
- **Studio Revenue** — Custom development fees (`studiofee`)
- **Other Services** — AMS, opening split, miscellaneous (`amsfee + otherservicesfee + openingsplitfee`)

**Transaction Type:**
- `CustInvc` — Customer Invoice (positive amount)
- `CustCred` — Customer Credit Note (negative amount, reduces revenue)

**Billing Entity / Subsidiary** — The Darwinbox legal entity that raised the invoice (e.g. DB India, DB SG).

**Paying Entity** — The entity making the payment (relevant for intercompany).
    """)

    st.subheader("AR (Accounts Receivable)")
    st.markdown("""
**Open Amount** — Unpaid portion of an invoice in transaction currency. `open_amount > 0` = outstanding invoice; `open_amount < 0` = unapplied credit.

**Open Days** — `CURRENT_DATE - COALESCE(duedate, transaction_date)`. Positive = past due (overdue). Negative or zero = not yet due (current).

**Outstanding** — All open invoices regardless of due date: `SUM(open_amount * rate)`

**Overdue** — Invoices past their due date: `SUM(open_amount * rate) WHERE open_days >= 1`

**Current (Not Due)** — Invoices not yet past due: `WHERE open_days < 1`

**Overdue %** — `Overdue / Outstanding`. Higher = more urgent collection risk.

**Ageing Buckets:**
| Bucket | Definition |
|---|---|
| Current | open_days < 1 |
| 1-30 days | 1 ≤ open_days ≤ 30 |
| 31-60 days | 31 ≤ open_days ≤ 60 |
| 61-90 days | 61 ≤ open_days ≤ 90 |
| 91-180 days | 91 ≤ open_days ≤ 180 |
| >180 days | open_days > 180 |

**AR is a real-time snapshot** — it reflects the current state of unpaid invoices, not a historical record. There is no FY filter on AR queries.
    """)

with col2:
    st.subheader("Collections")
    st.markdown("""
**Collection Amount** — The amount received from a customer in transaction currency.

**Gross Collections** — All receipts including TDS: `SUM(collection_amount * rate)`

**Net Collections (default)** — Receipts excluding TDS payments: `WHERE tds_flag = 'F'`

**TDS Amount** — Tax Deducted at Source: `WHERE tds_flag = 'T'`

**TDS Flag:**
- `'F'` — Normal collection payment (default in all queries)
- `'T'` — TDS payment (excluded by default)

**Ageing Bucket (`ageingbucket`)** — Pre-computed bucket indicating how overdue the invoice was at the time of collection.

**Collection Status** — Operational status of the receivable:
- `Acknowledged` — Customer has confirmed the invoice
- `Pending Acknowledgement` — Awaiting customer confirmation
- `Product Issue` — Disputed due to product problems
- `Implementation Issue / Implementation Delays` — Disputed due to onboarding
- `Other Issues` — Miscellaneous disputes
- `Agreement / Renewal` — Under contract renegotiation
    """)

    st.subheader("Unified (Billing + Collections)")
    st.markdown("""
**finance_unified_txn** — A pre-aggregated materialized view joining billing and collections at `customer_ucc + fy_quarter` level. One row per customer per quarter.

**Collection Efficiency** — `collected_net / billed_excl_tax`. Interpretation:
- `= 1.0` (100%) — Everything billed was collected
- `> 1.0` (>100%) — More was collected than billed (prior period payments received)
- `< 1.0` (<100%) — Not all billing was collected in this period

**Billing-Collection Gap** — `billed - collected_net`. The uncollected portion of billing. Not the same as AR Outstanding (which is a real-time snapshot; gap is period-specific).

**Note:** The unified view does not include AR data. For outstanding AR alongside billing/collections, query the `ar` view separately.
    """)

# ─────────────────────────────────────────────
st.divider()
st.header("3. Dimensions")
# ─────────────────────────────────────────────

st.markdown("""
| Dimension | Values | Notes |
|---|---|---|
| **Region** | APAC, India - North, India - South, India - West, India - Growth A, India - Growth B, MENA, NORAM, HeadQuarter, EU, Unassigned | Customer's sales region |
| **Billing Entity (Subsidiary)** | DB India, DB SG, DB PH, DB Mena, DB US, DB ID, DB MY, DB TH | Darwinbox legal entity that raised the invoice |
| **Client Journey Stage (CJS)** | Customer Success, Implementation, Potential Churn, Churned | Stage in the customer lifecycle |
| **Client Bucket** | Issue, Non-Issue, Churned Account | Operational health classification |
| **Collection Status** | Acknowledged, Pending Acknowledgement, Product Issue, Implementation Issue / Implementation Delays, Other Issues, Agreement / Renewal | Receivables management status |
| **inter_company_status** | `'F'` = External, `'T'` = Intercompany | Always `'F'` by default |
| **Currency Symbol** | INR, USD, PHP, SGD, IDR, SAR, MYR, AED, THB, GBP, CAD, EUR | Transaction invoice currency |
""")

# ─────────────────────────────────────────────
st.divider()
st.header("4. Currency & Exchange Rates")
# ─────────────────────────────────────────────

st.markdown("""
All monetary amounts in the source tables are in **transaction currency** (the currency of the original invoice).

Conversion to a reporting currency is done using exchange rates stored per transaction:

| Column | Converts to |
|---|---|
| `usd_exchangerate` | US Dollar (USD) |
| `inr_exchangerate` | Indian Rupee (INR) |

**Formula:** `billing_amount * usd_exchangerate` → amount in USD

**Exchange rates** are transaction-level (not daily market rates). They reflect the rate agreed at invoice time.

**finance_unified_txn** — amounts are **pre-converted** in the view. Use `billed_usd` / `billed_inr` directly without multiplying by an exchange rate.

**Number formatting:**

| Currency | Denominations |
|---|---|
| USD | K (thousands) → Mn (millions) → Bn (billions) |
| INR | K (thousands) → L (lakhs = 100K) → Cr (crores = 10M) |
""")

# ─────────────────────────────────────────────
st.divider()
st.header("5. Financial Year")
# ─────────────────────────────────────────────

st.markdown("""
Darwinbox uses the **Indian Financial Year**: April 1 to March 31.

| FY Label | Period |
|---|---|
| FY26 | April 2025 – March 2026 |
| FY27 | April 2026 – March 2027 |

**Quarter breakdown:**
| Quarter | Months |
|---|---|
| Q1 | April, May, June |
| Q2 | July, August, September |
| Q3 | October, November, December |
| Q4 | January, February, March |

**`transaction_fy_quarter` format:** `'FY26 Q1'`, `'FY26 Q2'`, etc.

**FY filter pattern:** `transaction_fy_quarter LIKE 'FY26%'` matches all 4 quarters of FY26.
""")

# ─────────────────────────────────────────────
st.divider()
st.header("6. Caveats & Assumptions")
# ─────────────────────────────────────────────

st.markdown("""
**General**
- All data originates from **NetSuite** via pre-computed materialized views. Refresh frequency depends on your ETL pipeline.
- The chatbot generates SQL dynamically. While the semantic model guides it, complex or ambiguous questions may occasionally produce incorrect SQL. Always verify via the **Generated SQL** expander.
- AR is a **point-in-time snapshot**. Querying AR on different days will yield different results as invoices are paid.

**Billing**
- `billing_amount` includes tax. Use `billing_amount - COALESCE(transaction_tax, 0)` for net revenue.
- Credit notes (`CustCred`) have negative `billing_amount` and reduce gross billing.
- Intercompany transactions (`inter_company_status = 'T'`) are excluded from all queries by default.

**Collections**
- TDS payments (`tds_flag = 'T'`) are excluded by default. All "collections" figures are net of TDS unless stated otherwise.
- A collection amount > billed amount for a customer in a given period is normal — it means prior-period invoices were collected in the current period.

**AR**
- `open_amount` in the AR view is signed. Positive = invoice, Negative = credit note or overpayment.
- AR does not have a financial year dimension. It reflects **current unpaid invoices** only.
- The "Current (Not Due)" bucket includes invoices where `open_days < 1` (due today or in the future).

**Unified View (finance_unified_txn)**
- The view joins billing and collections on `customer_ucc + fy_quarter`. If a customer has collections but no billing in a quarter (or vice versa), they still appear via the FULL OUTER JOIN with NULLs on the missing side.
- `collection_efficiency_usd > 1.0` is possible and indicates prior-period collections arriving in the current period.
- The unified view does **not** include AR data.

**Chat Layer**
- The chat layer uses Claude (claude-sonnet-4) to generate SQL. Each query costs tokens.
- The NL filter below results is for **narrowing existing data** (e.g. "only India", "top 5"). For new analysis (comparisons, % change), ask a new question.
- Domain routing (billing / collections / AR / unified) is automatic based on keywords. If a query routes to the wrong domain, rephrase with the domain name explicitly.
""")