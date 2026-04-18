# Architecture Visualization Summary

## Quick Visual Reference

### UML Component Structure (Text-Based)

```
┌─────────────────────────────────────────────────────────────────┐
│                 CMASB Disclosures Review System (UML)                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ ┌──────────────────┐  ┌──────────────────┐                     │
│ │  Infrastructure  │  │  Data Discovery  │                     │
│ │   - DB Adapter   │  │  - Universe      │                     │
│ │   - SEC Client   │  │  - Filing Fetch  │                     │
│ │   - HTTP Client  │  │  - Company Map   │                     │
│ │   - Connection   │  └──────────────────┘                     │
│ │     Pool         │                                           │
│ │   - Logging      │                                           │
│ └──────────────────┘                                           │
│         ↓ manages                                              │
│         ↓ connections                                          │
│   ┌─────────────────────────────────────────┐                │
│   │  Extraction Pipeline (V2)               │                │
│   │  ┌────────────────────────────────────┐ │                │
│   │  │ V2 Stages (15 sequential):         │ │                │
│   │  │ - Candidate Generation             │ │                │
│   │  │ - Section Classification           │ │                │
│   │  │ - Value Binding                    │ │                │
│   │  │ - Fact Construction                │ │                │
│   │  │ - OCR/Image Processing             │ │                │
│   │  │ - Deduplication & Validation       │ │                │
│   │  └────────────────────────────────────┘ │                │
│   └─────────────────────────────────────────┘                │
│         ↓ uses                                                │
│    ┌────────────────────┐                                     │
│    │  LLM Integration   │                                     │
│    │  - Vision Client   │                                     │
│    │  - OpenAI Client   │                                     │
│    │  - LLM Cache       │                                     │
│    │  - Prompts         │                                     │
│    └────────────────────┘                                     │
│         ↓ calls                                               │
│    [OpenAI API]                                               │
│                                                                 │
│ ┌──────────────────┐  ┌──────────────────┐                     │
│ │  Review & Analyze│  │  Validation      │                     │
│ │  - Candidate Gen │  │  - Gold Standard │                     │
│ │  - Pattern Anly  │  │  - V2 Validator  │                     │
│ │  - Review Mgr    │  │  - Fresh Extract │                     │
│ └──────────────────┘  └──────────────────┘                     │
│         ↑                                                       │
│    stores/reads                                                │
│         ↓                                                       │
│    ┌─────────────────┐                                         │
│    │  Web Interface  │                                         │
│    │  - Flask App    │                                         │
│    │  - API Routes   │                                         │
│    │  - Review Routes│                                         │
│    │  - Templates    │                                         │
│    └─────────────────┘                                         │
│         ↑                                                       │
│    ┌─────────────────┐                                         │
│    │  Configuration  │                                         │
│    │  - Metrics YAML │                                         │
│    └─────────────────┘                                         │
└─────────────────────────────────────────────────────────────────┘
         ↓
   ┌──────────────────┐
   │   PostgreSQL DB  │
   │   - companies    │
   │   - filings      │
   │   - metric_vals  │
   │   - decisions    │
   └──────────────────┘
```

### C4 System Context (Text-Based)

```
┌────────────────────────────────────────────────────────────────────┐
│                 CMASB Disclosures Review System (C4 L1)                     │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌──────────────┐                                                  │
│  │  Analyst     │                                                  │
│  │  Auditor     │                                                  │
│  └──────────────┘                                                  │
│         ↑                                                          │
│         │ reviews disclosures                                     │
│         │                                                          │
│         ↓                                                          │
│  ┌────────────────────────────────────────┐                       │
│  │   CMASB Disclosures Review System               │                       │
│  │   ─────────────────────────────────────│                       │
│  │   Analyzes SEC S-1/F-1 filings for     │                       │
│  │   customer metric disclosure           │                       │
│  │   (CMASB initiative)                   │                       │
│  └────────────────────────────────────────┘                       │
│   ↕ (bidirectional)                                               │
│   │                                                                │
│   ├─→ [SEC Edgar API]                                             │
│   │    (Fetches filings)                                          │
│   │                                                                │
│   ├─→ [OpenAI API]                                                │
│   │    (Text & image analysis)                                    │
│   │                                                                │
│   └─→ [HuggingFace Hub]                                           │
│        (Pre-trained models)                                       │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

---

## Component Layer Breakdown

### Layer 1: Infrastructure (Foundation)
- Manages PostgreSQL connections
- Handles HTTP requests to external APIs
- Provides centralized logging
- Coordinates database pooling

### Layer 2: Data Pipeline (Input)
- Discovers relevant filings via SEC Edgar
- Fetches and caches document contents
- Maps companies to SEC identifiers

### Layer 3: Extraction & Processing (Core Logic)
- **V2 Pipeline**: Sole production extraction pipeline (V1 retired 2026-04-08); 15-stage unified pipeline for all filing types
- Integrates LLM (OpenAI) for enhanced analysis
- Processes images via Vision API

### Layer 4: Candidate Generation & Review (Analysis)
- Generates candidates from extraction results
- Analyzes metric disclosure patterns
- Orchestrates human review workflows

### Layer 5: Presentation (Output)
- Flask web application
- RESTful API endpoints
- Human review interface
- HTML templates

### Layer 6: Validation (Quality Assurance)
- Gold standard validation framework
- V2 extraction validator
- Fresh extraction for comparison

### Layer 7: Configuration (Cross-Cutting)
- `metric_keywords.yaml` - authoritative metric patterns
- Applied to V2 extraction pipeline

---

## Data Flow Diagram

### End-to-End Flow

```
1. SEC Edgar API
   ↓
2. FilingFetcher (retrieves documents)
   ↓
3. UniverseBuilder (identifies relevant filings)
   ↓
4. Extraction V2 Pipeline
   ├─ Rule-based: metric_keywords.yaml patterns
   ├─ LLM-based: OpenAI for enhanced analysis
   ├─ Vision: Claude Vision for image/table extraction
   └─ Processing: OCR, deduplication, validation
   ↓
5. Database Storage
   ├─ metric_values (extracted values)
   ├─ source_segments (provenance)
   └─ metric_definitions (metadata)
   ↓
6. Candidate Generation
   ├─ Candidate Generator (from extraction)
   └─ Pattern Analyzer (disclosure patterns)
   ↓
7. Review Interface (Flask Web App)
   ├─ Analyst reviews candidates
   ├─ Auditor validates quality
   └─ Decisions stored to database
   ↓
8. Validation Framework
   ├─ Gold Standard checks
   ├─ V2 Validator compares results
   └─ Fresh Extractor for regression testing
```

---

## Technology Stack by Component

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Web Server** | Flask (Python) | HTTP routing, templates |
| **Database** | PostgreSQL | Persistent storage, relationships |
| **LLM Integration** | OpenAI API + Claude Vision | Text/image analysis |
| **ML Models** | HuggingFace Transformers | Classification, NER |
| **Language** | Python 3.10+ | Primary implementation |
| **Testing** | pytest | Unit, integration tests |
| **Code Quality** | ruff, black, mypy | Linting, formatting, type checking |
| **Package Mgmt** | uv (UV) | Fast dependency management |
| **Configuration** | YAML (metric_keywords.yaml) | Extensible metric patterns |

---

## Key Architectural Decisions

### 1. **V2 as Sole Extraction Pipeline**
- **V2**: Unified production pipeline for all document types (SEC filings, transcripts, presentations)
- V1 extraction was retired 2026-04-08; V2 is the sole production pipeline

### 2. **Rule-Based First**
- Keyword matching (fast, reliable) is primary
- LLM processing (expensive, flexible) is secondary enhancement
- Reduces API costs and improves consistency

### 3. **PostgreSQL-Backed Caching**
- LLM responses cached in database
- Enables cost tracking and audit trail
- Allows comparison and validation

### 4. **Separation of Concerns**
- Infrastructure layer isolated (db, http, logging)
- Business logic independent of presentation
- Review workflow decoupled from extraction
- Configuration externalized (metric_keywords.yaml)

### 5. **Provenance Tracking**
- Every extracted value links to source segment
- Enables validation and human review
- Supports audit requirements

---

## Dependency Matrix

### External Dependencies
- ✅ **SEC Edgar**: Required (primary data source)
- ✅ **OpenAI API**: Required (LLM analysis, vision)
- ⚠️ **HuggingFace**: Optional (fallback models available)
- ✅ **PostgreSQL**: Required (data persistence)

### Internal Dependencies
- **Extraction depends on**: Keyword config, Database, LLM
- **Review depends on**: Extraction results, Database
- **Web Interface depends on**: Extraction, Review, Database
- **Validation depends on**: Extraction V2

---

## Document Files Created

1. **L1_UML_COMPONENT_DIAGRAM.md** - Detailed internal architecture
2. **L1_C4_SYSTEM_CONTEXT_DIAGRAM.md** - External boundaries and actors
3. **L1_DIAGRAM_COMPARISON.md** - Side-by-side comparison and usage guide
4. **ARCHITECTURE_VISUALIZATION.md** - This file (text-based visuals)

All files include PlantUML code that can be rendered online or locally.

---

## Next Steps

To render the diagrams:

1. **View Online**: Visit https://www.plantuml.com/plantuml/uml/
2. **Copy Code**: Paste the PlantUML code blocks from the markdown files
3. **Download**: Export as PNG/SVG/PDF

To extend the architecture documentation:

- Create **C4 L2 (Container Diagram)** showing Flask, Extraction, Database containers
- Create **C4 L3 (Component Diagram)** showing Web routes, Pipeline stages, Database queries
- Add **Deployment Diagram** showing how system is deployed (servers, containers)
- Add **Sequence Diagrams** for key workflows (e.g., filing extraction process)
