"""
Minimal Flask server for Playwright UI tests.
Renders review.html with mock data, stubbing out custom filters and url_for.
"""
import os
from datetime import datetime

from flask import Blueprint, Flask, jsonify, render_template, send_from_directory

# Add project root to path so templates resolve
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

app = Flask(
    __name__,
    template_folder=os.path.join(PROJECT_ROOT, 'src', 'web', 'templates'),
    static_folder=os.path.join(PROJECT_ROOT, 'src', 'web', 'static'),
)
app.config['TESTING'] = True

# Create blueprints matching real app's endpoint names
review_bp = Blueprint('review', __name__)
review_pres_images_bp = Blueprint('review_pres_images', __name__)


# Stub custom Jinja2 filters
def highlight_html(text, number, keyword):
    """Stub: return text as-is."""
    return text or ''


def highlight_context(text, number, keyword):
    """Stub: return text with basic highlighting."""
    if not text:
        return ''
    if number and number in text:
        text = text.replace(
            number,
            f'<span class="extracted-number">{number}</span>'
        )
    if keyword and keyword in text:
        text = text.replace(
            keyword,
            f'<span class="triggering-keyword">{keyword}</span>'
        )
    return text


app.jinja_env.filters['highlight_html'] = highlight_html
app.jinja_env.filters['highlight_context'] = highlight_context
app.jinja_env.filters['truncate'] = lambda s, n: s[:n] if s else ''


# Mock data
MOCK_FILING = type('Filing', (), {
    'filing_id': 1,
    'company_name': 'Acme Corp',
    'form_type': 'S-1',
    'filing_date': datetime(2025, 3, 15),
    'cik': '0001234567',
    'accession_number': '0001234567-25-000001',
    'sec_html_url': 'https://www.sec.gov/example',
})()

MOCK_CANDIDATE = type('Candidate', (), {
    'candidate_id': 101,
    'suggested_metric_id': 'cm_net_revenue_retention',
    'suggestion_confidence': 0.85,
    'parsed_value': 1234567.89,
    'parsed_unit': 'usd',
    'raw_number_text': '1,234,567.89',
    'triggering_keyword': 'revenue retention',
    'keyword_distance': 12,
    'keyword_position': 'before',
    'context_text': 'The company reported a net revenue retention rate of 1,234,567.89 for the fiscal year ended December 2024.',
    'segment_html': None,
    'segment_html_table_only': None,
    'segment_type': 'text',
    'review_status': 'pending',
    'source_segment_id': 42,
    'features': {
        'number_format': 'decimal',
        'is_in_table': False,
        'contains_definition_language': True,
        'is_in_risk_factors': False,
    },
})()

MOCK_CANDIDATE_REVIEWED = type('CandidateReviewed', (), {
    'candidate_id': 102,
    'suggested_metric_id': 'cm_total_customers',
    'suggestion_confidence': 0.45,
    'parsed_value': 5000,
    'parsed_unit': 'count',
    'raw_number_text': '5,000',
    'triggering_keyword': 'customers',
    'keyword_distance': 8,
    'keyword_position': 'after',
    'context_text': 'Our total customers reached 5,000 by Q4.',
    'segment_html': None,
    'segment_html_table_only': None,
    'segment_type': 'text',
    'review_status': 'reviewed',
    'source_segment_id': 43,
    'features': None,
})()

MOCK_METRICS = [
    type('Metric', (), {'metric_id': 'cm_net_revenue_retention', 'display_name': 'Net Revenue Retention'})(),
    type('Metric', (), {'metric_id': 'cm_total_customers', 'display_name': 'Total Customers'})(),
    type('Metric', (), {'metric_id': 'cm_arpu', 'display_name': 'Average Revenue Per User'})(),
    type('Metric', (), {'metric_id': 'cm_churn_rate', 'display_name': 'Churn Rate'})(),
    type('Metric', (), {'metric_id': 'cm_gross_revenue_retention', 'display_name': 'Gross Revenue Retention'})(),
    type('Metric', (), {'metric_id': 'cm_ltv', 'display_name': 'Lifetime Value'})(),
]

MOCK_FILTERS = type('Filters', (), {
    'status': 'all',
    'metric': 'all',
    'confidence': 'all',
    'sort': 'position',
    'has_active_filters': False,
})()

REJECTION_CATEGORIES = [
    'wrong_metric', 'not_a_metric', 'wrong_value',
    'wrong_period', 'part_of_date', 'duplicate', 'other'
]


# --- Blueprint routes (must match endpoint names used in templates) ---

@review_bp.route('/')
def filing_list():
    return 'Filing List (stub)'


@review_bp.route('/review/<int:filing_id>')
def review_filing(filing_id):
    return 'Review Filing (stub)'


@review_bp.route('/review/<int:filing_id>/next')
def next_candidate(filing_id, **kwargs):
    return 'Next Candidate (stub)'


@review_bp.route('/stats')
def stats():
    return 'Stats (stub)'


@review_pres_images_bp.route('/pres-images')
def index():
    return 'Pres Images (stub)'


# --- App-level routes for actual test pages ---

@app.route('/')
def review_pending():
    """Render review page with a pending candidate (edit mode)."""
    return render_template(
        'review.html',
        filing=MOCK_FILING,
        candidates=[MOCK_CANDIDATE, MOCK_CANDIDATE_REVIEWED],
        current_candidate=MOCK_CANDIDATE,
        existing_decision=None,
        metrics=MOCK_METRICS,
        rejection_categories=REJECTION_CATEGORIES,
        extraction_date=datetime(2025, 3, 16),
        reviewed_count=1,
        pending_count=1,
        total_candidates=2,
        total_candidates_unfiltered=2,
        current_filters=MOCK_FILTERS,
        available_metrics=['cm_net_revenue_retention', 'cm_total_customers'],
    )


@app.route('/reviewed')
def review_already_reviewed():
    """Render review page for an already-reviewed candidate (read-only mode)."""
    existing = type('Decision', (), {
        'decision': 'accept',
        'assigned_metric_id': 'cm_total_customers',
        'is_automated': False,
        'rejection_category': None,
        'rejection_reason': None,
        'reviewer_notes': 'Looks correct',
        'created_at': datetime(2025, 3, 17, 14, 30),
    })()
    return render_template(
        'review.html',
        filing=MOCK_FILING,
        candidates=[MOCK_CANDIDATE, MOCK_CANDIDATE_REVIEWED],
        current_candidate=MOCK_CANDIDATE_REVIEWED,
        existing_decision=existing,
        metrics=MOCK_METRICS,
        rejection_categories=REJECTION_CATEGORIES,
        extraction_date=datetime(2025, 3, 16),
        reviewed_count=1,
        pending_count=1,
        total_candidates=2,
        total_candidates_unfiltered=2,
        current_filters=MOCK_FILTERS,
        available_metrics=['cm_net_revenue_retention', 'cm_total_customers'],
    )


@app.route('/api/decisions', methods=['POST'])
def mock_submit_decision():
    """Mock decision endpoint for testing."""
    return jsonify({
        'status': 'success',
        'decision_id': 999,
        'next_candidate': {'url': '/'},
    })


@app.route('/api/decisions/<int:decision_id>', methods=['DELETE'])
def mock_undo_decision(decision_id):
    """Mock undo endpoint."""
    return jsonify({
        'status': 'success',
        'message': 'Decision reverted',
        'candidate_id': 101,
        'candidate_url': '/',
    })


@app.route('/api/candidates/<int:cid>/skip', methods=['POST'])
def mock_skip(cid):
    return jsonify({'status': 'success', 'next_candidate': {'url': '/'}})


# Serve local Bootstrap files (CDN not accessible in test environment)
BOOTSTRAP_DIR = os.path.join(PROJECT_ROOT, 'node_modules', 'bootstrap', 'dist')


@app.route('/bootstrap/<path:filename>')
def serve_bootstrap(filename):
    return send_from_directory(BOOTSTRAP_DIR, filename)


# Register blueprints with url_prefix to avoid route conflicts
app.register_blueprint(review_bp, url_prefix='/bp')
app.register_blueprint(review_pres_images_bp, url_prefix='/bp')


if __name__ == '__main__':
    app.run(port=5199, debug=False)
