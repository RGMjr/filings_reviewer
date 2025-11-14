
#%%
# Fetch the most recent S-1 and S-1/A filings from the SEC EDGAR system
# and extract key metadata including company name, CIK, filing date, form type,
# and URLs to the filing text and HTML documents.

# %%
import requests, time, pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Jacki Huang (xinwenh@mit.edu)"}
BASE = "https://www.sec.gov/Archives/edgar/full-index"
FORMS = {"S-1","S-1/A"}
MAX_RESULTS = 20

#%%
def quarter_list(years=2):
    now = datetime.now()
    out, y, q = [], now.year, (now.month-1)//3+1
    for _ in range(years*4):
        out.append((y,q))
        q -= 1
        if q==0: q, y = 4, y-1
    return out

def parse_idx(txt):
    lines = txt.splitlines()
    start = next(i for i,l in enumerate(lines) if l.startswith("-----"))+1
    rows=[]
    for l in lines[start:]:
        parts=l.split()
        if len(parts)<5: continue
        form=parts[0]
        if form not in FORMS: continue
        cik,date,fn=parts[-3],parts[-2],parts[-1]
        co=" ".join(parts[1:-3])
        edgar_txt="https://www.sec.gov/Archives/"+fn
        edgar_index_page=edgar_txt.replace(".txt","-index.htm")
        rows.append(dict(company=co,cik=cik.zfill(10),filing_date=date,
                         form_type=form,edgar_txt=edgar_txt,
                         edgar_index_page=edgar_index_page))
    return rows

def fetch_quarter(y,q):
    r=requests.get(f"{BASE}/{y}/QTR{q}/form.idx",headers=HEADERS,timeout=60)
    return parse_idx(r.text) if r.ok else []

def get_s1_html(idx_html_url):
    """Scrape the index.htm page and pull the Document href for Type=S-1/S-1A."""
    try:
        r=requests.get(idx_html_url,headers=HEADERS,timeout=60)
        r.raise_for_status()
        soup=BeautifulSoup(r.text,"html.parser")
        table=soup.find("table",{"class":"tableFile"})
        if not table: return None
        for row in table.find_all("tr")[1:]:
            cols=[c.get_text(strip=True) for c in row.find_all("td")]
            if len(cols)>=4 and cols[3] in FORMS:   # Type column
                link=row.find("a")
                if link and link["href"]:
                    return "https://www.sec.gov"+link["href"]
    except Exception as e:
        print("Error on",idx_html_url,e)
    return None

#%%
def fetch_company_metadata(cik):
    """Fetch SIC and ticker for a given company CIK"""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=60)
        if not r.ok:
            return None, None, None
        data = r.json()
        sic = data.get("sic")
        sic_desc = data.get("sicDescription")
        tickers = data.get("tickers") or []
        ticker = tickers[0] if tickers else None
        return ticker, sic, sic_desc
    except Exception as e:
        print("Metadata error for", cik, e)
        return None, None, None

# %%
def collect_recent_s1(max_results=MAX_RESULTS):
    all=[]
    for y,q in quarter_list(2):
        all+=fetch_quarter(y,q); time.sleep(0.25)
    df=pd.DataFrame(all).drop_duplicates(["cik","filing_date","form_type"])
    df["filing_date"]=pd.to_datetime(df["filing_date"],errors="coerce")
    df=df.sort_values("filing_date",ascending=False).head(max_results)

    # fetch metadata for each company
    tickers, sics, sic_descs = [], [], []
    for cik in df["cik"]:
        t,s,sd = fetch_company_metadata(cik)
        tickers.append(t); sics.append(s); sic_descs.append(sd)
        time.sleep(0.1)  # polite delay
    df["ticker"]=tickers
    df["sic"]=sics
    df["company_type"]=sic_descs

    # fetch actual html doc
    df["edgar_html"]=[get_s1_html(u) for u in df["edgar_index_page"]]

    return df[["company","cik","ticker","sic","company_type",
               "filing_date","form_type","edgar_txt","edgar_index_page","edgar_html"]]

# %%
df=collect_recent_s1()
print(df)
df.to_csv("s1_fetch_records.csv",index=False)

# %%
# Download and parse the filings

#%%
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import ftfy

HEADERS = {"User-Agent": "Jacki Huang (xinwenh@mit.edu)"}

#%%
# Load your edgar_html links from CSV
records = pd.read_csv("s1_fetch_records.csv")   # contains column "edgar_html"
urls = records["edgar_html"].dropna().tolist()

# Define your keywords (case-insensitive search)
KEYWORDS = ["paid customers", "MAU", "bookings", "retention", "active users", "customer"]

def fetch_plain_text(url):
    """Fetch SEC filing HTML and convert to plain text."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        return ftfy.fix_text(text)   # <-- normalize encodings
    except Exception as e:
        print("Failed on", url, e)
        return ""

def split_paragraphs(text):
    """Split text into paragraphs (simple heuristic)."""
    paras = [p.strip() for p in text.split("\n") if len(p.strip()) > 40]  # skip very short lines
    return paras

def keyword_hits(paragraphs, keywords):
    """Return paragraphs containing any keyword."""
    hits = []
    for p in paragraphs:
        for kw in keywords:
            if kw.lower() in p.lower():
                hits.append((kw, p))
                break
    return hits

results = []

#%%
for url in urls[:3]:  # limit for testing
    print(f"Processing: {url}")
    text = fetch_plain_text(url)
    paras = split_paragraphs(text)
    hits = keyword_hits(paras, KEYWORDS)
    for kw, p in hits:
        results.append({"url": url, "keyword": kw, "paragraph": p})
    time.sleep(0.25)  # polite delay

# Save results
hits_df = pd.DataFrame(results)
hits_df.to_csv("s1_keyword_paragraphs.csv", index=False)

print(hits_df.head(10))



#%%
# Use openAI to extract customer metrics from S-1 filings

# %%
"""
SEC S-1 Customer Metrics Extractor (LLM-powered)
------------------------------------------------
Replicates exactly what we’re doing in chat:
- Fetch each S-1 HTML
- Surface text + tables + figure/graph captions/alt-text
- Prompt an LLM to extract every customer/user metric VALUE, DEFINITION, or CALCULATION
- Return a single table with required columns
- Prints sample rows and saves CSV/JSON

Requirements:
  pip install openai requests beautifulsoup4 lxml python-dotenv pandas

Auth:
  export OPENAI_API_KEY="sk-..."   # or use a .env file with OPENAI_API_KEY=...

Run:
  python s1_customer_metrics_llm.py
"""

import os
import re
import json
import time
import math
import html
import uuid
import itertools
from typing import List, Dict, Any, Iterable

import requests
import pandas as pd
from bs4 import BeautifulSoup, Tag, NavigableString
from dotenv import load_dotenv
from openai import OpenAI

#%%
# ------------------------- CONFIG -------------------------
load_dotenv()  # Load environment variables from .env file
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

OPENAI_MODEL = "gpt-4o" 

#%%
# SEC polite headers (important so EDGAR doesn't block you)
REQ_HEADERS = {
    "User-Agent": "MetricsExtractor/1.0 (contact: xinwenh@mit.edu)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Input URLs (you can replace or pass from CLI)
S1_URLS = [
    "https://www.sec.gov/Archives/edgar/data/1764925/000162828019004786/slacks-1.htm",
    "https://www.sec.gov/Archives/edgar/data/1524566/000162828025043113/wealthfront-sx1.htm",
    "https://www.sec.gov/Archives/edgar/data/1746618/000119312519157516/d669074ds1a.htm",
    "https://www.sec.gov/Archives/edgar/data/1792789/000119312520292381/d752207ds1.htm",
]

# The exact synonym set you specified (treated as equivalent to “customer/user”)
CUSTOMER_SYNONYMS = [
    "customer","customers","user","users","client","clients","subscriber","subscribers",
    "member","members","account","accounts","buyer","buyers","consumer","consumers",
    "organization","organizations","merchant","merchants","host","hosts","driver","drivers",
    "partner","partners","vendor","vendors","tenant","tenants","seller","sellers","creator","creators"
]

# Metric keywords (as specified)
METRIC_KEYWORDS = [
    "active users","paying users","subscribers","customer count","accounts","registered users",
    "transactions","revenue per user","churn","user retention","new customers","gross adds","net adds",
    "customer acquisition cost","ltv","clv","cac","payback period","retention","nrr","mrr","arpu","arppu",
    "average order value","orders per customer","purchase frequency","repeat purchase rate",
    "cohort analysis","lifetime value","active customers","paid customers","net dollar retention",
    "daily active users","monthly active users","orders","gross order volume","gov"
]

# Definition / calculation cues
DEFINITION_CUES = [
    "definition","defined as","we define","means","refers to","calculated as","computed as",
    "formula","calculation method","determined by","measured by","represents","derived from","we measure"
]

# LLM chunking
MAX_CHARS_PER_CHUNK = 16000  # conservative for gpt-4o
SECTION_HEADERS_HINTS = [
    "prospectus summary","key business metrics","md&a","management’s discussion and analysis",
    "business","risk factors","selected consolidated financial","key operating metrics",
    "market opportunity","our platform","growth strategy"
]

# Output schema keys
OUTPUT_FIELDS = [
    "company","metric_name","value","period","source_type","source_details",
    "url","missing_data_note","extracted_type"
]

# %%
HEADERS = {
    "User-Agent": "MetricsExtractor/1.0 (contact: xinwenh@mit.edu)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
LLM_MODEL = "gpt-4o"
CHUNK_SIZE = 8000        # characters
MAX_RETRIES = 2
TIMEOUT = 90             # seconds per chunk

def fetch_clean_text(url: str) -> str:
    """Download and strip HTML to visible text only."""
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script","style","noscript"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    # Only keep first ~100k chars (relevant early sections)
    return text[:100000]

def chunk_text(text, size=CHUNK_SIZE):
    return [text[i:i+size] for i in range(0, len(text), size)]

#%%
# =================== IMPROVED LLM PROMPT ===================

def extract_metrics_from_chunk(text, url):
    """
    Send a chunk of S-1 text to the LLM and extract clean JSON of metrics.
    """
    prompt = f"""
You are a precise SEC S-1 parser that extracts *customer-related metrics* from the text below.

Your task:
- Extract every relevant **metric value**, **definition**, or **calculation** mentioning customers/users or equivalents.
- Treat these as equivalent terms: {", ".join(CUSTOMER_SYNONYMS)}.
- Focus on any metric using these words: {", ".join(METRIC_KEYWORDS)}.
- Also extract any definition or formula phrase using these: {", ".join(DEFINITION_CUES)}.

For each metric, return a clean JSON object with this exact schema:

{{
  "company": "Company name as written in filing",
  "metric_name": "Name of the customer metric (e.g. active users, paying customers, churn rate)",
  "value": "Numeric or textual metric value (keep symbols and ~approximate text as in source)",
  "period": "Time period or date phrase as written (e.g. 'as of January 31, 2019', 'FY 2024')",
  "source_type": "text" | "table" | "graph",
  "source_details": "Brief context or section (e.g. 'Prospectus Summary', 'Key Metrics Table')",
  "url": "{url}",
  "missing_data_note": "" | "not found" | "not reported",
  "extracted_type": "value" | "definition" | "calculation"
}}

Rules:
- Each unique metric, definition, or calculation = one JSON object.
- Do not invent data. Quote text as-is when uncertain.
- Return only a **JSON array**; no commentary or extra text.

Text to analyze:
{text}
"""
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "You are a structured data extractor that outputs strict JSON only."},
                {"role": "user", "content": prompt}
            ],
            timeout=TIMEOUT
        )
        content = resp.choices[0].message.content.strip()
        start, end = content.find("["), content.rfind("]") + 1
        if start == -1:
            return []
        data = json.loads(content[start:end])
        # Enforce field consistency
        clean = []
        for d in data:
            obj = {k: d.get(k, "") for k in [
                "company","metric_name","value","period","source_type",
                "source_details","url","missing_data_note","extracted_type"
            ]}
            # normalize values
            obj["url"] = url
            if not obj["missing_data_note"]:
                obj["missing_data_note"] = ""
            if obj["extracted_type"] not in ["value","definition","calculation"]:
                obj["extracted_type"] = "value"
            clean.append(obj)
        return clean
    except Exception as e:
        print(f"LLM parse error: {e}")
        return []


def process_s1(url):
    print(f"\nProcessing {url}")
    text = fetch_clean_text(url)
    chunks = chunk_text(text)
    all_rows = []
    for i, chunk in enumerate(chunks):
        print(f"   → Chunk {i+1}/{len(chunks)}")
        data = extract_metrics_from_chunk(chunk, url)
        if data:
            print(f"     {len(data)} metrics found")
            all_rows.extend(data)
        time.sleep(0.6)
    return all_rows

#%%
if __name__ == "__main__":
    all_data = []
    for url in S1_URLS:
        try:
            all_data += process_s1(url)
        except Exception as e:
            print(f"Skipped {url} due to {e}")

    df = pd.DataFrame(all_data)
    print(f"\nExtracted {len(df)} rows total")
    if not df.empty:
        print(json.dumps(df.head(2).to_dict(orient="records"), indent=2))
    df.to_csv("s1_customer_metrics_extracted.csv", index=False)
    print("Saved to s1_customer_metrics_extracted.csv")
# %%
