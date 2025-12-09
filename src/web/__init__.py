"""
Flask web application for human-in-the-loop metric extraction review.

This package provides:
- Review interface for validating candidate metric extractions
- API endpoints for recording decisions
- Pattern analysis and reporting views
"""

from src.web.app import create_app

__all__ = ["create_app"]
