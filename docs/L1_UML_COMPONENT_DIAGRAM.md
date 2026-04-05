# L1 UML Component Diagram - Filings Reviewer System

## PlantUML Syntax (copy into PlantUML Editor)

```plantuml
@startuml L1_UML_Component_Diagram
!define COMPONENT_BG #FFE5B4
!define DATABASE_BG #B4D7FF
!define EXTERNAL_BG #D5FFB4
!define SERVICE_BG #FFB4E5

skinparam backgroundColor #FAFAFA
skinparam component {
    backgroundColor COMPONENT_BG
    borderColor #333
}

package "Filings Reviewer System" {
    package "Infrastructure Layer" {
        component [Database Adapter] as db_adapter <<infrastructure>>
        component [SEC Client] as sec_client <<infrastructure>>
        component [HTTP Client] as http_client <<infrastructure>>
        component [Connection Pool] as pool <<infrastructure>>
        component [Logging] as logging_config <<infrastructure>>
    }

    package "Data Discovery & Retrieval" {
        component [Universe Builder] as universe <<business>>
        component [Filing Fetcher] as fetcher <<business>>
        component [Company Mapping] as company_mapping <<business>>
    }

    package "Extraction Pipeline" {
        component [Extraction V1] as extraction_v1 <<business>>
        component [Extraction V2] as extraction_v2 <<business>>
        component [V2 Stages:\n- Candidate Generation\n- Section Classification\n- Value Binding\n- Fact Construction\n- OCR/Image Processing\n- Deduplication\n- Validation] as v2_stages <<business>>
    }

    package "Review & Analysis" {
        component [Candidate Generator] as candidate_gen <<business>>
        component [Pattern Analyzer] as pattern_analyzer <<business>>
        component [Review Manager] as review_mgr <<business>>
    }

    package "LLM Integration" {
        component [Vision Client] as vision_client <<service>>
        component [OpenAI Client] as openai_client <<service>>
        component [LLM Cache] as llm_cache <<service>>
        component [Prompts] as prompts <<service>>
    }

    package "Web Interface" {
        component [Flask App] as flask_app <<presentation>>
        component [API Routes] as api_routes <<presentation>>
        component [Review Routes] as review_routes <<presentation>>
        component [Templates] as templates <<presentation>>
    }

    package "Validation & Testing" {
        component [Gold Standard] as gold_standard <<testing>>
        component [V2 Validator] as v2_validator <<testing>>
        component [Fresh Extractor] as fresh_extractor <<testing>>
    }

    package "Configuration" {
        component [Metric Keywords\n(metric_keywords.yaml)] as config <<configuration>>
    }
}

database "PostgreSQL Database" as postgres <<external>> {
    note on right
    Tables:
    - companies
    - filings
    - source_segments
    - metric_values
    - metric_definitions
    - review_candidates
    - review_decisions
    - ...
    end note
}

cloud "External Services" {
    [SEC Edgar] as sec_edgar <<external>>
    [OpenAI API] as openai_api <<external>>
    [HuggingFace] as huggingface <<external>>
}

' Dependencies
sec_client --> http_client : uses
sec_client --> sec_edgar : fetches from
fetcher --> sec_client : retrieves documents
universe --> company_mapping : builds
pool --> db_adapter : manages connections
db_adapter --> postgres : reads/writes

extraction_v1 --> db_adapter : stores results
extraction_v2 --> v2_stages : orchestrates
v2_stages --> extraction_v2 : sub-components
v2_stages --> openai_client : analyzes with LLM
v2_stages --> vision_client : processes images

candidate_gen --> extraction_v2 : uses results
candidate_gen --> db_adapter : persists
pattern_analyzer --> db_adapter : analyzes patterns
review_mgr --> candidate_gen : manages

flask_app --> api_routes : routes to
flask_app --> review_routes : routes to
api_routes --> extraction_v2 : queries
review_routes --> review_mgr : manages reviews
templates --> flask_app : renders

vision_client --> openai_api : calls
openai_client --> openai_api : calls
openai_client --> llm_cache : caches responses
llm_cache --> postgres : stores cache

gold_standard --> v2_validator : validates
v2_validator --> extraction_v2 : compares
fresh_extractor --> extraction_v2 : extracts

config --> v2_stages : keyword patterns
config --> extraction_v1 : keyword patterns

@enduml
```

## Component Descriptions

### Infrastructure Layer
- **Database Adapter**: PostgreSQL connection and query management
- **SEC Client**: Fetches SEC filings via Edgar API
- **HTTP Client**: Generic HTTP utilities for external calls
- **Connection Pool**: Manages database connection pooling
- **Logging**: Centralized logging configuration

### Data Discovery & Retrieval
- **Universe Builder**: Discovers relevant S-1/F-1 filings
- **Filing Fetcher**: Retrieves and caches filing documents
- **Company Mapping**: Maps companies to SEC identifiers

### Extraction Pipeline
- **V1 Extraction**: Production extraction pipeline
- **V2 Extraction**: Unified pipeline for transcripts/presentations
  - **V2 Stages**: 15 sequential processing stages including candidate generation, OCR, deduplication, validation

### Review & Analysis
- **Candidate Generator**: Generates review candidates from extraction
- **Pattern Analyzer**: Analyzes metric disclosure patterns
- **Review Manager**: Orchestrates human review workflows

### LLM Integration
- **Vision Client**: Claude vision API for image analysis
- **OpenAI Client**: GPT integration for text analysis
- **LLM Cache**: PostgreSQL-backed caching layer
- **Prompts**: Centralized prompt templates

### Web Interface
- **Flask App**: Main application server
- **API Routes**: RESTful endpoints for data access
- **Review Routes**: Human review interface endpoints
- **Templates**: HTML templates for web UI

### Validation & Testing
- **Gold Standard**: Baseline validation framework
- **V2 Validator**: Validates V2 extraction accuracy
- **Fresh Extractor**: Re-extracts for comparison testing

### Configuration
- **Metric Keywords**: YAML-based keyword patterns (authoritative source for metrics)
