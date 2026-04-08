# L1 C4 System Context Diagram - Filings Reviewer

## PlantUML C4 Syntax (copy into PlantUML Editor)

```plantuml
@startuml L1_C4_Context_Diagram
!define TITLE Filings Reviewer - System Context Diagram (L1)
!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4/C4_Context.puml

LAYOUT_WITH_LEGEND()

title TITLE

Person(analyst, "Financial Analyst", "Reviews metric disclosures\nand validates extractions")
Person(auditor, "Auditor/Reviewer", "Evaluates metric extraction\naccuracy and quality")

System(filings, "Filings Reviewer System", "Analyzes SEC S-1/F-1 filings\nto extract and validate\ncustomer metric disclosures\n(CMASB initiative)")

System_Ext(sec_edgar, "SEC Edgar API", "Public SEC filing database\n(e.g., 10-K, S-1, F-1)")
System_Ext(openai, "OpenAI API", "GPT-based text and\nimage analysis")
System_Ext(huggingface, "HuggingFace Hub", "Pre-trained ML models\nfor classification and extraction")

Rel(analyst, filings, "Reviews extractions\nand validations")
Rel(auditor, filings, "Analyzes patterns\nand quality metrics")
Rel(filings, sec_edgar, "Fetches S-1/F-1\nfilings")
Rel(filings, openai, "Analyzes text\nand images")
Rel(filings, huggingface, "Uses pre-trained\nmodels")

@enduml
```

## C4 Model Levels in This System

### L1: System Context (Current)
Shows the Filings Reviewer system as a black box with external systems and users.
- **Users**: Financial Analysts, Auditors
- **External Systems**: SEC Edgar, OpenAI, HuggingFace

### L2: Container Diagram (One Level Down)
Would show major containers within Filings Reviewer:
- Web Application (Flask)
- Extraction Engine (V2)
- Database (PostgreSQL)
- Batch Processing (Universe Builder, Filing Fetcher)

### L3: Component Diagram (One Level Down from Containers)
Would show components within containers:
- Within Web: API routes, Review routes, Templates
- Within Extraction: V2 stages, Candidate generation
- Within Database: Connection pooling, Query layer

### L4: Code/Class Diagram
Shows implementation details within components.

---

## Key Characteristics of the System

### Purpose
- Extracts customer metrics from SEC S-1/F-1 filings
- Supports CMASB (Customer Metrics Accounting Standards Board) initiative
- Provides human review interface for validation

### Key Features
1. **V2 Extraction Pipeline**
   - Unified production pipeline for SEC filings, transcripts, and presentations
   - V1 is retired (kept for historical reference in `src/extraction/`)

2. **Multi-Stage Processing**
   - Rule-based keyword matching (primary)
   - LLM-enhanced extraction (secondary)
   - OCR and image processing for tables/figures
   - Deduplication and validation

3. **Quality Assurance**
   - Gold standard validation framework
   - Pattern analysis for metric disclosure evaluation
   - Human review workflow

4. **Data Sources**
   - SEC Edgar (primary filings)
   - Transcripts and presentations (V2)
   - Images and tables (OCR processing)

### External Dependencies
- **SEC Edgar API**: Authoritative source for filings
- **OpenAI API**: Vision and text analysis capabilities
- **HuggingFace**: Pre-trained models for classification

### Data Flow (High-Level)
```
SEC Edgar
   ↓
[FilingFetcher] → [UniverseBuilder]
   ↓
[V2 Pipeline] → [Processing Stages]
   ↓
[Database] ← [LLM Integration]
   ↓
[Candidate Generator] → [Review Interface]
   ↓
[Web UI] ← [Analyst/Auditor]
```

### Technology Stack
- **Language**: Python
- **Web**: Flask
- **Database**: PostgreSQL
- **LLM**: OpenAI (GPT)
- **Vision**: Claude Vision API
- **ML**: HuggingFace transformers
- **Testing**: pytest
- **Package Management**: uv (UV)
