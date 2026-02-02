# GPT-4 Code Review: D6 Security

**Copy this entire prompt and paste into GPT-4**

---

You are a security engineer reviewing a Python Flask application that processes SEC filings.

## Application Profile

- **Framework**: Flask (web UI for human review)
- **Database**: PostgreSQL via psycopg3
- **External APIs**: SEC EDGAR, OpenAI
- **Authentication**: None (single-user internal tool)
- **Deployment**: Local development

## Security-Relevant Files

| File | LOC | Concern |
|------|-----|---------|
| `src/web/app.py` | 150 | Flask app config |
| `src/web/routes/api.py` | 341 | Review API endpoints |
| `src/web/routes/review.py` | 406 | Review UI routes |
| `src/infra/db.py` | 4,006 | SQL queries |
| `src/infra/validation.py` | ~200 | Input validation |

## Code Examples

### Flask Configuration
```python
# src/web/app.py
def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
    # ^^^ Weak default if env var not set

    app.config['DEBUG'] = True  # Hardcoded in some configs
    # No CSRF protection configured
    # No security headers configured
```

### API Endpoint (No Auth, No Rate Limit)
```python
# src/web/routes/api.py
@api_bp.route('/candidates/<int:candidate_id>/decision', methods=['POST'])
def create_decision(candidate_id: int):
    """Create review decision - no authentication check."""
    data = request.get_json()
    # Input validation exists but no auth/authz
    decision = DecisionCreate(
        candidate_id=candidate_id,
        is_valid=data.get('is_valid'),
        # ...
    )
```

### Database Query (Parameterized - Good)
```python
# src/infra/db.py
def get_candidate(self, candidate_id: int) -> Optional[ReviewCandidate]:
    query = """
        SELECT * FROM review_candidates WHERE id = %s
    """
    # Parameterized query - SAFE from SQL injection
    result = self._execute(query, (candidate_id,))
```

### File Path Handling
```python
# src/filing_fetcher/filing_fetcher.py
def _get_cache_path(self, cik: str, accession: str) -> Path:
    """Build path for cached filing."""
    # CIK and accession come from SEC API
    # No explicit path traversal check
    return self.cache_dir / cik / accession / "filing.htm"
```

### Template Rendering
```python
# src/web/routes/review.py
@review_bp.route('/candidate/<int:candidate_id>')
def view_candidate(candidate_id: int):
    candidate = db.get_candidate(candidate_id)
    # Template uses {{ candidate.context_text }}
    # Jinja2 auto-escapes by default - should be safe
    return render_template('candidate.html', candidate=candidate)
```

## OWASP Top 10 Checklist

| Risk | Status | Notes |
|------|--------|-------|
| A01 Broken Access Control | ⚠️ RISK | No authentication |
| A02 Cryptographic Failures | ⚠️ RISK | Weak SECRET_KEY default |
| A03 Injection | ✅ OK | Parameterized queries |
| A04 Insecure Design | ⚠️ RISK | No auth by design |
| A05 Security Misconfiguration | ⚠️ RISK | DEBUG=True, no headers |
| A06 Vulnerable Components | ❓ Unknown | No dependency scanning |
| A07 Auth Failures | ⚠️ RISK | No auth implemented |
| A08 Software/Data Integrity | ✅ OK | No deserialization |
| A09 Logging Failures | ❓ Unknown | Not audited |
| A10 SSRF | ✅ OK | SEC URLs only |

## Review Questions

1. **Authentication**: Is "no auth" acceptable for internal tool?
2. **SECRET_KEY**: How bad is the weak default?
3. **CSRF**: Should state-changing APIs have CSRF protection?
4. **Security Headers**: What headers are missing?
5. **Rate Limiting**: Should API endpoints be rate limited?
6. **Secrets in Logs**: Are credentials ever logged?

## Output Format

```json
{
  "dimension": "D6_SECURITY",
  "model": "gpt4",
  "findings": [
    {
      "id": "G-D6-001",
      "severity": "Critical|High|Medium|Low",
      "category": "security",
      "title": "Short title",
      "description": "Detailed description",
      "file": "path/to/file.py",
      "line_range": "100-150",
      "owasp_category": "A01-A10",
      "attack_scenario": "How this could be exploited",
      "recommendation": "What to do",
      "effort": "XS|S|M|L|XL"
    }
  ],
  "summary": "Overall security assessment"
}
```

Provide 10-15 findings covering web security concerns.
