"""
Image and OCR extraction pipeline for SEC filings.

This module implements the image/OCR extraction stages:
- Ingestion: parse HTML filing into segments and image assets
- Image Triage: classify images (chart, table_image, decorative)
- OCR Extraction: extract values from relevant images via OCR and vision models

Architecture:
    SEC HTML Filing
        ↓
    [Stage 1: Ingestion & Parsing] → Segments and ImageAsset objects
        ↓
    [Stage 2: Image Triage] → chart, table_image, decorative classification
        ↓
    [Stage 3: OCR & Chart Extraction] → labeled values only

Design Principles:
    1. Structure-first, LLM-second: DOM parsing → rules → LLM fallback
    2. No value without provenance: Every extracted value has a source locator
    3. Fail closed: Ambiguous extraction → flag for review, don't guess
    4. Charts only when labeled: Never interpolate from axis pixels
"""

__version__ = "2.0.0-alpha"
