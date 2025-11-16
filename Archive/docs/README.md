# SEC Filings Analysis System - Complete Documentation

**Version 2.0 - Stateless Agent Architecture**

---

## Overview

This system extracts structured customer and growth metrics from SEC filings (S-1, 10-K) at scale using a hybrid approach:

- **Rule-based table extraction** (50-70% of metrics, $0 cost)
- **LLM text extraction** with GPT-4o-mini (30-50% of metrics, low cost)
- **Selective re-extraction** with GPT-4o for low-confidence cases
- **QA validation** with automated quality checks

**Target Scale:** 20,500+ filings (10 years S-1, 3 years 10-K)
**Target Cost:** $500-$1,000 (95% cheaper than naive LLM approach)
**Target Quality:** >95% success rate, >90% precision, >80% recall

---

## Quick Start

### For Developers
1. Read **01_ARCHITECTURE_OVERVIEW.md** - Understand the system design
2. Read **06_IMPLEMENTATION_GUIDE.md** - Build the system step-by-step
3. Follow **Phase 1** in the implementation guide
4. Run tests as you build each component

### For Project Managers
1. Read **01_ARCHITECTURE_OVERVIEW.md** - High-level design and goals
2. Review **Success Criteria** section
3. Read **08_DEPLOYMENT_GUIDE.md** - Deployment phases and timeline
4. Monitor progress using provided scripts

### For QA/Analysts
1. Read **07_TESTING_STRATEGY.md** - Quality validation approach
2. Review **Manual QA Protocol** section
3. Use provided validation scripts
4. Report findings using QA templates

---

## Document Index

### Core Architecture
| Document | Description | Audience |
|----------|-------------|----------|
| **[01_ARCHITECTURE_OVERVIEW.md](01_ARCHITECTURE_OVERVIEW.md)** | System design, components, data flow | Everyone - Start Here |
| **[02_SYSTEM_COMPONENTS.md](02_SYSTEM_COMPONENTS.md)** | Detailed component specifications | Developers |
| **[03_DATA_MODELS.md](03_DATA_MODELS.md)** | Database schemas, CSV formats, API contracts | Developers |

### Implementation Details
| Document | Description | Audience |
|----------|-------------|----------|
| **[04_TABLE_EXTRACTION.md](04_TABLE_EXTRACTION.md)** | Rule-based table parsing logic | Developers |
| **[05_LLM_EXTRACTION.md](05_LLM_EXTRACTION.md)** | Prompt engineering, LLM integration | Developers |
| **[06_IMPLEMENTATION_GUIDE.md](06_IMPLEMENTATION_GUIDE.md)** | Step-by-step build instructions | Developers |

### Testing & Deployment
| Document | Description | Audience |
|----------|-------------|----------|
| **[07_TESTING_STRATEGY.md](07_TESTING_STRATEGY.md)** | Quality validation approach | QA, Developers |
| **[08_DEPLOYMENT_GUIDE.md](08_DEPLOYMENT_GUIDE.md)** | Production deployment instructions | DevOps, PM |

---

## Key Features

### 🚀 Performance
- **Parallel processing:** 10 concurrent workers
- **Smart rate limiting:** Respects OpenAI API limits
- **Processing speed:** 5-10 filings/minute
- **Total runtime:** 2-5 days for full dataset

### 💰 Cost Optimization
- **Table-first extraction:** 50-70% of metrics at $0 cost
- **Keyword filtering:** Reduces LLM input by 90%
- **GPT-4o-mini primary:** 94% cheaper than GPT-4o
- **Selective fallback:** GPT-4o only when needed

### ✅ Quality Assurance
- **Inline QA validation:** Real-time quality checks
- **Confidence scoring:** 0.0-1.0 for every metric
- **Consistency checks:** DAU ≤ MAU, etc.
- **Completeness checks:** Flag sparse extractions

### 🔧 Resilience
- **HTML caching:** Avoid re-downloading from SEC
- **Automatic retry:** Exponential backoff on failures
- **Checkpointing:** Resume from interruptions
- **Error tracking:** Dedicated retry mechanism

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     USER COMMANDS                                │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │   CLI Interface       │
                    └───────────┬───────────┘
                                │
            ┌───────────────────┼───────────────────┐
            │                   │                   │
    ┌───────▼────────┐  ┌──────▼──────┐  ┌────────▼────────┐
    │   Discovery    │  │ Orchestrator │  │   Monitoring    │
    │   Service      │  │   (Parallel) │  │   Dashboard     │
    └───────┬────────┘  └──────┬───────┘  └─────────────────┘
            │                  │
            │          ┌───────▼────────┐
            └──────────► Stateless Agent│
                       │                 │
                       │ 1. Cache HTML   │
                       │ 2. Extract      │
                       │    Tables       │
                       │ 3. Filter       │
                       │    Keywords     │
                       │ 4. LLM Extract  │
                       │ 5. QA Validate  │
                       └────────┬────────┘
                                │
                       ┌────────▼────────┐
                       │ SQLite Database │
                       │ + CSV Exports   │
                       └─────────────────┘
```

---

## Technology Stack

**Core:**
- Python 3.11+
- SQLite 3
- OpenAI API (GPT-4o-mini, GPT-4o)

**Key Libraries:**
- `beautifulsoup4` - HTML parsing
- `pandas` - Data manipulation
- `openai` - LLM integration
- `requests` - SEC API access
- `tqdm` - Progress tracking

---

## Development Workflow

### Phase 1: Setup (Week 1)
```bash
# Clone/setup project
cd filings_reviewer
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your OpenAI API key
```

### Phase 2: Build (Week 2)
```bash
# Build components in order
# 1. Discovery service
# 2. Cache layer
# 3. Table extractor
# 4. Keyword filter
# 5. LLM extractor
# 6. QA agent
# 7. Storage layer

# Test each component
pytest tests/test_<component>.py -v
```

### Phase 3: Integration (Week 3)
```bash
# Build orchestrator
# Add parallel processing
# Add rate limiting
# Add monitoring

# Integration tests
pytest tests/test_integration.py -v
```

### Phase 4: Deployment (Week 4)
```bash
# Pilot run
python main.py --start-date 2024-01-01 --end-date 2024-12-31 --max-results 100

# Production run
python main.py --start-date 2015-01-01 --end-date 2024-12-31 --filing-type S-1
```

---

## Key Decisions & Rationale

### Why Stateless Agent?
- **Reproducibility:** Same input = same output
- **Testability:** Easy to unit test
- **Debuggability:** No hidden state
- **Parallelization:** Safe concurrent processing

### Why Hybrid Extraction?
- **Cost:** Rule-based is free, LLM is expensive
- **Quality:** Tables are more accurate than text
- **Coverage:** LLM catches what rules miss

### Why SQLite?
- **Simple:** No server setup
- **Fast:** Sufficient for this scale
- **Portable:** Single file database
- **Flexible:** Easy to export to CSV

### Why GPT-4o-mini First?
- **Cost:** 94% cheaper than GPT-4o
- **Quality:** Sufficient for structured extraction
- **Fallback:** Can use GPT-4o when needed

---

## Success Metrics

### Technical
- ✅ Process 20,500+ filings
- ✅ Success rate > 95%
- ✅ Total cost < $1,500
- ✅ Processing time < 5 days

### Quality
- ✅ Extract 300K-500K metrics
- ✅ Precision > 90%
- ✅ Recall > 80%
- ✅ Average confidence > 0.7

---

## Common Issues & Solutions

### "OpenAI rate limit exceeded"
→ System automatically retries with exponential backoff
→ Check rate limiter settings in config

### "SEC blocking requests"
→ Ensure User-Agent header is set correctly
→ HTML caching prevents re-downloads

### "High cost per filing"
→ Check keyword filtering is working
→ Verify table extraction runs first
→ Check if GPT-4o being used too much

### "Low extraction quality"
→ Review QA warnings
→ Adjust metric patterns in config
→ Test on sample filings
→ Iterate on LLM prompts

---

## Best Practices

### During Development
1. **Test with small samples** before full runs
2. **Use mock data** for unit tests to avoid API costs
3. **Commit often** with clear messages
4. **Document changes** to extraction logic

### During Deployment
1. **Start with pilot** (100 filings)
2. **Monitor costs** in real-time
3. **Backup database** before major runs
4. **Log everything** for debugging
5. **Export frequently** to prevent data loss

### After Deployment
1. **Validate results** with manual QA
2. **Review failures** and retry
3. **Generate reports** for stakeholders
4. **Archive codebase** snapshot
5. **Document lessons learned**

---

## Cost Breakdown

### Expected Costs (Full Dataset)

| Phase | Filings | Estimated Cost | Time |
|-------|---------|---------------|------|
| Pilot (2024 S-1) | 100 | $3-6 | 30 min |
| Full 2024 S-1 | 250 | $8-15 | 1-2 hours |
| 10-year S-1 | 2,500 | $75-150 | 6-10 hours |
| 3-year 10-K | 18,000 | $540-1,080 | 24-48 hours |
| **Total** | **~20,500** | **$615-$1,230** | **2-5 days** |

*Note: Actual costs depend on filing complexity and LLM usage*

---

## Data Outputs

### Primary Output
- **customer_metrics.csv** - All extracted metrics with metadata

### Intermediate Outputs
- **keyword_paragraphs.csv** - Filtered paragraphs (debugging)
- **qa_warnings.csv** - Quality issues flagged

### Tracking Outputs
- **execution_log.csv** - Batch processing history
- **failed_filings.csv** - Errors for retry
- **cost_tracking.csv** - Detailed cost breakdown

### Database
- **filings_data.db** - SQLite database (all data)

---

## Next Steps

### For New Team Members
1. Read this README
2. Read 01_ARCHITECTURE_OVERVIEW.md
3. Set up development environment
4. Run example on 1 filing
5. Ask questions!

### For Implementation
1. Follow 06_IMPLEMENTATION_GUIDE.md
2. Build Phase 1 (Setup)
3. Build Phase 2 (Core Components)
4. Build Phase 3 (Orchestration)
5. Deploy Phase 4 (Production)

### For Questions
- Technical questions → Review component docs (02-05)
- Testing questions → Review 07_TESTING_STRATEGY.md
- Deployment questions → Review 08_DEPLOYMENT_GUIDE.md

---

## Version History

### Version 2.0 (Current)
- Stateless agent architecture
- Hybrid extraction (tables + LLM)
- Cost optimized (GPT-4o-mini first)
- Parallel processing with rate limiting
- Comprehensive QA validation

### Version 1.0 (Legacy)
- Monolithic script (data_preprocessing.py)
- Full LLM extraction only
- Sequential processing
- Manual QA

---

## License & Contact

**Contact:** Rob Markey

**Documentation Created:** 2025-11-14

**System Version:** 2.0

---

**Ready to get started? Begin with [01_ARCHITECTURE_OVERVIEW.md](01_ARCHITECTURE_OVERVIEW.md)!**
