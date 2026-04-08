# 02_METRIC_TAXONOMY_AND_DEFINITIONS

Version: 0.1  
Date: 2025-11-15  
Owner: Rob Markey  

## 1. Purpose

> **Note on keyword patterns**: As of the `eb2fb54` refactor, all keyword patterns, synonyms, and metric signal configurations have been moved to `config/metric_keywords.yaml` as the **authoritative source**. The synonym and pattern examples in this document are illustrative of intent; the YAML config is canonical for extraction purposes. Always update `config/metric_keywords.yaml` when changing detection behavior.

This document defines the **metric taxonomy** for the Customer Metrics Filings Analysis project.

It serves four purposes:

- Define a **controlled vocabulary** of metrics and concepts  
- Specify **business definitions** and **calculation rules** for Phase 1 Core Metrics  
- Enumerate **synonyms and variants** we expect to see in SEC filings  
- Provide a foundation for:
  - Data model design (`03_DATA_MODEL_SPEC.md`)  
  - Extraction rules and prompts  
  - Quality/comparability assessment  

All extraction, QA, and analysis must use these canonical metric IDs and definitions.

---

## 2. Taxonomy overview

### 2.1 Metric classes

We classify metrics into three groups:

1. **Core Metrics (Phase 1)**  
   - Highest priority for S-1 analysis  
   - Must be handled with the strongest detection, extraction, and QA  
   - Definitions should be as close as possible to CMASB’s long-term standards  

2. **Extended Metrics (Phase 1)**  
   - Important, but secondary to Core Metrics in Phase 1  
   - We track incidence and basic values when feasible  
   - Definitions can be somewhat looser initially  

3. **Future Metrics (Phase 2+)**  
   - Anticipated metrics for later phases (e.g., full NRR, GRR, LTV)  
   - Included here to ensure the taxonomy will scale, but not required for Phase 1 delivery  

### 2.2 Canonical IDs and naming

- All metrics use **lower_snake_case** IDs.  
- Prefix `cm_` for customer metrics to avoid collisions with generic financial metrics.

Examples:

- Core: `cm_new_customers_acquired`  
- Extended: `cm_active_customers_total`, `cm_revenue_per_customer`  
- Future: `cm_lifetime_value_per_customer`

These IDs are the **single source of truth** across:

- Data model fields  
- Extraction rules  
- LLM prompts  
- Analytics code  

### 2.3 Data model mapping

In the relational schema (`03_DATA_MODEL_SPEC.md`), each metric in this taxonomy is represented in the `metrics` dimension table.

Key fields:

- `metric_id` – The canonical ID defined in this document (e.g., `cm_new_customers_acquired`).
- `metric_class` – The class of the metric as defined in Section 2.1.

The mapping is:

- **Core Metrics (Phase 1)** → `metrics.metric_class = 'core'`
- **Extended Metrics (Phase 1)** → `metrics.metric_class = 'extended'`
- **Future Metrics (Phase 2+)** → `metrics.metric_class = 'future'`

All references to "Core", "Extended", or "Future" metrics in this document are intended to map directly onto these `metric_class` values in the data model.

---

## 3. Core Metrics (Phase 1)

> Note: These are **draft definitions** for Phase 1. We will refine them as we test against real filings and through CMASB conversations.

### 3.1 CM1 – New Customers Acquired per Period

**ID:** `cm_new_customers_acquired`  
**Class:** Core (Phase 1)  

**Business intent**

Measure how many **new customers** a company acquires in each reporting period. This is the primary driver of future cohort size and future cash flows.

**Canonical definition**

> The count of **unique customers** whose **first qualifying economic activity** with the company occurs in the reporting period.

“Qualifying economic activity” is defined in Section 5.4 (Customer and Active Customer).

**Units**

- Integer count of customers

**Required dimensions**

- **Time**:
  - `period_start`, `period_end`
  - `period_type` (e.g., FY, Q, half-year, month)  
- **Company**:
  - `cik`, `company_id`  

**Optional dimensions**

- Acquisition channel (e.g., direct, partner, marketplace)  
- Geography  
- Customer type (consumer, SMB, enterprise)  

**Calculation rules (ideal standard)**

1. A “new customer” is one whose **first transaction** or **first billed revenue** occurs in the period.  
2. Customers who previously churned and then reactivated should be counted separately as **reactivated customers**, not as “new customers,” where such information is available.  
3. The count should be based on the same underlying system as revenue recognition (e.g., billing, CRM, subscription system).

**What counts in Phase 1**

- Any disclosed metric clearly described as:
  - “New customers”  
  - “New subscribers”  
  - “Gross adds”  
  - “New logos”  
  - “New paying accounts”  
- We will flag whether the issuer:
  - Includes reactivated customers  
  - Includes non-paying users  
  - Uses a different definition (see Section 7 on alignment)

**Common synonyms and phrases**

- New customers  
- New paying customers  
- New subscribers  
- Gross customer adds  
- New logos  
- First-time buyers  

**Out-of-scope / must not map here**

- Total customers at period end  
- Total users (including non-paying) unless clearly defined as “customers”  
- Sales leads, sign-ups, or app downloads without evidence of economic activity  

---

### 3.2 CM2 – Customers at Period End by Tenure Cohort

**ID:** `cm_customers_period_end_by_tenure`  
**Class:** Core (Phase 1)  

**Business intent**

Measure the **size and age structure** of the active customer base at the end of the period, broken into **tenure cohorts**. This shows retention and longevity.

**Canonical definition**

> The number of customers **active at period end**, broken down by **tenure cohorts** defined by time since first qualifying economic activity.

Example tenure buckets (illustrative):

- 0–1 years since first purchase  
- 1–2 years  
- 2–3 years  
- 3–5 years  
- 5+ years  

**Units**

- Integer count of customers  

**Required dimensions**

- Time:
  - `period_end`, `period_type`  
- Tenure cohort:
  - `cohort_type = 'tenure'`  
  - `cohort_bucket` (e.g., “0–1 years”)  

**Optional dimensions**

- Customer type (consumer, SMB, enterprise)  
- Geography  
- Product / subscription plan  

**Calculation rules (ideal standard)**

1. Customer tenure is measured from **first qualifying economic activity**.  
2. A customer is **included in a tenure cohort** if:
   - They are **active** at period end (see definition of Active Customer)  
   - Their tenure falls into the bucket at period end.  
3. Reporting should **cover all tenure cohorts** that sum to total active customers.

**What counts in Phase 1**

- Any disclosure tabulating customers by age or tenure, including:  
  - “Customers by duration of relationship”  
  - “Subscribers by years since subscription start”  
  - “Cohort of customers acquired before 2020 vs 2020 vs 2021…”, when framed as tenure  
- We will capture the exact bins provided, even if they differ from our ideal set.

**Common synonyms and phrases**

- Customer tenure cohorts  
- Age of relationship  
- Vintage cohorts (if expressed in tenure terms)  
- Duration since sign-up / first transaction  

**Out-of-scope / must not map here**

- Customer count by **acquisition year** only (that belongs in revenue-by-cohort or other cohort metrics) unless also clearly used as a tenure breakdown  
- Purely product segmentation with no tenure dimension  

---

### 3.3 CM3 – Revenue by Customer Cohort

**ID:** `cm_revenue_by_cohort`  
**Class:** Core (Phase 1)  

**Business intent**

Measure how much **revenue** each customer cohort generates over time, enabling analysis of retention, expansion, and cohort value.

**Canonical definition**

> Recognized **GAAP revenue** in the period, attributed to **customer cohorts** defined by **acquisition period** or **tenure**, as disclosed by the issuer.

We accept both:

- **Acquisition cohorts** (customers acquired in a specific year/quarter)  
- **Tenure cohorts** (customers grouped by tenure at period end)

**Units**

- Monetary (e.g., USD, EUR)  

**Required dimensions**

- Time:
  - `period_start`, `period_end`, `period_type`  
- Cohort:
  - `cohort_type` (`'acquisition'` or `'tenure'`)  
  - `cohort_bucket` (e.g., “2021 acquisition cohort,” “0–1 years tenure”)  

**Optional dimensions**

- Product or service  
- Geography  
- Customer segment (consumer, SMB, enterprise)  

**Calculation rules (ideal standard)**

1. Revenue must be consistent with the company’s **GAAP revenue** for the period when aggregated.  
2. Cohort attribution must be:
   - Based on where the revenue-causing customer belongs (by acquisition date or tenure)  
   - Not double-counted across cohorts.  
3. Non-recurring and recurring revenue should be distinguishable where disclosed.

**What counts in Phase 1**

- Any table or narrative that clearly attributes **revenue** to:
  - Acquisition cohorts  
  - Vintage years  
  - Tenure cohorts  
- Even if not reconciled to total GAAP revenue, we still record values and note misalignment.

**Common synonyms and phrases**

- Cohort revenue  
- Revenue by customer vintage  
- Revenue by signup year  
- Revenue contribution by cohort  
- Revenue by customer tenure  

**Out-of-scope / must not map here**

- Revenue by product or geography without a cohort dimension  
- ARR/MRR by cohort **only** if it is clearly about contracted revenue without recognition; these may be tracked as extended metrics  

---

### 3.4 CM4 – Purchase Transactions by Cohort

**ID:** `cm_transactions_by_cohort`  
**Class:** Core (Phase 1)  

**Business intent**

Measure **purchase intensity** and **engagement** by cohort, independent of ticket size, to understand how cohorts behave over time.

**Canonical definition**

> The number of **completed purchase transactions** in the period, grouped by customer cohort (acquisition or tenure).

**Units**

- Integer count of transactions  

**Required dimensions**

- Time:
  - `period_start`, `period_end`, `period_type`  
- Cohort:
  - `cohort_type` (`'acquisition'` or `'tenure'`)  
  - `cohort_bucket`  

**Optional dimensions**

- Product/service  
- Channel (in-store, online, app, etc.)  
- Geography  

**Calculation rules (ideal standard)**

1. Count each **completed purchase** as one transaction, regardless of order value.  
2. Returns/refunds should be handled consistently (ideally separate).  
3. If the issuer uses order lines vs orders, we will follow their definition but flag it.

**What counts in Phase 1**

- Any disclosures that report:
  - Transaction counts by cohort  
  - Orders per cohort by period  
  - Purchase frequency by cohort (if can be converted to counts with provided base)  

**Common synonyms and phrases**

- Number of orders  
- Transactions  
- Purchases  
- Rides / deliveries (for rideshare/delivery)  
- Bookings (if clearly used as transaction counts)  

**Out-of-scope / must not map here**

- Page views, app sessions, or logins  
- “Engagement events” that are not economic transactions  

---

### 3.5 CM4b – Purchase Transactions (Overall)

**ID:** `cm_purchase_transactions_overall`  
**Class:** Core (Phase 1)  

**Business intent**

Measure total **purchase transaction volume** across all customers in the period, independent of cohort. This is the aggregate complement to CM4 (`cm_transactions_by_cohort`) and captures companies that disclose order counts without a cohort breakdown.

**Canonical definition**

> The total number of **completed purchase transactions** in the reporting period, across all customers and cohorts.

**Units**

- Integer count of transactions  

**Required dimensions**

- Time:
  - `period_start`, `period_end`, `period_type`  

**What counts in Phase 1**

- “Number of orders”  
- “Total orders”  
- “Purchase transactions” (without cohort qualifier)  
- “Order count” or “order volume”

**Out-of-scope / must not map here**

- Transaction counts broken down by cohort (those belong to `cm_transactions_by_cohort`)  
- Page views, sessions, or non-purchase engagement events  

---

### 3.6 CM5 – Customers at Period End (Total)

**ID:** `cm_customers_period_end`  
**Class:** Core (Phase 1)  

**Business intent**

Measure the **total size of the customer base** at the end of each period. This is a stock count of all customers — paying or otherwise as defined by the issuer — and is the most fundamental customer-base metric.

**Canonical definition**

> The count of **unique customers** that meet the issuer's definition of “customer” as of the last day of the reporting period.

**Units**

- Integer count of customers  

**Required dimensions**

- Time:
  - `period_end`, `period_type`  
- Company:
  - `cik`, `company_id`  

**What counts in Phase 1**

- “Total customers”  
- “Paid customers” / “paying customers”  
- “Total paying organizations”  
- “Customer base” disclosures with a count  
- Period-end subscriber counts (telecom, SaaS)

**Out-of-scope / must not map here**

- Active customers based on engagement criteria (those belong to `cm_active_customers_total`)  
- New customers acquired in the period (those belong to `cm_new_customers_acquired`)  
- Leads, sign-ups, or app downloads without evidence of economic activity  

---

## 4. Extended Metrics (Phase 1)

Extended metrics are **not primary** for Phase 1 but provide important context. We track incidence and values where feasible.

### 4.1 Active Customers (Total)

**ID:** `cm_active_customers_total`  
**Class:** Extended (Phase 1)  

**Intent**

Total number of **active customers** as defined by the issuer at period end.

We will:

- Capture the number  
- Capture the issuer’s definition of “active” (see Section 5)  
- Link to revenue and cohort metrics where possible  

### 4.2 Revenue per Customer (ARPU)

**ID:** `cm_revenue_per_customer`  
**Class:** Extended (Phase 1)  

Any metric clearly framed as revenue per user/customer/subscriber over a defined period. Common labels include ARPU (average revenue per user) and ARPA (average revenue per account).

We will:

- Capture values and definitions  
- Not enforce a single standard definition yet  

### 4.3 CAC and CAC Payback

**IDs:**

- `cm_customer_acquisition_cost`  
- `cm_cac_payback_period`  

We will:

- Track their incidence and disclosed values  
- Capture methodology text  
- Flag alignment/misalignment with a future CMASB standard  

### 4.4 Retention and Churn (Basic)

**IDs:**

- `cm_customer_retention_rate`  
- `cm_customer_churn_rate`  

Phase 1:

- Focus on incidence and basic extraction of values  
- Defer detailed comparability analysis to Phase 2  

### 4.5 Large Customers at Period End

**ID:** `cm_large_customers_period_end`  
**Class:** Extended (Phase 1)  

Count of customers exceeding a revenue or ARR threshold defined by the issuer (e.g., customers with trailing 12-month revenue greater than $100,000). Common in SaaS and enterprise software filings.

### 4.6 Net Revenue Retention

**ID:** `cm_net_revenue_retention`  
**Class:** Extended (Phase 1)  

Revenue retained from the prior-period cohort of customers including expansion, net of churn and contraction. Also referred to as Net Dollar Retention (NDR) or dollar-based net retention. A value above 100% indicates expansion outweighs churn.

### 4.7 Gross Revenue Retention

**ID:** `cm_gross_revenue_retention`  
**Class:** Extended (Phase 1)  

Revenue retained from the prior-period cohort of customers excluding expansion (churn and contraction only). Represents the floor of revenue retained, capped at 100%. Also referred to as GRR.

### 4.8 Monthly Active Users

**ID:** `cm_monthly_active_users`  
**Class:** Extended (Phase 1)  

Count of unique users or accounts that meet the issuer's activity criteria within a calendar month. Commonly abbreviated MAU. Widely disclosed by consumer internet, social media, and payments companies.

### 4.9 Daily Active Users

**ID:** `cm_daily_active_users`  
**Class:** Extended (Phase 1)  

Count of unique users or accounts that meet the issuer's activity criteria within a single day. Commonly abbreviated DAU. Often disclosed alongside MAU to show engagement depth.

### 4.10 Gross Margin by Cohort

**ID:** `cm_gross_margin_by_cohort`  
**Class:** Extended (Phase 1)  

Gross margin or contribution margin analyzed by customer acquisition cohort or vintage. Captures how unit economics evolve as cohorts mature. Common in e-commerce and marketplace filings (e.g., order contribution margin for new vs. existing customers).

### 4.11 Annual Recurring Revenue

**ID:** `cm_arr`  
**Class:** Extended (Phase 1)  

Annualized value of subscription or recurring contract revenue as of a point in time. Commonly abbreviated ARR. A standard SaaS metric; includes annualized run-rate variants disclosed by issuers.

### 4.12 Monthly Recurring Revenue

**ID:** `cm_mrr`  
**Class:** Extended (Phase 1)  

Monthly subscription or recurring contract revenue as of a point in time. Commonly abbreviated MRR. The monthly analogue of ARR; typically used by earlier-stage SaaS companies or those with monthly billing cycles.

### 4.13 Expansion Revenue

**ID:** `cm_expansion_revenue`  
**Class:** Extended (Phase 1)  

Revenue generated from existing customers beyond their initial contract or baseline spend. Includes upsell, cross-sell, and additional product adoption. Sometimes expressed as products per customer or transactions per active account.

### 4.14 Revenue Concentration

**ID:** `cm_revenue_concentration`  
**Class:** Extended (Phase 1)  

Measure of how revenue is distributed across the customer base. Commonly disclosed as revenue from the top N customers, a named customer's revenue percentage, or a statement that no single customer exceeds a given threshold. Signals customer dependency risk.

### 4.15 Average Order Value

**ID:** `cm_average_order_value`  
**Class:** Extended (Phase 1)  

Average revenue per purchase transaction, also referred to as average ticket size or average basket size. Commonly abbreviated AOV. Primarily used in e-commerce and retail filings.

### 4.16 Repeat Purchase Rate

**ID:** `cm_repeat_purchase_rate`  
**Class:** Extended (Phase 1)  

The proportion of customers who make more than one purchase, or the frequency with which customers reorder. Common labels include repeat purchase rate, purchase frequency, reorder rate, and repurchase rate.

### 4.17 LTV/CAC Ratio by Cohort

**ID:** `cm_ltv_to_cac_ratio_by_cohort`  
**Class:** Extended (Phase 1)  

The ratio of customer lifetime value to customer acquisition cost, analyzed by acquisition cohort. Captures how unit economics vary across cohorts over time. May be disclosed with temporal qualifiers such as "6-month LTV/CAC" or "LTV/CAC after 12 months."

---

## 5. Core concepts and definitions

These concepts are referenced in metric definitions. They must be used consistently.

### 5.1 Customer

Working definition for Phase 1:

> A **customer** is an identifiable party (individual or entity) that has engaged in a **qualifying economic activity** with the company, such as a purchase, subscription, or usage that results in revenue.

We will:

- Prefer the issuer’s explicit definition where provided  
- Capture issuer-specific definitions verbatim in the definitions table  
- Map them to this working concept for alignment scoring

### 5.2 Active Customer

Working definition for Phase 1:

> An **active customer** is a customer that meets the issuer’s defined criteria for being “active” as of a given date (often based on recency of activity).

Common issuer definitions include:

- At least one transaction in the last X months  
- Current subscription without cancellation  
- Logged-in or transacting above a minimum threshold

The system must:

- Capture the issuer’s explicit definition text  
- Classify the definition type where possible (e.g., “recency-based,” “subscription-status-based”)  

### 5.3 Cohort

Generic concept:

> A **cohort** is a group of customers that share a common attribute used for grouping over time.

Two primary cohort types in scope:

1. **Acquisition Cohort**  
   - Grouped by time of first qualifying economic activity (e.g., “2021 Acquisition Cohort”)  

2. **Tenure Cohort**  
   - Grouped by time since first qualifying economic activity (e.g., “0–1 year tenure”)  

In the data model, we will capture:

- `cohort_type` (e.g., `'acquisition'`, `'tenure'`)  
- `cohort_bucket` (issuer-specific label, plus normalized where possible)

### 5.4 Qualifying Economic Activity

Working definition:

> An action by a customer that leads to recognized revenue or a commitment that will result in revenue under the company’s business model.

Examples:

- Purchase of a product or service  
- Subscription sign-up that leads to billing  
- Usage that triggers usage-based fees  

We will capture issuer-specific criteria when disclosed.

### 5.5 Purchase / Transaction

Working definition:

> A **transaction** is a completed economic exchange where a customer acquires a product or service and the company records revenue or billable usage.

We will:

- Use issuer’s definitions where available  
- Capture whether transactions are:
  - Orders  
  - Rides  
  - Deliveries  
  - Bookings  
  - Other domain-specific constructs  

---

## 6. Alignment and mapping rules

For each metric, we will record:

- Whether a disclosed metric **maps** to a canonical metric ID  
- Alignment level:
  - `aligned` – close to the canonical definition  
  - `partial` – overlaps but includes or excludes important elements  
  - `not_aligned` – related but materially different  

The extraction/QA pipeline must:

- Capture issuer labels and definitions  
- Map them to canonical IDs where appropriate  
- Store alignment flags and short notes

---

## 7. Versioning and governance

### 7.1 Versioning

- Each metric definition has a **version**.  
- This document will maintain a **changelog** when definitions change in ways that affect comparability.

Example changes:

- Narrowing or broadening what counts as a “customer”  
- Changing how acquisition cohorts are defined  

### 7.2 Backward compatibility

When definitions change:

- We will document whether old data can be mechanically transformed to the new definition.  
- If not, we may maintain separate **metric IDs** (e.g., `cm_new_customers_acquired_v1`, `cm_new_customers_acquired_v2`) for internal use, even if public-facing analysis uses a single label.

---

## 8. Open questions

Items to resolve before finalizing v1.0:

1. **Exact list of Phase 1 Core Metrics**  
   - Confirm that CM1–CM4 are the correct set and that others remain Extended in Phase 1.  

2. **Canonical tenure buckets**  
   - Decide whether we will enforce a standard set (0–1, 1–2, 2–3, 3–5, 5+ years) or simply normalize issuer buckets where possible.  

3. **Treatment of reactivated customers**  
   - Do we require separate metrics for reactivations in standards, or just capture issuer choices?  

4. **ARR/MRR vs GAAP revenue**  
   - For cohort metrics, how do we want to treat ARR/MRR disclosures that are not GAAP revenue but are economically meaningful?  

5. **Minimum detail level for Phase 1**  
   - For Extended Metrics (CAC, ARPU, retention), how much effort do we want to invest now vs Phase 2?

These decisions will influence:

- Extraction complexity  
- Comparability claims in CMASB reports  
- The degree of “push” on issuers in the first standards proposal

---

## 9. References and links

- `01_ANALYTIC_REQUIREMENTS.md`  
- Proposed Metrics and Definitions_v1.docx (source draft)  
- Analysis of SEC filings – overview.docx  
- Future: CMASB Draft Standards (when available)