# GI-1: Cohort Pattern Gap Analysis

## Executive Summary

Analysis of 479 cohort-related text snippets extracted from Slack and Farfetch S-1 filings reveals critical gaps in current pattern detection:

- **9/9 patterns** have zero matches against real cohort language
- **Total matches across all patterns**: 0 (of 4311 possible pattern-snippet pairs)
- **Overall match rate**: 0.0%

The current patterns focus narrowly on percentage-of-customer language and explicit 'cohort analysis' phrases, missing the rich variety of cohort-related disclosures in real filings.

## Methodology

### Text Extraction
- Parsed HTML from Slack S-1 (CIK 0001764925) and Farfetch S-1 (CIK 0001740915)
- Used BeautifulSoup to extract text from paragraph, div, td, span, and li elements
- Searched for sentences containing cohort-related terms:
  - `cohort, retention, NRR, NDR, dollar-based, dollar based, ARR, expansion, tenure, vintage`, ...

### Pattern Testing
- Tested all 9 current COHORT_PATTERNS against each extracted snippet
- Recorded match/no-match and calculated miss rate per pattern
- Categorized missed snippets by language type

## Current Pattern Performance

| # | Pattern Name | Description | Matches | Miss Rate |
|---|--------------|-------------|---------|-----------|
| 1 | `pct_of_customers` | "X% of customers/users" | 0/479 | 100.0% |
| 2 | `pct_were_customers` | "X% were/are [adj] customers" | 0/479 | 100.0% |
| 3 | `customer_represented` | "new/existing customers represented" | 0/479 | 100.0% |
| 4 | `cohort_analysis` | "cohort analysis" phrase | 0/479 | 100.0% |
| 5 | `by_cohort` | "by acquisition/tenure/vintage cohort" | 0/479 | 100.0% |
| 6 | `customers_acquired_in` | "customers acquired in 20XX" | 0/479 | 100.0% |
| 7 | `year_customers` | "first/second/third-year customers" | 0/479 | 100.0% |
| 8 | `new_vs_existing` | "new vs existing customers" | 0/479 | 100.0% |
| 9 | `customer_tenure` | "customer age/tenure/lifetime" | 0/479 | 100.0% |

**Key Finding**: The patterns focus on very specific phrasings that don't match how companies actually describe cohort metrics in their filings.

## Missed Text Snippets by Category

### Category: Fiscal Year Cohorts
**Count**: 32 snippets

1. "We had 575 Paid Customers >$100,000 of ARR as of January 31, 2019, which accounted for approximately 40% of our revenue in fiscal year 2019 ."
   - **Source**: Slack S-1
   - **Search term**: ARR

2. "In fiscal year 2019, we implemented a new ERP system, including our systems for tracking revenue recognition."
   - **Source**: Slack S-1
   - **Search term**: fiscal year

3. "In the fiscal year ended January 31, 2018, approximately 10% of our revenue was derived from organizations on our Free subscription plan prior to fiscal year 2018 that converted to Paid Customers in fiscal year 2018."
   - **Source**: Slack S-1
   - **Search term**: fiscal year

4. "I n the fiscal year ended January 31, 2019, approximately 8% of our revenue was derived from organizations on our Free subscription plan prior to fiscal year 2019 that converted to Paid Customers in fiscal year 2019."
   - **Source**: Slack S-1
   - **Search term**: fiscal year

5. "For example, the fiscal year 2015 cohort represents all Paid Customers that purchased their first subscription from us during the fiscal year ended January 31, 2015."
   - **Source**: Slack S-1
   - **Search term**: cohort

6. "Three Months Ended April 30, 2017 July 31, 2017 October 31, 2017 January 31, 2018 April 30, 2018 July 31, 2018 October 31, 2018 January 31, 2019 (In thousands) Revenue $ 42,719 $ 51,320 $ 58,046 $ 68,459 $ 80,919 $ 92,018 $ 105,648 $ 121,967 Cost of revenue (1) 5,418 6,098 6,788 8,060 10,101 11,361 ..."
   - **Source**: Slack S-1
   - **Search term**: fiscal year

7. "In the first, second and fourth quarters of fiscal year 2019, we recorded an additional compensation expense of $4.4 million, $7.9 million, and $2.5 million, respectively, related to secondary sales of Class B common stock by certain of our current and former employees."
   - **Source**: Slack S-1
   - **Search term**: fiscal year

8. "Operating Expenses Total operating expenses increased sequentially for all periods presented, excluding stock-based compensation of $39.1 million attributable to tender offers and repurchases for our outstanding common stock in the fourth quarter of fiscal year 2018, primarily due to increases in em..."
   - **Source**: Slack S-1
   - **Search term**: expansion

9. "In the fourth quarter of fiscal year 2018, we recorded a one-time compensation charge for a total amount of $39.1 million due to a tender offer in which we repurchased shares of our Class B common stock and convertible preferred stock from certain of our stockholders."
   - **Source**: Slack S-1
   - **Search term**: fiscal year

10. "The expense associated with the tender offer increased cost of revenue by $0.3 million, research and development expense by $30.4 million, sales and marketing expense by $6.5 million, and general and administrative expense by $1.9 million, in the fourth quarter of fiscal year 2018."
   - **Source**: Slack S-1
   - **Search term**: fiscal year

*... and 22 more snippets in this category*

### Category: Retention Metrics
**Count**: 87 snippets

1. "They do so because Slack is a new layer of the business technology stack that brings together people, applications, and data – a single place where people can effectively work together, access hundreds of thousands of critical applications and services, and find important information to do their bes..."
   - **Source**: Slack S-1
   - **Search term**: NDR

2. "Depending on the size of the organization, this might provide tens, hundreds or even thousands of times more access to information than is available to individuals working in environments where email is the primary means of communication."
   - **Source**: Slack S-1
   - **Search term**: NDR

3. "Slack has aggregated hundreds of thousands of organizations on one platform and made it easier for developers to distribute their software to any Slack-using organization."
   - **Source**: Slack S-1
   - **Search term**: NDR

4. "We measure the rate of expansion within our Paid Customer base, both sales-driven and through organic growth, by Net Dollar Retention Rate."
   - **Source**: Slack S-1
   - **Search term**: retention

5. "Our Net Dollar Retention Rate was 143% as of January 31, 2019."
   - **Source**: Slack S-1
   - **Search term**: retention

6. "We believe that our Net Dollar Retention Rate is a reflection of the rapid pace of adoption that often occurs as usage spreads within and across teams."
   - **Source**: Slack S-1
   - **Search term**: retention

7. "For a definition of how we calculate Net Dollar Retention Rate and additional information about our key business metrics, see the section titled “Management’s Discussion and Analysis of Financial Condition and Results of Operations—Key Business Metrics.” What Sets Us Apart Singular focus Our develop..."
   - **Source**: Slack S-1
   - **Search term**: retention

8. "• If we are unable to attract new users and organizations, convert users of and organizations on our free version into paid customers, grow or maintain our Net Dollar Retention Rate, expand usage within organizations on Slack, and sell premium subscription plans or develop new features, integrations..."
   - **Source**: Slack S-1
   - **Search term**: retention

9. "As of January 31, 2017 2018 2019 Paid Customers 37,000 59,000 88,000 Paid Customers >$100,000 135 298 575 Net Dollar Retention Rate 171 % 152 % 143 % 11 For additional information about our key business metrics, see the section titled “Management’s Discussion and Analysis of Financial Condition and ..."
   - **Source**: Slack S-1
   - **Search term**: retention

10. "In future periods, our revenue growth could slow or our revenue could decline for a number of reasons, including any failure to increase the number of organizations on Slack, increase our number of paid customers, or grow or maintain our Net Dollar Retention Rate, a decrease in the growth of our ove..."
   - **Source**: Slack S-1
   - **Search term**: retention

*... and 77 more snippets in this category*

### Category: Arr Cohorts
**Count**: 1 snippets

1. "67 The chart below illustrates the annual recurring revenue, or ARR, of each cohort over the periods presented, with each cohort representing Paid Customers who made their first purchase from us in a given fiscal year."
   - **Source**: Slack S-1
   - **Search term**: cohort

### Category: Enterprise Terms
**Count**: 45 snippets

1. "Once an organization has three or more users on a paid subscription plan, we count them as a Paid Customer."
   - **Source**: Slack S-1
   - **Search term**: Paid Customer

2. "As of January 31, 2019, Slack had more than 600,000 organizations with three or more users, comprised of: • More than 88,000 Paid Customers, including more than 65 companies in the Fortune 100; and • More than 500,000 organizations on our Free subscription plan."
   - **Source**: Slack S-1
   - **Search term**: Paid Customer

3. "Many of our Paid Customers have thousands of active users and our largest Paid Customers have tens of thousands of employees using Slack on a daily basis."
   - **Source**: Slack S-1
   - **Search term**: Paid Customer

4. "During this same time, on a typical workday, users at Paid Customers averaged nine hours connected to Slack through at least one device and spent more than 90 minutes actively using Slack."
   - **Source**: Slack S-1
   - **Search term**: Paid Customer

5. "We measure the number of Paid Customers > $100,000 of annual recurring revenue, or ARR, as a gauge of adoption within and expansion into large enterprises."
   - **Source**: Slack S-1
   - **Search term**: ARR

6. "We had 575 Paid Customers >$100,000 of ARR as of January 31, 2019, which accounted for approximately 40% of our revenue in fiscal year 2019 ."
   - **Source**: Slack S-1
   - **Search term**: ARR

7. "We measure the rate of expansion within our Paid Customer base, both sales-driven and through organic growth, by Net Dollar Retention Rate."
   - **Source**: Slack S-1
   - **Search term**: retention

8. "As of January 31, 2017 2018 2019 Paid Customers 37,000 59,000 88,000 Paid Customers >$100,000 135 298 575 Net Dollar Retention Rate 171 % 152 % 143 % 11 For additional information about our key business metrics, see the section titled “Management’s Discussion and Analysis of Financial Condition and ..."
   - **Source**: Slack S-1
   - **Search term**: retention

9. "In the years ended January 31, 2017, 2018 and 2019, 34%, 34%, and 36%, respectively, of our revenue was generated by Paid Customers outside of the United States."
   - **Source**: Slack S-1
   - **Search term**: Paid Customer

10. "In the periods presented, no one Paid Customer accounted for more than 3% of our revenue."
   - **Source**: Slack S-1
   - **Search term**: Paid Customer

*... and 35 more snippets in this category*

### Category: Expansion Language
**Count**: 36 snippets

1. "Since 2016, we have augmented our approach with a direct sales force and customer success professionals who are focused on driving successful adoption and expansion within organizations, whether on a free or paid subscription plan."
   - **Source**: Slack S-1
   - **Search term**: expansion

2. "We measure the number of Paid Customers > $100,000 of annual recurring revenue, or ARR, as a gauge of adoption within and expansion into large enterprises."
   - **Source**: Slack S-1
   - **Search term**: ARR

3. "Expansion within organizations on Slack is a significant contributor to our growth."
   - **Source**: Slack S-1
   - **Search term**: expansion

4. "We measure the rate of expansion within our Paid Customer base, both sales-driven and through organic growth, by Net Dollar Retention Rate."
   - **Source**: Slack S-1
   - **Search term**: retention

5. "Customer love leading to stickiness and organic expansion People love using Slack and many become advocates for wider use inside of their organizations."
   - **Source**: Slack S-1
   - **Search term**: expansion

6. "Invest in international expansion We plan to open offices and hire sales and customer experience people in additional countries and expand our presence in countries where we already operate."
   - **Source**: Slack S-1
   - **Search term**: expansion

7. "Our expansion has placed, and our expected future growth will continue to place, a significant strain on our management, customer experience, research and development, sales and marketing, administrative, financial, and other resources."
   - **Source**: Slack S-1
   - **Search term**: expansion

8. "This expansion will require us to invest significant financial and other resources to train and grow our direct sales force, in order to complement our self-service go-to-market approach ."
   - **Source**: Slack S-1
   - **Search term**: expansion

9. "Any additional international expansion efforts that we are undertaking and may undertake may not be successful."
   - **Source**: Slack S-1
   - **Search term**: expansion

10. "Our limited experience in operating our business internationally increases the risk that any potential future expansion efforts that we may undertake will not be successful."
   - **Source**: Slack S-1
   - **Search term**: expansion

*... and 26 more snippets in this category*

### Category: Ltv Cac Metrics
**Count**: 16 snippets

1. "We believe that all of these factors will contribute to a high lifetime value of an organization on Slack."
   - **Source**: Slack S-1
   - **Search term**: lifetime value

2. "In addition to government activity, privacy advocacy groups, and technology and other industries are considering various new, additional, or different self-regulatory standards that may place additional burdens on us."
   - **Source**: Slack S-1
   - **Search term**: CAC

3. "7 Table of Contents Our Growth Strategies The key elements of our growth strategies include: • Increasing the lifetime value of existing consumers."
   - **Source**: Farfetch S-1
   - **Search term**: lifetime value

4. "In determining how successful our consumer acquisition and retention strategy is, we closely monitor the initial Consumer Acquisition Cost (“CAC”), the Lifetime Value of a Consumer (“LTV”) and Platform Order Contribution Margin."
   - **Source**: Farfetch S-1
   - **Search term**: retention

5. "• CAC means demand generation expense attributable only to new consumer acquisition during a specific time period divided by the number of new consumers acquired during the same period."
   - **Source**: Farfetch S-1
   - **Search term**: CAC

6. "• LTV means cumulative Platform Order Contribution, calculated as gross profit less demand generation expense, excluding demand generation expense attributable to any new consumer acquisition, over a period of time attributable to a particular consumer cohort since the acquisition of those consumers..."
   - **Source**: Farfetch S-1
   - **Search term**: cohort

7. "We deploy our demand generation expense across a variety of channels, such as search engine marketing, search engine optimization, display advertising and affiliate marketing, and we monitor on a real-time basis the aggregate LTV of each cohort and the return on CAC across each channel."
   - **Source**: Farfetch S-1
   - **Search term**: cohort

8. "The LTV/CAC ratio illustrates the LTV on average each consumer generates as a multiple of CAC."
   - **Source**: Farfetch S-1
   - **Search term**: LTV

9. "Our increased LTV/CAC ratio demonstrates that each cohort is becoming more valuable."
   - **Source**: Farfetch S-1
   - **Search term**: cohort

10. "We believe we can generate a higher LTV over time or can spend less on demand generation to achieve a comparable return."
   - **Source**: Farfetch S-1
   - **Search term**: LTV

*... and 6 more snippets in this category*

### Category: Time Period Cohorts
**Count**: 2 snippets

1. "In the third quarter of fiscal year 2019, we incurred additional sales and marketing expenses primarily due to increased advertising efforts as well as incurring expenses in connection with holding our annual user conference, Frontiers."
   - **Source**: Slack S-1
   - **Search term**: fiscal year

2. "We expect Calculated Billings to decline or grow less quickly in the first quarter of fiscal year 2020 due to the impact of seasonality on our business."
   - **Source**: Slack S-1
   - **Search term**: fiscal year

### Category: Other
**Count**: 296 snippets

1. "Our fiscal year ends January 31."
   - **Source**: Slack S-1
   - **Search term**: fiscal year

2. "When new members joined the team, they were cut off from the rich history of communication that occurred before they arrived."
   - **Source**: Slack S-1
   - **Search term**: ARR

3. "Important messages are surrounded by useful context and users can see how fellow team members created and worked with the information and arrived at a decision."
   - **Source**: Slack S-1
   - **Search term**: ARR

4. "Paid customers typically pay on a monthly or annual basis, based on the number of users that they have on Slack."
   - **Source**: Slack S-1
   - **Search term**: Paid Customer

5. "4 Our reven ue was $105.2 million, $220.5 million, and $400.6 million in fiscal years 2017, 2018, and 2019, respectively, representing annual growth of 110% and 82%, respectively."
   - **Source**: Slack S-1
   - **Search term**: fiscal year

6. "Our growth is global with international revenue representing 34%, 34%, and 36% of total revenue in fiscal years 2017, 2018, and 2019, respectively."
   - **Source**: Slack S-1
   - **Search term**: fiscal year

7. "As a result, we incurred net losses of $146.9 million, $140.1 million, and $138.9 million in fiscal years 2017, 2018, and 2019, respectively."
   - **Source**: Slack S-1
   - **Search term**: fiscal year

8. "Grow the number of organizations on Slack and increase our paid customers We believe our market remains underpenetrated and we will continue to expand our marketing and sales efforts to reach more users and organizations and to increase the number of paid customers."
   - **Source**: Slack S-1
   - **Search term**: Paid Customer

9. "Accordingly, we will not be subject to the same new or revised accounting standards as other public companies that are not “emerging growth companies.” We will remain an “emerging growth company” until the earliest to occur of: (i) the last day of the fiscal year in which we have more than $1.07 bil..."
   - **Source**: Slack S-1
   - **Search term**: fiscal year

10. "Year Ended January 31, 2017 2018 2019 (In thousands, except per share data) Consolidated Statements of Operations Data: Revenue $ 105,153 $ 220,544 $ 400,552 Cost of revenue (1) 15,517 26,364 51,301 Gross profit 89,636 194,180 349,251 Operating expenses: Research and development (1) 96,678 141,350 1..."
   - **Source**: Slack S-1
   - **Search term**: fiscal year

*... and 286 more snippets in this category*

## Proposed New Patterns

Based on analysis of missed snippets, the following new patterns are proposed:

### Priority 1 (High Impact)

| # | Pattern Name | Regex | Would Match | Notes |
|---|--------------|-------|-------------|-------|
| 1 | `net_dollar_retention` | `r"net\s+dollar\s+(?:retention\|expansion)"` | NRR/NDRR metrics | Case-insensitive, most common cohort KPI |
| 2 | `dollar_based_retention` | `r"dollar[- ]?based\s+(?:net\s+)?(?:retention\|expansion)"` | DBNER variants | Covers "dollar-based net expansion rate" |
| 3 | `fiscal_year_cohort` | `r"(?:fiscal\s+year\s+\|FY\s*)20\d{2}\s+cohort"` | Fiscal year cohorts | Year-first ordering |
| 4 | `year_cohort` | `r"\b20\d{2}\s+cohort"` | Generic year cohorts | Simple but high-yield |
| 5 | `arr_cohort` | `r"\bARR\b.{0,30}cohort"` | ARR by cohort | Captures ARR-cohort relationship |

### Priority 2 (Medium Impact)

| # | Pattern Name | Regex | Would Match | Notes |
|---|--------------|-------|-------------|-------|
| 6 | `paid_customer_cohort` | `r"Paid\s+Customers?\s+(?:who\|that\|acquired)"` | Enterprise SaaS terms | Case-sensitive for proper noun |
| 7 | `retention_rate_pct` | `r"retention\s+rate\s+(?:of\s+)?\d+%"` | Retention percentages | Catches "retention rate of 143%" |
| 8 | `cohort_with_year` | `r"cohort\s+(?:of\s+)?(?:customers?\s+)?(?:from\|in\|acquired)\s+20\d{2}"` | Cohort year references | Flexible cohort-year association |
| 9 | `expansion_revenue` | `r"(?:expansion\|upsell\|cross-sell)\s+revenue"` | Revenue expansion | Cohort growth indicators |
| 10 | `ltv_cac_ratio` | `r"(?:LTV|lifetime\s+value)\s*[:/]\s*CAC"` | Unit economics | LTV/CAC ratio patterns |

### Priority 3 (Lower Impact)

| # | Pattern Name | Regex | Would Match | Notes |
|---|--------------|-------|-------------|-------|
| 11 | `customer_tenure_months` | `r"(?:customer|user)s?\s+(?:of|with)\s+(?:\d+|\w+)\s+months?"` | Tenure by months | Customer age measurements |
| 12 | `renewal_rate` | `r"(?:renewal|retention)\s+rate"` | Renewal metrics | Broader retention capture |
| 13 | `mrr_arr_growth` | `r"(?:MRR|ARR)\s+(?:growth|increase|expansion)"` | Recurring revenue growth | SaaS metrics |
| 14 | `churn_rate` | `r"(?:churn|attrition)\s+rate"` | Churn metrics | Inverse of retention |
| 15 | `customer_cohort_generic` | `r"customer\s+cohorts?"` | Generic cohort reference | Broad capture |

## Recommendations for GI-4

1. **Implement Priority 1 patterns first** - These will capture the highest-value cohort disclosures with minimal false positive risk

2. **Add NRR/NDRR as primary cohort signal** - Net Dollar Retention is the single most important SaaS cohort metric and appears frequently in S-1s

3. **Support year-first cohort references** - Current patterns expect 'cohort of 2019' but filings commonly use 'fiscal year 2019 cohort' or 'the 2019 cohort'

4. **Consider case sensitivity for proper nouns** - Terms like 'Paid Customer' and 'Enterprise Customer' are often capitalized as defined terms in filings

5. **Add expansion/growth context** - Cohort analysis often appears in context of revenue expansion, upsell, and cross-sell discussions

6. **Test new patterns against validation set** - Re-run `scripts/rerun_goldmine_validation.py` after implementing new patterns to measure improvement

## Appendix: Raw Snippets

Full list of all extracted cohort-related snippets:

**1.** (Slack S-1, term: 'fiscal year')
> Our fiscal year ends January 31.

**2.** (Slack S-1, term: 'NDR')
> They do so because Slack is a new layer of the business technology stack that brings together people, applications, and data – a single place where people can effectively work together, access hundreds of thousands of critical applications and services, and find important information to do their best work.

**3.** (Slack S-1, term: 'ARR')
> When new members joined the team, they were cut off from the rich history of communication that occurred before they arrived.

**4.** (Slack S-1, term: 'NDR')
> Depending on the size of the organization, this might provide tens, hundreds or even thousands of times more access to information than is available to individuals working in environments where email is the primary means of communication.

**5.** (Slack S-1, term: 'ARR')
> Important messages are surrounded by useful context and users can see how fellow team members created and worked with the information and arrived at a decision.

**6.** (Slack S-1, term: 'NDR')
> Slack has aggregated hundreds of thousands of organizations on one platform and made it easier for developers to distribute their software to any Slack-using organization.

**7.** (Slack S-1, term: 'expansion')
> Since 2016, we have augmented our approach with a direct sales force and customer success professionals who are focused on driving successful adoption and expansion within organizations, whether on a free or paid subscription plan.

**8.** (Slack S-1, term: 'Paid Customer')
> Once an organization has three or more users on a paid subscription plan, we count them as a Paid Customer.

**9.** (Slack S-1, term: 'Paid Customer')
> As of January 31, 2019, Slack had more than 600,000 organizations with three or more users, comprised of: • More than 88,000 Paid Customers, including more than 65 companies in the Fortune 100; and • More than 500,000 organizations on our Free subscription plan.

**10.** (Slack S-1, term: 'Paid Customer')
> Many of our Paid Customers have thousands of active users and our largest Paid Customers have tens of thousands of employees using Slack on a daily basis.

**11.** (Slack S-1, term: 'Paid Customer')
> During this same time, on a typical workday, users at Paid Customers averaged nine hours connected to Slack through at least one device and spent more than 90 minutes actively using Slack.

**12.** (Slack S-1, term: 'ARR')
> We measure the number of Paid Customers > $100,000 of annual recurring revenue, or ARR, as a gauge of adoption within and expansion into large enterprises.

**13.** (Slack S-1, term: 'ARR')
> We had 575 Paid Customers >$100,000 of ARR as of January 31, 2019, which accounted for approximately 40% of our revenue in fiscal year 2019 .

**14.** (Slack S-1, term: 'Paid Customer')
> Paid customers typically pay on a monthly or annual basis, based on the number of users that they have on Slack.

**15.** (Slack S-1, term: 'fiscal year')
> 4 Our reven ue was $105.2 million, $220.5 million, and $400.6 million in fiscal years 2017, 2018, and 2019, respectively, representing annual growth of 110% and 82%, respectively.

**16.** (Slack S-1, term: 'fiscal year')
> Our growth is global with international revenue representing 34%, 34%, and 36% of total revenue in fiscal years 2017, 2018, and 2019, respectively.

**17.** (Slack S-1, term: 'fiscal year')
> As a result, we incurred net losses of $146.9 million, $140.1 million, and $138.9 million in fiscal years 2017, 2018, and 2019, respectively.

**18.** (Slack S-1, term: 'expansion')
> Expansion within organizations on Slack is a significant contributor to our growth.

**19.** (Slack S-1, term: 'retention')
> We measure the rate of expansion within our Paid Customer base, both sales-driven and through organic growth, by Net Dollar Retention Rate.

**20.** (Slack S-1, term: 'retention')
> Our Net Dollar Retention Rate was 143% as of January 31, 2019.

**21.** (Slack S-1, term: 'retention')
> We believe that our Net Dollar Retention Rate is a reflection of the rapid pace of adoption that often occurs as usage spreads within and across teams.

**22.** (Slack S-1, term: 'lifetime value')
> We believe that all of these factors will contribute to a high lifetime value of an organization on Slack.

**23.** (Slack S-1, term: 'retention')
> For a definition of how we calculate Net Dollar Retention Rate and additional information about our key business metrics, see the section titled “Management’s Discussion and Analysis of Financial Condition and Results of Operations—Key Business Metrics.” What Sets Us Apart Singular focus Our development, design, partnerships, customer engagement, and investments are targeted at realizing the enorm...

**24.** (Slack S-1, term: 'expansion')
> Customer love leading to stickiness and organic expansion People love using Slack and many become advocates for wider use inside of their organizations.

**25.** (Slack S-1, term: 'Paid Customer')
> Grow the number of organizations on Slack and increase our paid customers We believe our market remains underpenetrated and we will continue to expand our marketing and sales efforts to reach more users and organizations and to increase the number of paid customers.

**26.** (Slack S-1, term: 'expansion')
> Invest in international expansion We plan to open offices and hire sales and customer experience people in additional countries and expand our presence in countries where we already operate.

**27.** (Slack S-1, term: 'retention')
> • If we are unable to attract new users and organizations, convert users of and organizations on our free version into paid customers, grow or maintain our Net Dollar Retention Rate, expand usage within organizations on Slack, and sell premium subscription plans or develop new features, integrations, capabilities, and enhancements that achieve market acceptance, our revenue growth and profitabilit...

**28.** (Slack S-1, term: 'fiscal year')
> Accordingly, we will not be subject to the same new or revised accounting standards as other public companies that are not “emerging growth companies.” We will remain an “emerging growth company” until the earliest to occur of: (i) the last day of the fiscal year in which we have more than $1.07 billion in annual revenue; (ii) the date we qualify as a “large accelerated filer,” with at least $700 ...

**29.** (Slack S-1, term: 'fiscal year')
> Year Ended January 31, 2017 2018 2019 (In thousands, except per share data) Consolidated Statements of Operations Data: Revenue $ 105,153 $ 220,544 $ 400,552 Cost of revenue (1) 15,517 26,364 51,301 Gross profit 89,636 194,180 349,251 Operating expenses: Research and development (1) 96,678 141,350 157,538 Sales and marketing (1) 104,006 140,188 233,191 General and administrative (1) 37,455 56,493 ...

**30.** (Slack S-1, term: 'retention')
> As of January 31, 2017 2018 2019 Paid Customers 37,000 59,000 88,000 Paid Customers >$100,000 135 298 575 Net Dollar Retention Rate 171 % 152 % 143 % 11 For additional information about our key business metrics, see the section titled “Management’s Discussion and Analysis of Financial Condition and Results of Operations—Key Business Metrics.” Non-GAAP Financial Measures In addition to our results ...

**31.** (Slack S-1, term: 'fiscal year')
> Year Ended January 31, 2017 2018 2019 (In thousands) Calculated Billings $ 143,390 $ 289,013 $ 516,972 Free Cash Flow $ (114,038 ) $ (57,661 ) $ (97,239 ) Tender offer payments and repurchases deemed compensation (1) 8,033 39,374 — Adjusted Free Cash Flow $ (106,005 ) $ (18,287 ) $ (97,239 ) __________________ (1) In fiscal years 2017 and 2018, we made cash payments of $8.0 million and $39.4 milli...

**32.** (Slack S-1, term: 'fiscal year')
> We have incurred significant net losses in each year since our inception, including net losses of $146.9 million , $140.1 million , and $138.9 million in fiscal years 2017, 2018, and 2019, respectively.

**33.** (Slack S-1, term: 'retention')
> In future periods, our revenue growth could slow or our revenue could decline for a number of reasons, including any failure to increase the number of organizations on Slack, increase our number of paid customers, or grow or maintain our Net Dollar Retention Rate, a decrease in the growth of our overall market, our failure, for any reason, to continue to capitalize on growth opportunities, slowing...

**34.** (Slack S-1, term: 'retention')
> We believe our revenue growth depends on a number of factors, including, but not limited to, our ability to: • attract new users and organizations; • provide excellent customer experience; • grow or maintain our Net Dollar Retention Rate, expand usage within organizations on Slack, and sell premium versions of Slack; • convert users of and organizations on our free version into paid customers; • i...

**35.** (Slack S-1, term: 'expansion')
> Our expansion has placed, and our expected future growth will continue to place, a significant strain on our management, customer experience, research and development, sales and marketing, administrative, financial, and other resources.

**36.** (Slack S-1, term: 'retention')
> If we fail to manage our anticipated growth and change in a manner that preserves the key aspects of our corporate culture, the quality of Slack may suffer, which could negatively affect our brand and reputation and harm our ability to attract users, employees, and organizations, and to grow or maintain our Net Dollar Retention Rate.

**37.** (Slack S-1, term: 'customer base')
> As our paid customer base continues to grow, we will need to expand our account management, customer service and other personnel, our partners, our features, and our security offerings to provide personalized account management and customer service as well as personalized features, integrations and capabilities.

**38.** (Slack S-1, term: 'retention')
> Our quarterly results of operations may fluctuate from quarter to quarter as a result of a number of factors, many of which are outside of our control and may be difficult to predict, including, but not limited to: • the level of demand for Slack; • our ability to grow or maintain our Net Dollar Retention Rate, expand usage within organizations on Slack, and sell premium versions of Slack; • our a...

**39.** (Slack S-1, term: 'customer base')
> New competitors or alliances among competitors may emerge and rapidly acquire significant market share due to factors such as greater brand name recognition, a larger existing user and/or 16 customer base, superior product offerings, a larger or more effective sales organization, and significantly greater financial, technical, marketing, and other resources and experience.

**40.** (Slack S-1, term: 'retention')
> If we are unable to attract new users and organizations, convert users of and organizations on our free version into paid customers, grow or maintain our Net Dollar Retention Rate, expand usage within organizations on Slack, and sell premium subscription plans or develop new features, integrations, capabilities, and enhancements that achieve market acceptance, our revenue growth and profitability ...

**41.** (Slack S-1, term: 'retention')
> To increase our revenue and achieve and maintain profitability, we must add new users and organizations, convert users of and organizations on our free version into paid customers, grow or maintain our Net Dollar Retention Rate, expand usage within organizations on Slack, and sell premium subscription plans.

**42.** (Slack S-1, term: 'Paid Customer')
> We encourage organizations on our free version to upgrade to paid versions of Slack and paid customers of Standard to upgrade to our premium subscription plans, Plus or Enterprise Grid, through in-product prompts and notifications, by recommending additional features and by providing customer support that explains the additional capabilities of our paid and premium plans.

**43.** (Slack S-1, term: 'retention')
> Numerous factors, however, may impede our ability to add new users and organizations, convert users of and 17 organizations on our free version into paid customers, grow and maintain our Net Dollar Retention Rate, expand usage within organizations on Slack, and sell premium subscription plans, including our inability to convert organizations using our free version into paid customers, failure to a...

**44.** (Slack S-1, term: 'Paid Customer')
> See also “—Failure to effectively develop and expand our direct sales capabilities could harm our ability to increase the number of organizations on Slack and achieve broader market acceptance of Slack.” Our ability to attract new users and organizations and increase revenue from existing paid customers depends in large part on our ability to continually enhance and improve Slack and the features,...

**45.** (Slack S-1, term: 'renewal')
> While many of our subscriptions provide for automatic renewal, organizations have no obligation to renew a subscription after the expiration of the term, and we cannot ensure that organizations will renew subscriptions with a similar contract period, with the same or greater number of users, or for the same subscription plan or upgrade to Plus or Enterprise Grid.

**46.** (Slack S-1, term: 'Paid Customer')
> With our fair billing practices, we may also not earn as much revenue as anticipated if the actual numbers of users in a paid customer decreases during the subscription period.

**47.** (Slack S-1, term: 'Paid Customer')
> Organizations may or may not renew their subscriptions as a result of a number of factors, including their satisfaction or dissatisfaction with Slack or services, our pricing or pricing structure, the pricing or capabilities of the products and services offered by our competitors, the effects of economic conditions, or reductions in our paid customers’ spending levels.

**48.** (Slack S-1, term: 'retention')
> In the past, few of our paid customers have elected to downgrade or not to renew agreements with us, but it is difficult to accurately predict long-term Net Dollar Retention Rates.

**49.** (Slack S-1, term: 'retention')
> Having organizations on multiple subscription plans also makes it more difficult to accurately predict long-term Net Dollar Retention Rates.

**50.** (Slack S-1, term: 'Paid Customer')
> Since organizations on Slack rely on Slack to communicate, collaborate, and access and complete their work, which in many cases includes entire organizations that complete substantially all of their work functions on Slack, any outage on Slack would impair the ability of organizations on Slack and their users to perform their work, which would negatively impact our brand, reputation, and customer ...

**51.** (Slack S-1, term: 'Paid Customer')
> Any of the above circumstances or events may harm our reputation, cause organizations on Slack to terminate their agreements with us, impair our ability to obtain subscription renewals from organizations on Slack, impair our ability to grow the base of users and organizations on Slack, subject us to financial penalties and liabilities under our service level agreements with our paid customers, and...

**52.** (Slack S-1, term: 'Paid Customer')
> Further, if a channel is shared between paid customers or workspaces, the above risks, vulnerabilities, and threats may be “inherited” or transferred from one paid customer or workspace to another.

**53.** (Slack S-1, term: 'ARR')
> Despite significant efforts to create security barriers to such threats, it is virtually impossible for us to entirely mitigate these risks, especially where they are attributable to the behavior of independent third parties beyond our control.

**54.** (Slack S-1, term: 'retention')
> Security breaches impacting Slack or integrations on Slack could result in a risk of loss, unavailability, or unauthorized disclosure of this information, which, in turn, could lead to litigation, governmental audits, and investigations and possible liability (including regulatory fines), damage our relationships with existing users and organizations on Slack, and have a negative impact on our abi...

**55.** (Slack S-1, term: 'retention')
> Further, if a high-profile security breach occurs with respect to another software company with communication, collaboration, data collection, and integrations, our users and potential users could lose trust in the security of such solutions providers generally, which could adversely impact our ability to attract organizations to Slack or grow or maintain our Net Dollar Retention Rate.

**56.** (Slack S-1, term: 'CAC')
> In addition to government activity, privacy advocacy groups, and technology and other industries are considering various new, additional, or different self-regulatory standards that may place additional burdens on us.

**57.** (Slack S-1, term: 'retention')
> Any such investigation or charges by European and/or Swiss data protection authorities and/or the FTC could have a negative effect on our existing business and on our ability to attract new users and organizations and to grow or maintain our Net Dollar Retention Rate.

**58.** (Slack S-1, term: 'retention')
> The GDPR enhances data protection obligations for processors and controllers of Personal Data, including, for example, expanded disclosures about how Personal Data is to be used, limitations on retention of information, mandatory data breach notification requirements, and additional obligations on service providers (such 23 as any third parties to whom we may transfer Personal Data).

**59.** (Slack S-1, term: 'renewal')
> Because we recognize subscription revenue over the subscription term, downturns or upturns in new sales and renewals are not immediately reflected in full in our results of operations.

**60.** (Slack S-1, term: 'ARR')
> Our subscription arrangements generally have monthly or annual contractual terms.

**61.** (Slack S-1, term: 'Paid Customer')
> As a result, an increase in paid customers could result in our recognition of more costs than revenue in the earlier portion of the subscription term, and we may not attain profitability in any given period.

**62.** (Slack S-1, term: 'retention')
> High-quality user and customer education and customer experience has been key to our brand and is important for the successful marketing and sale of Slack, for the conversion of organizations on our free version into paid customers, and for growth or maintenance of our Net Dollar Retention Rate.

**63.** (Slack S-1, term: 'expansion')
> This expansion will require us to invest significant financial and other resources to train and grow our direct sales force, in order to complement our self-service go-to-market approach .

**64.** (Slack S-1, term: 'Paid Customer')
> Organizations on Slack may merge with other entities who use alternative software that addresses one or more of the problems that Slack solves and, during weak economic times, there is an increased risk that one or more of our paid customers will file for bankruptcy protection, either of which may harm our revenue, profitability, and results of operations.

**65.** (Slack S-1, term: 'Paid Customer')
> We also face risk from international paid customers that file for bankruptcy protection in foreign jurisdictions, particularly given that the application of foreign bankruptcy laws may be more difficult to predict.

**66.** (Slack S-1, term: 'retention')
> If we fail to successfully promote and maintain our brand, or incur substantial expenses in an unsuccessful attempt to promote and maintain our brand, we may fail to attract new organizations to Slack or to grow or maintain our Net Dollar Retention Rate to the extent necessary to realize a sufficient return on our brand-building efforts, and our business, results of operations, and financial condi...

**67.** (Slack S-1, term: 'Paid Customer')
> To the extent that some of these users and organizations do not become, or lead others to become, paid customers, we will not realize the intended benefits of this marketing strategy, which incurs costs as we must pay to host our free version, and our ability to grow our business may be harmed and our results of operations and financial condition could suffer.

**68.** (Slack S-1, term: 'ARR')
> We may not carry sufficient business interruption insurance to compensate us for losses that may occur as a result of any events that cause interruptions in our service.

**69.** (Slack S-1, term: 'ARR')
> In the event that our AWS service agreements are terminated, or there is a lapse of service, interruption of Internet service provider connectivity or damage to such facilities, we could experience interruptions in access to Slack as well as delays and additional expense in arranging new facilities and services.

**70.** (Slack S-1, term: 'ARR')
> In addition to risks related to license requirements, usage of open source software can lead to greater risks than use of third-party commercial software, as open source licensors generally do not provide warranties or assurance of title or controls on origin of the software.

**71.** (Slack S-1, term: 'ARR')
> In addition, many of the risks associated with usage of open source software, such as the lack of warranties or assurances of title, cannot be eliminated, and could, if not properly addressed, negatively affect our business.

**72.** (Slack S-1, term: 'Paid Customer')
> We provide service level commitments under certain of our paid customer contracts.

**73.** (Slack S-1, term: 'Paid Customer')
> Certain of our paid customer agreements contain service level agreements, under which we guarantee specified minimum availability of Slack.

**74.** (Slack S-1, term: 'Paid Customer')
> From time to time, we have granted credits to paid customers pursuant to the terms of these agreements.

**75.** (Slack S-1, term: 'Paid Customer')
> If we are unable to meet the stated service level commitments to our paid customers or suffer extended periods of unavailability of Slack, we may be contractually obligated to provide affected paid customers with service credits for future subscriptions, or paid customers could elect to terminate and receive refunds for prepaid amounts related to unused subscriptions.

**76.** (Slack S-1, term: 'Paid Customer')
> Our revenue, other results of operations, and financial condition could be harmed if we suffer unscheduled downtime that exceeds the service level commitments under our agreements with our paid customers, and any extended service outages could adversely affect our business and reputation as paid customers may elect not to renew and we could lose future sales.

**77.** (Slack S-1, term: 'Paid Customer')
> We may function as a HIPAA business associate for certain of our paid customers and, as such, are subject to applicable privacy and data security requirements.

**78.** (Slack S-1, term: 'Paid Customer')
> If we fail to comply with any of these requirements, we could be subject to significant liability, which could harm our reputation and adversely affect our business as well as our ability to attract new and retain existing paid customers.

**79.** (Slack S-1, term: 'Paid Customer')
> Certain of our paid customers are HIPAA covered entities and service providers, and in that context we may function as a business associate under HIPAA.

**80.** (Slack S-1, term: 'retention')
> If we are unable to meet the requirements of HIPAA, our business associate agreements or state health privacy laws, we could face contractual liability or civil and criminal liability under HIPAA, all of which can have an adverse impact on our business and generate negative publicity, which, in turn, can have an adverse impact on our ability to attract new paid customers and to grow or maintain ou...

**81.** (Slack S-1, term: 'renewal')
> We may also be subject to consumer privacy or consumer protection laws that may impact our sales, marketing, and compliance efforts, including laws related to subscriptions, billing, and auto-renewal.

**82.** (Slack S-1, term: 'retention')
> These laws, as well as any changes in these laws, could adversely affect our free version of Slack and make it more difficult for us to grow or maintain our Net Dollar Retention Rate, upgrade organizations on Slack, and attract new organizations to Slack.

**83.** (Slack S-1, term: 'renewal')
> Additionally, we have in the past, are currently, and may from time to time in the future become the subject of inquiries and other actions by regulatory authorities as a result of our business practices, including our subscription, billing, and auto-renewal policies.

**84.** (Slack S-1, term: 'retention')
> In the event that access to Slack is restricted, in whole or in part, in one or more countries or our competitors are able to successfully penetrate geographic markets that we cannot access, our ability to grow or maintain our Net Dollar Retention Rate may be adversely affected, we may not be able to maintain or grow our revenue as anticipated and our business, results of operations, and financial...

**85.** (Slack S-1, term: 'fiscal year')
> In fiscal years 2017, 2018, and 2019, our non-U.S.

**86.** (Slack S-1, term: 'expansion')
> Any additional international expansion efforts that we are undertaking and may undertake may not be successful.

**87.** (Slack S-1, term: 'ARR')
> These risks include, among other things: • unexpected costs and errors in the localization of Slack, including translation into foreign languages and adaptation for local culture, practices, and regulatory requirements; • lack of familiarity and burdens of complying with foreign laws, legal standards, privacy standards, regulatory requirements, tariffs, and other barriers, and the risk of penaltie...

**88.** (Slack S-1, term: 'expansion')
> Our limited experience in operating our business internationally increases the risk that any potential future expansion efforts that we may undertake will not be successful.

**89.** (Slack S-1, term: 'Paid Customer')
> Today, our contracts with paid customers outside of the United States are sometimes denominated in local currencies.

**90.** (Slack S-1, term: 'Paid Customer')
> Over time, an increasing portion of our contracts with paid customers outside of the United States may be denominated in local currencies.

**91.** (Slack S-1, term: 'Paid Customer')
> We may be required to defer recognition of revenue for a significant period of time after entering into an agreement due to a variety of factors, including, among other things, whether: • the paid customer fails to deploy Slack to as many users as contemplated in the agreement given that, in many of our transactions, revenue is reduced in the form of fair billing credits we provide to paid custome...

**92.** (Slack S-1, term: 'Paid Customer')
> Although we strive to enter into agreements that meet the criteria under GAAP for current revenue recognition on delivered elements, our agreements are often subject to negotiation and revision based on the demands of our paid customers.

**93.** (Slack S-1, term: 'Paid Customer')
> In the past, we have sometimes adjusted our prices either for individual paid customers in connection with long-term agreements or unique situations.

**94.** (Slack S-1, term: 'retention')
> Similarly, certain competitors may use marketing strategies that enable them to acquire users more rapidly or at a lower cost than us, or both, and we may be unable to attract new users and organizations or grow or maintain our Net Dollar Retention Rate based on our historical pricing.

**95.** (Slack S-1, term: 'retention')
> There can be no assurance that we will not be forced to engage in price-cutting initiatives or to increase our marketing and other expenses to attract users and organizations to Slack and to grow or maintain our Net Dollar Retention Rate in response to competitive or other pressures, either of which could materially and adversely affect our business, results of operations, and financial condition.

**96.** (Slack S-1, term: 'fiscal year')
> We may take advantage of these exemptions until we are no longer an “emerging growth company,” which could be as long as five full fiscal years following the listing of our Class A common stock on the NYSE.

**97.** (Slack S-1, term: 'fiscal year')
> In fiscal year 2019, we implemented a new ERP system, including our systems for tracking revenue recognition.

**98.** (Slack S-1, term: 'ARR')
> We base our estimates on historical experience and on various other assumptions that we believe to be reasonable under the circumstances, as provided in the section titled “Management’s Discussion and Analysis of Financial Condition and Results of Operations.” The results of these estimates form the basis for making judgments about the carrying values of assets, liabilities and equity, and the amo...

**99.** (Slack S-1, term: 'Paid Customer')
> Changes in tax laws or regulations in the various tax jurisdictions we are subject to that are applied adversely to us or our paid customers could increase the costs of Slack and harm our business.

**100.** (Slack S-1, term: 'Paid Customer')
> These events could require us or our paid customers to pay additional tax amounts on a prospective or retroactive basis, as well as require us or our paid customers to pay fines and/or penalties and interest for past amounts deemed to be due.

*... 379 additional snippets omitted for brevity*

---

**Generated by**: `scripts/gi1_pattern_analysis.py`
**Date**: 2025-12-17
**Task**: GI-1 (Investigate Cohort Pattern Gaps)