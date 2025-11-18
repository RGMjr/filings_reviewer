# Alternative Architecture Proposal – Retrieval & Evaluator Driven

## Objectives
- Preserve the program goals of low-cost, high-volume extraction of customer metrics from SEC filings while improving determinism, observability, and maintainability.
- Replace brittle heuristic stages with modular services that each solve one problem (normalization, retrieval, extraction, evaluation, publishing).
- Support multi-operator deployments with auditable workflows, backpressure-aware queueing, and scalable storage beyond SQLite.

## Guiding Tenets
1. **Document Normalization First** – Convert every filing into layout-aware artifacts (HTML, PDF, tables, figures) using libraries like PDFPlumber or layout-aware OCR so downstream actors consume a consistent schema rather than raw EDGAR HTML.
2. **Semantic Retrieval over Keywords** – Index normalized paragraphs, tables, and captions with embeddings tuned for financial language (e.g., OpenAI text-embedding-3-large or InstructorXL) and retrieve context by semantic similarity plus metadata filters instead of hard-coded keyword checks.
3. **Specialized Extractors** – Use lightweight, fine-tuned models for common metric families (engagement, subscriber counts, revenue ratios). Only escalate outlier spans to general LLMs, reducing token spend and hallucination risk.
4. **Evaluator-First Loop** – Treat the evaluator as the orchestrator. Rule-based checks, learned anomaly detectors, and cross-source comparisons determine whether an extraction is accepted, re-queued for a stronger model, or flagged for human review.
5. **Event-Driven Orchestration** – Push filings into a queue (SQS, Redis, RabbitMQ). Stateless workers pop tasks for normalization, retrieval/extraction, evaluation, and publishing, ensuring natural rate limiting and easy horizontal scale.
6. **Data Lake Output** – Store authoritative outputs as partitioned Parquet (e.g., `s3://filings-metrics/year=2024/filing_id=.../metrics.parquet`) plus structured metadata tables. Analysts can query via DuckDB/Snowflake without ETL from SQLite.

## System Overview
```
Ingestion → Normalization Service → Vector Index Builder → Task Queue
                                   ↘
                        Table Extractor Service
                                   ↘
                        Text Retrieval + Extractor Service
                                   ↘
                           Evaluator / Policy Engine
                                   ↘
                       Data Lake Writer + Warehouse Sync
                                   ↘
                         Monitoring + Analyst Review UI
```

### Normalization Service
- Downloads filings via the SEC bulk feed, converts PDFs/HTML to unified JSON (`blocks`, `tables`, `figures`).
- Emits chunk metadata (CIK, accession, filing_type, chunk_id, chunk_kind) for downstream retrieval.
- Stores raw artifacts in object storage for reproducibility.

### Retrieval + Extraction Services
- **Vector Index Builder:** Generates embeddings for each chunk and persists them in FAISS (offline) or a managed vector DB (online).
- **Table Service:** Applies layout-aware table extraction (Camelot, GCV, Tabby) and outputs normalized columnar JSON irrespective of HTML quirks.
- **Text Service:** For each metric template, retrieves top-N relevant paragraphs using semantic filters (e.g., “metric_family:retention”). A distilled T5/BERT extractor translates spans into structured metrics. General LLMs (GPT-4o mini/4o) are invoked only when confidence falls below a policy threshold.

### Evaluator / Policy Engine
- Cross-validates outputs: table vs. text, YoY sanity checks, value-type validation, and historical comparisons per company.
- Uses learnable confidence models plus deterministic guards (e.g., DAU ≤ MAU, churn between 0 and 1).
- Determines escalation path: accept, re-process with higher-tier model, or route to a reviewer queue.

### Data Platform
- Accepted metrics/QA events flow into a bronze/silver/gold lakehouse. Bronze captures raw extracts, silver enforces schemas, gold surfaces analyst-ready tables.
- Metadata catalogs (Glue/Hive) expose datasets to BI tools. Airflow/Prefect orchestrates periodic compaction, cost statistics, and SLA tracking.

### Operations & Compliance
- Queue depth, throughput, cost per filing, and evaluator decision rates feed dashboards (Grafana). Rate limiting is centralized in the queue rather than per-thread sleeps.
- Every task carries operator identity and config hashes for auditability. API credentials live in a secrets manager, not source files.

## Migration Path
1. Stand up normalization and storage scaffolding alongside the current pipeline; begin writing dual outputs.
2. Add semantic retrieval + evaluator services for a limited metric family (e.g., MAU/DAU) and measure precision/recall vs. baseline.
3. Expand specialized extractors and decommission keyword filters + ad hoc table heuristics once coverage surpasses legacy performance.
4. Retire SQLite by streaming both pipelines into the new data lake; keep the old storage read-only for lineage.
