# Alternative Architectural Options for SEC Filings Analysis

**Created**: 2025-12-23
**Status**: Analysis Document
**Purpose**: Evaluate three dramatically different architectural approaches that could improve upon the current system

---

## Executive Summary

The current architecture is a **sequential extraction pipeline** combining rule-based processing with selective LLM enhancement. While production-ready with 87% test coverage and ~$0.10/filing cost, it faces fundamental limitations:

| Current Limitation | Root Cause | Impact |
|-------------------|------------|--------|
| Table structure loss | HTML→text normalization destroys cell boundaries | Cross-row matching errors, ambiguous values |
| Two-tier quality | CandidateGenerator and ValueExtractor evolved separately | Filters in one don't apply to other |
| Brittle parsing | Regex/keyword patterns break on format variations | Edge cases require constant maintenance |
| LLM inconsistency | Single-pass extraction with no verification | Quality depends on prompt engineering |
| Schema rigidity | Fixed metric taxonomy embedded in code | Adding new metrics requires code changes |

This document presents **three alternative architectures** that fundamentally reimagine the extraction approach:

1. **Vision-Language Document Understanding** — Treat filings as visual documents
2. **Knowledge Graph + Semantic Retrieval** — Ontology-driven extraction with embeddings
3. **Multi-Agent Verification System** — Self-correcting LLM agents with debate

---

## Alternative 1: Vision-Language Document Understanding

### Concept

Instead of parsing HTML to text and losing structural information, treat SEC filings as **visual documents** and use document understanding models that natively preserve layout, table structure, and reading order.

```
┌────────────────────────────────────────────────────────────────────────┐
│                    CURRENT APPROACH (LOSSY)                             │
│                                                                         │
│   HTML Document → BeautifulSoup → Text Extraction → Regex/Keywords     │
│         ↓                               ↓                               │
│   Structure preserved         Structure LOST (tables become text)       │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│                    ALTERNATIVE 1 (STRUCTURE-PRESERVING)                 │
│                                                                         │
│   HTML Document → PDF/Image Render → Vision-Language Model              │
│         ↓                                    ↓                          │
│   Visual layout preserved          Tables understood natively           │
└────────────────────────────────────────────────────────────────────────┘
```

### Architecture

```
SEC Filing (HTML)
    │
    ├──► PDF Rendering (wkhtmltopdf / Playwright)
    │         │
    │         ▼
    │    Page Images (300 DPI)
    │         │
    │         ▼
    │    ┌───────────────────────────────────┐
    │    │  Document Understanding Model     │
    │    │  (LayoutLMv3 / DocFormer / DONUT) │
    │    │                                   │
    │    │  • Table structure preserved      │
    │    │  • Cell boundaries explicit       │
    │    │  • Reading order encoded          │
    │    │  • Section hierarchy understood   │
    │    └───────────────────────────────────┘
    │              │
    │              ▼
    │    Structured Extraction Prompts
    │    ┌─────────────────────────────────────────────────┐
    │    │ "Extract customer metrics from this table:      │
    │    │  - Metric name (row label)                      │
    │    │  - Value (same row, numeric column)             │
    │    │  - Period (column header)"                      │
    │    └─────────────────────────────────────────────────┘
    │              │
    │              ▼
    └──► Structured JSON Output ──► PostgreSQL
```

### Key Technologies

| Component | Options | Notes |
|-----------|---------|-------|
| **Document Model** | LayoutLMv3, DocFormer, DONUT | Pre-trained on document understanding tasks |
| **Fine-tuning** | SEC-specific training | ~500-1000 labeled examples needed |
| **Table Extraction** | Table Transformer, TableFormer | Specialized for tabular data |
| **OCR Backup** | Tesseract, PaddleOCR | For scanned/image-based filings |

### Implementation Approach

**Phase 1: Proof of Concept (2-3 weeks)**
1. Select 100 diverse S-1 filings covering all table formats
2. Render to PDF/images at 300 DPI
3. Fine-tune LayoutLMv3 on table extraction task
4. Evaluate vs current approach on same test set

**Phase 2: Production Pipeline (4-6 weeks)**
1. Build rendering infrastructure (parallelized PDF generation)
2. Deploy document model inference (GPU cluster or managed service)
3. Create structured output parsing and validation
4. Implement fallback to current approach for edge cases

**Phase 3: Optimization (2-3 weeks)**
1. Distill model for faster inference
2. Implement caching for processed pages
3. Add quality scoring based on model confidence

### Advantages

| Advantage | Impact |
|-----------|--------|
| **No more table parsing issues** | Cell boundaries are visual, not textual |
| **Robust to HTML variations** | Visual rendering normalizes formats |
| **Handles charts/images** | Can extract from visual elements current approach ignores |
| **Future-proof** | Works on PDFs, scans, any visual format |
| **Better accuracy** | Document understanding models achieve 95%+ on similar tasks |

### Disadvantages

| Disadvantage | Mitigation |
|--------------|------------|
| **GPU requirement** | Use managed inference (AWS Bedrock, Azure AI) or spot instances |
| **Training data needed** | Bootstrap with synthetic labels from current extractions |
| **Higher latency** | Batch processing, page-level caching |
| **Less interpretable** | Model attention maps provide some explainability |
| **New dependencies** | Rendering + ML stack adds complexity |

### Cost Analysis

| Component | Current | Alternative 1 |
|-----------|---------|---------------|
| Compute | $0 (CPU) | $0.02-0.05/filing (GPU inference) |
| LLM | $0.10/filing | $0.02/filing (smaller prompts) |
| Storage | ~200KB/filing | ~5MB/filing (images) |
| **Total per filing** | **$0.10** | **$0.04-0.07** |
| **7,304 filings** | **$730** | **$300-500** |

### Verdict

**Best for**: Long-term investment in robust extraction that handles visual complexity.

**When to choose**: If you anticipate processing diverse document formats (PDFs, scans) or if table extraction accuracy is critical and worth infrastructure investment.

---

## Alternative 2: Knowledge Graph + Semantic Retrieval (RAG)

### Concept

Build a **knowledge graph** of customer metrics with their definitions, relationships, and variants. Use **embedding-based retrieval** to find relevant segments, then **graph reasoning** to validate extractions and infer relationships.

```
┌────────────────────────────────────────────────────────────────────────┐
│                    CURRENT APPROACH (KEYWORD-BASED)                     │
│                                                                         │
│   "customer" + "acquired" → candidate → regex extract → validate       │
│                                                                         │
│   Problems:                                                             │
│   • Synonyms missed ("clients", "subscribers", "users")                 │
│   • Context ignored (definition vs disclosure)                          │
│   • Relationships lost (retention = 1 - churn)                          │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│                    ALTERNATIVE 2 (SEMANTIC + GRAPH)                     │
│                                                                         │
│   Segment embedding → similarity to metric embeddings → retrieve        │
│         ↓                                                               │
│   Graph validation: Is this a disclosure or definition context?         │
│         ↓                                                               │
│   Relationship inference: If churn found, compute retention             │
└────────────────────────────────────────────────────────────────────────┘
```

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        KNOWLEDGE GRAPH                                   │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                                                                   │    │
│  │   (cm_new_customers_acquired)                                    │    │
│  │          │                                                        │    │
│  │          ├── hasSynonym ──► "new customers"                      │    │
│  │          ├── hasSynonym ──► "customers acquired"                 │    │
│  │          ├── hasSynonym ──► "new subscribers"                    │    │
│  │          ├── hasDefinition ──► "Customers with first purchase... │    │
│  │          ├── hasUnit ──► count                                    │    │
│  │          ├── relatedTo ──► (cm_customer_churn_rate) [inverse]    │    │
│  │          └── measuredOver ──► period                              │    │
│  │                                                                   │    │
│  │   (cm_customer_retention_rate)                                   │    │
│  │          │                                                        │    │
│  │          ├── computedFrom ──► 1 - (cm_customer_churn_rate)       │    │
│  │          ├── hasSynonym ──► "retention", "logo retention"        │    │
│  │          └── ...                                                  │    │
│  │                                                                   │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     SEMANTIC RETRIEVAL PIPELINE                          │
│                                                                          │
│   Filing Segments                    Metric Embeddings                   │
│        │                                    │                            │
│        ▼                                    ▼                            │
│   ┌─────────────┐                   ┌─────────────────┐                 │
│   │  Embedding  │                   │  Pre-computed   │                 │
│   │   Model     │                   │  Metric Vectors │                 │
│   │ (text-embed-│                   │  + Synonyms     │                 │
│   │  ing-3-large│                   │                 │                 │
│   └─────────────┘                   └─────────────────┘                 │
│        │                                    │                            │
│        └────────────┬───────────────────────┘                            │
│                     ▼                                                    │
│            Cosine Similarity Search                                      │
│            (threshold: 0.75)                                             │
│                     │                                                    │
│                     ▼                                                    │
│        ┌─────────────────────────────┐                                  │
│        │   Context Classification    │                                  │
│        │   • disclosure (extract)    │                                  │
│        │   • definition (store)      │                                  │
│        │   • methodology (store)     │                                  │
│        │   • noise (discard)         │                                  │
│        └─────────────────────────────┘                                  │
│                     │                                                    │
│                     ▼                                                    │
│        ┌─────────────────────────────┐                                  │
│        │   Value Extraction          │                                  │
│        │   (LLM with graph context)  │                                  │
│        └─────────────────────────────┘                                  │
│                     │                                                    │
│                     ▼                                                    │
│        ┌─────────────────────────────┐                                  │
│        │   Relationship Inference    │                                  │
│        │   • If churn = 5%, infer    │                                  │
│        │     retention = 95%         │                                  │
│        │   • Cross-validate related  │                                  │
│        │     metrics                 │                                  │
│        └─────────────────────────────┘                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Technologies

| Component | Options | Notes |
|-----------|---------|-------|
| **Knowledge Graph** | Neo4j, Amazon Neptune, RDFLib | Store metric ontology and relationships |
| **Embedding Model** | text-embedding-3-large, BGE-M3 | High-quality semantic embeddings |
| **Vector Store** | Pinecone, Qdrant, pgvector | Efficient similarity search |
| **Graph Reasoning** | LLM with graph context, or rule-based | Validate and infer relationships |

### Ontology Design

```yaml
# CMASB Metric Ontology (excerpt)
metrics:
  cm_new_customers_acquired:
    synonyms:
      - "new customers"
      - "customers acquired"
      - "new customer additions"
      - "new subscribers"
      - "first-time buyers"
    definition: "Count of customers completing first purchase in period"
    unit: count
    temporal: period
    related:
      - metric: cm_customer_churn_rate
        relationship: inverse_of_growth
      - metric: cm_active_customers_total
        relationship: component_of

  cm_customer_retention_rate:
    synonyms:
      - "retention rate"
      - "logo retention"
      - "customer retention"
      - "renewal rate"
    computed_from: "1 - cm_customer_churn_rate"
    unit: percentage
    range: [0, 100]

context_types:
  disclosure:
    patterns:
      - "increased by X%"
      - "X customers"
      - "grew to X"
    action: extract_value

  definition:
    patterns:
      - "we define X as"
      - "X is defined as"
      - "X means"
    action: store_definition
```

### Implementation Approach

**Phase 1: Ontology Construction (2 weeks)**
1. Formalize CMASB metrics as knowledge graph
2. Add synonym expansion from corpus analysis
3. Define metric relationships (computed_from, related_to, component_of)
4. Create context classification taxonomy

**Phase 2: Retrieval Pipeline (3-4 weeks)**
1. Embed all metric descriptions and synonyms
2. Build segment embedding pipeline
3. Implement semantic similarity search
4. Add context classification (disclosure vs definition)

**Phase 3: Graph Reasoning (2-3 weeks)**
1. Implement relationship inference (churn ↔ retention)
2. Add cross-validation between related metrics
3. Build confidence scoring based on graph consistency
4. Create audit trail with graph path explanations

### Advantages

| Advantage | Impact |
|-----------|--------|
| **Synonym handling** | "subscribers", "users", "clients" all match correctly |
| **Context awareness** | Distinguishes definitions from disclosures semantically |
| **Relationship inference** | Can compute retention from churn and vice versa |
| **Extensibility** | Add new metrics to graph, no code changes |
| **Cross-validation** | Related metrics validate each other |
| **Better recall** | Semantic matching catches keyword misses |

### Disadvantages

| Disadvantage | Mitigation |
|--------------|------------|
| **Ontology maintenance** | Version control, automated synonym discovery |
| **Embedding cost** | Cache embeddings, batch processing |
| **False positives from semantic similarity** | Threshold tuning, context classification |
| **Complexity** | Start with core metrics, expand gradually |

### Cost Analysis

| Component | Current | Alternative 2 |
|-----------|---------|---------------|
| Embedding | $0 | $0.02/filing (text-embedding-3-large) |
| Vector search | $0 | $0.01/filing (managed service) |
| LLM (reduced prompts) | $0.10/filing | $0.05/filing (smaller context) |
| Graph DB | $0 | $50/month (managed Neo4j) |
| **Total per filing** | **$0.10** | **$0.08** |
| **7,304 filings** | **$730** | **$580 + $50/mo** |

### Verdict

**Best for**: Handling metric variations and building a scalable, maintainable extraction system.

**When to choose**: If you need to handle diverse metric naming conventions, want to add new metrics without code changes, or value relationship reasoning between metrics.

---

## Alternative 3: Multi-Agent Verification System

### Concept

Replace single-pass LLM extraction with a **multi-agent system** where specialized agents collaborate and verify each other's work. Inspired by debate/verification approaches that improve LLM reliability.

```
┌────────────────────────────────────────────────────────────────────────┐
│                    CURRENT APPROACH (SINGLE-PASS)                       │
│                                                                         │
│   Segment → LLM Prompt → JSON Response → (optional quote verification)  │
│                                                                         │
│   Problems:                                                             │
│   • No verification of extraction logic                                 │
│   • False positives pass through                                        │
│   • Ambiguities resolved arbitrarily                                    │
│   • Quality depends entirely on prompt engineering                      │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│                    ALTERNATIVE 3 (MULTI-AGENT)                          │
│                                                                         │
│   Extractor Agent → Verifier Agent → Critic Agent → Resolver Agent      │
│         ↓                  ↓               ↓               ↓            │
│   "Found 5 metrics"   "3 verified"   "2 are dates"   "Final: 3 valid"  │
│                                                                         │
│   Self-correcting through debate and verification                       │
└────────────────────────────────────────────────────────────────────────┘
```

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        MULTI-AGENT SYSTEM                                │
│                                                                          │
│   Filing Segment                                                         │
│        │                                                                 │
│        ▼                                                                 │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    EXTRACTOR AGENT                               │   │
│   │                                                                   │   │
│   │   Role: Find ALL potential metric mentions                       │   │
│   │   Bias: High recall (find everything, let others filter)         │   │
│   │                                                                   │   │
│   │   Output:                                                         │   │
│   │   [                                                               │   │
│   │     {metric: "new_customers", value: "24,000", quote: "..."},    │   │
│   │     {metric: "DAU", value: "24", quote: "24-hour period"},       │   │
│   │     {metric: "revenue", value: "2019", quote: "as of 2019"},     │   │
│   │   ]                                                               │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│        │                                                                 │
│        ▼                                                                 │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    VERIFIER AGENT                                │   │
│   │                                                                   │   │
│   │   Role: Validate each extraction against source                  │   │
│   │   Checks:                                                         │   │
│   │   • Does quote exist in source?                                  │   │
│   │   • Does value appear in quote?                                  │   │
│   │   • Is metric name appropriate for context?                      │   │
│   │                                                                   │   │
│   │   Output:                                                         │   │
│   │   [                                                               │   │
│   │     {metric: "new_customers", value: "24,000", verified: true},  │   │
│   │     {metric: "DAU", value: "24", verified: false,                │   │
│   │      reason: "24 is part of time unit, not a count"},            │   │
│   │     {metric: "revenue", value: "2019", verified: false,          │   │
│   │      reason: "2019 is a year, not a revenue value"},             │   │
│   │   ]                                                               │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│        │                                                                 │
│        ▼                                                                 │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    CRITIC AGENT                                  │   │
│   │                                                                   │   │
│   │   Role: Challenge verified extractions, find edge cases          │   │
│   │   Checks:                                                         │   │
│   │   • Is this a definition or an actual value?                     │   │
│   │   • Could this value belong to a different metric?               │   │
│   │   • Is the time period correctly identified?                     │   │
│   │   • Are there table structure issues?                            │   │
│   │                                                                   │   │
│   │   Output:                                                         │   │
│   │   [                                                               │   │
│   │     {metric: "new_customers", value: "24,000",                   │   │
│   │      challenges: [],                                              │   │
│   │      confidence: 0.95},                                           │   │
│   │   ]                                                               │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│        │                                                                 │
│        ▼                                                                 │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    RESOLVER AGENT                                │   │
│   │                                                                   │   │
│   │   Role: Make final decisions, handle ambiguities                 │   │
│   │   Actions:                                                        │   │
│   │   • Accept high-confidence extractions                           │   │
│   │   • Flag low-confidence for human review                         │   │
│   │   • Resolve conflicts between agents                             │   │
│   │                                                                   │   │
│   │   Output:                                                         │   │
│   │   {                                                               │   │
│   │     accepted: [{metric: "new_customers", value: "24,000", ...}], │   │
│   │     rejected: [{metric: "DAU", reason: "time unit"}, ...],       │   │
│   │     flagged: []                                                   │   │
│   │   }                                                               │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│        │                                                                 │
│        ▼                                                                 │
│   Final Validated Extractions ──► PostgreSQL                            │
└─────────────────────────────────────────────────────────────────────────┘
```

### Agent Specifications

```python
# Agent prompt templates (simplified)

EXTRACTOR_PROMPT = """
You are an EXTRACTOR agent. Your job is to find ALL potential customer metric
mentions in this text. Be aggressive - it's better to include false positives
than miss real metrics. Other agents will filter your output.

For each potential metric, provide:
- metric_name: The type of metric
- value: The numeric value
- quote: The exact text containing the value
- context: Surrounding text for verification

Text to analyze:
{segment_text}
"""

VERIFIER_PROMPT = """
You are a VERIFIER agent. Your job is to validate extractions from the
Extractor agent. For each extraction, verify:

1. The quote exists verbatim in the source text
2. The value actually appears in the quote
3. The metric classification makes sense for the context

Mark as INVALID if:
- The value is a year (1990-2100)
- The value is part of a time unit ("24-hour", "30-day")
- The value is a page number or reference
- The value is in a definition, not a disclosure

Extractions to verify:
{extractions}

Source text:
{segment_text}
"""

CRITIC_PROMPT = """
You are a CRITIC agent. Your job is to challenge verified extractions and
find potential issues that the Verifier missed.

For each verified extraction, consider:
- Could this be a table row attribution error?
- Is this value from an adjacent cell?
- Could this metric name be wrong?
- Is the time period correctly identified?
- Are there any red flags?

Assign a confidence score (0-1) based on how certain you are the
extraction is correct.

Verified extractions:
{verified}

Source text:
{segment_text}
"""

RESOLVER_PROMPT = """
You are a RESOLVER agent. Make final decisions based on all agent outputs.

Rules:
- ACCEPT extractions with confidence >= 0.8 and no unresolved challenges
- REJECT extractions marked invalid by Verifier
- FLAG extractions with 0.5 <= confidence < 0.8 for human review
- When agents disagree, explain your reasoning

Agent outputs:
Extractor: {extractor_output}
Verifier: {verifier_output}
Critic: {critic_output}

Make final decisions.
"""
```

### Implementation Approach

**Phase 1: Single-Segment Pipeline (2 weeks)**
1. Implement 4 agent prompts
2. Build sequential orchestration
3. Test on 100 diverse segments
4. Measure precision/recall vs current approach

**Phase 2: Optimization (2-3 weeks)**
1. Parallelize independent agent calls
2. Add caching for similar segments
3. Implement early-exit for high-confidence extractions
4. Tune agent prompts based on error analysis

**Phase 3: Confidence Calibration (1-2 weeks)**
1. Collect human labels on flagged extractions
2. Calibrate confidence thresholds
3. Build feedback loop for agent improvement
4. Implement batch processing for efficiency

### Advantages

| Advantage | Impact |
|-----------|--------|
| **Self-correcting** | Multiple agents catch each other's errors |
| **Explicit reasoning** | Each agent explains its decisions |
| **Confidence calibration** | Resolver provides meaningful confidence scores |
| **Handles ambiguity** | Critic challenges edge cases explicitly |
| **Reduces false positives** | Verifier specifically checks for known issues |
| **Graceful degradation** | Low-confidence extractions flagged, not wrong |

### Disadvantages

| Disadvantage | Mitigation |
|--------------|------------|
| **4x LLM cost** | Use smaller models (GPT-4o-mini), cache common patterns |
| **Higher latency** | Parallelize where possible, batch processing |
| **Complexity** | Clear agent boundaries, comprehensive logging |
| **Prompt maintenance** | Version control, A/B testing framework |

### Cost Analysis

| Component | Current | Alternative 3 |
|-----------|---------|---------------|
| LLM calls | 1/segment | 4/segment |
| Cost per call | $0.10/filing | $0.025/agent/filing |
| Caching benefit | N/A | ~30% reduction |
| **Total per filing** | **$0.10** | **$0.07** (with caching) |
| **Without caching** | **$0.10** | **$0.10** |
| **7,304 filings** | **$730** | **$510-$730** |

### Optimization: Tiered Processing

```
Segment Classification (fast, rule-based)
    │
    ├── HIGH CONFIDENCE (obvious metrics)
    │       │
    │       └── Single-pass extraction (current approach)
    │           Cost: $0.05/filing (50% of segments)
    │
    ├── MEDIUM CONFIDENCE (potential metrics)
    │       │
    │       └── Extractor + Verifier only
    │           Cost: $0.03/filing (35% of segments)
    │
    └── LOW CONFIDENCE (ambiguous)
            │
            └── Full 4-agent pipeline
                Cost: $0.10/filing (15% of segments)

Weighted average: ~$0.055/filing
```

### Verdict

**Best for**: Maximizing extraction quality when accuracy is paramount and you have LLM budget.

**When to choose**: If current false positive rates are unacceptable, if you need confidence scores for downstream decisions, or if you want explicit reasoning for auditing.

---

## Comparative Analysis

### Feature Comparison

| Feature | Current | Alt 1: Vision-Language | Alt 2: Knowledge Graph | Alt 3: Multi-Agent |
|---------|---------|------------------------|------------------------|-------------------|
| **Table handling** | Brittle | Excellent | Good | Good |
| **Synonym support** | Keywords only | Model-learned | Explicit ontology | Prompt-based |
| **Definition detection** | Pattern-based | Learned | Semantic | Agent-verified |
| **Extensibility** | Code changes | Retraining | Graph updates | Prompt updates |
| **Explainability** | Quote links | Attention maps | Graph paths | Agent reasoning |
| **Cost per filing** | $0.10 | $0.05 | $0.08 | $0.06-0.10 |
| **GPU required** | No | Yes | No | No |
| **Training data needed** | No | Yes (~500 examples) | No | No |
| **Setup complexity** | Low | High | Medium | Low |

### Quality Expectations

| Quality Metric | Current | Alt 1 | Alt 2 | Alt 3 |
|----------------|---------|-------|-------|-------|
| Table extraction precision | 85% | 98% | 90% | 92% |
| Text extraction precision | 80% | 85% | 88% | 95% |
| False positive rate | 15% | 3% | 8% | 3% |
| Recall | 85% | 92% | 95% | 88% |
| Definition detection | 90% | 95% | 98% | 95% |

### Risk Assessment

| Risk | Current | Alt 1 | Alt 2 | Alt 3 |
|------|---------|-------|-------|-------|
| **Implementation complexity** | Low | High | Medium | Low |
| **Operational complexity** | Low | High (GPU) | Medium | Low |
| **Maintenance burden** | High (edge cases) | Low | Medium (ontology) | Medium (prompts) |
| **Cost predictability** | High | Medium | High | Medium |
| **Vendor lock-in** | Medium (OpenAI) | Low | Low | High (OpenAI) |

---

## Recommendations

### Short-Term (Next 3 Months)

**Recommended: Alternative 3 (Multi-Agent)** with tiered processing

Rationale:
- Lowest implementation risk (builds on existing LLM infrastructure)
- Directly addresses known quality issues (false positives, ambiguities)
- Provides confidence scores for human review prioritization
- Can be implemented incrementally (start with Verifier agent only)

Implementation sequence:
1. Add Verifier agent to existing pipeline (Week 1-2)
2. Measure precision improvement (Week 3)
3. Add Critic agent for ambiguous cases (Week 4-5)
4. Add Resolver for final decisions (Week 6)
5. Implement tiered processing for cost optimization (Week 7-8)

### Medium-Term (3-6 Months)

**Recommended: Alternative 2 (Knowledge Graph)** for metric management

Rationale:
- Provides scalable solution for adding new metrics
- Enables relationship inference (churn ↔ retention)
- Supports semantic synonym handling
- Compatible with Multi-Agent approach (agents use graph context)

Implementation sequence:
1. Build initial CMASB metric ontology (Week 1-2)
2. Implement embedding-based retrieval (Week 3-4)
3. Integrate with Multi-Agent pipeline (Week 5-6)
4. Add relationship inference (Week 7-8)

### Long-Term (6-12 Months)

**Consider: Alternative 1 (Vision-Language)** for future-proofing

Rationale:
- Best long-term solution for document diversity
- Handles PDF/scan sources as they emerge
- Reduces maintenance of parsing edge cases
- Enables extraction from charts/images

Prerequisites:
- GPU infrastructure or managed service budget
- Training data from current extractions
- Clear ROI from reduced manual parsing maintenance

---

## Hybrid Architecture (Recommended End State)

The three alternatives are **complementary, not mutually exclusive**. The ideal architecture combines elements from each:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     HYBRID ARCHITECTURE                                  │
│                                                                          │
│   ┌───────────────────────────────────────────────────────────────┐     │
│   │                 KNOWLEDGE GRAPH (Alt 2)                        │     │
│   │   Metric ontology, relationships, synonyms                     │     │
│   │   Used by all downstream components                            │     │
│   └───────────────────────────────────────────────────────────────┘     │
│                              │                                           │
│                              ▼                                           │
│   ┌───────────────────────────────────────────────────────────────┐     │
│   │                 DOCUMENT PROCESSING                            │     │
│   │                                                                 │     │
│   │   ┌─────────────────┐     ┌─────────────────────────────┐     │     │
│   │   │  HTML Parsing    │     │  Vision-Language (Alt 1)    │     │     │
│   │   │  (current)       │     │  (for tables, complex docs) │     │     │
│   │   │  Fast, cheap     │     │  Robust, accurate           │     │     │
│   │   └─────────────────┘     └─────────────────────────────┘     │     │
│   │              │                         │                        │     │
│   │              └────────────┬────────────┘                        │     │
│   │                           ▼                                     │     │
│   │                  Semantic Retrieval                             │     │
│   │                  (Alt 2 embeddings)                             │     │
│   └───────────────────────────────────────────────────────────────┘     │
│                              │                                           │
│                              ▼                                           │
│   ┌───────────────────────────────────────────────────────────────┐     │
│   │                 MULTI-AGENT EXTRACTION (Alt 3)                 │     │
│   │                                                                 │     │
│   │   Extractor → Verifier → Critic → Resolver                    │     │
│   │   (with graph context from Alt 2)                              │     │
│   └───────────────────────────────────────────────────────────────┘     │
│                              │                                           │
│                              ▼                                           │
│                     High-Quality Extractions                             │
│                     with Confidence Scores                               │
└─────────────────────────────────────────────────────────────────────────┘
```

This hybrid approach:
- Uses **Knowledge Graph** for metric definitions and relationships
- Uses **Vision-Language** for complex tables (15% of segments)
- Uses **Multi-Agent** for verification and confidence scoring
- Falls back to **current approach** for simple, high-confidence cases

**Estimated cost**: $0.06/filing (vs $0.10 current)
**Estimated precision**: 96% (vs 85% current)
**Estimated recall**: 93% (vs 85% current)

---

## Conclusion

Each alternative addresses specific weaknesses in the current architecture:

| Alternative | Best For | Investment | Payoff |
|------------|----------|------------|--------|
| **Vision-Language** | Table structure, visual docs | High | High (long-term) |
| **Knowledge Graph** | Extensibility, synonyms | Medium | Medium |
| **Multi-Agent** | Accuracy, confidence | Low | High (immediate) |

**Recommended path**: Start with Multi-Agent (immediate quality wins), add Knowledge Graph (scalability), consider Vision-Language (future-proofing).

---

**Document Version**: 1.0
**Created**: 2025-12-23
**Author**: Architecture Analysis
