# D6: Security Review Context

## Dimension Focus
Input validation, SQL injection prevention, XSS, secrets handling, file path safety, rate limiting.

## Primary Files to Review

### Web Layer
- **src/web/app.py** - Flask app factory, security middleware
- **src/web/routes/api.py** (341 LOC) - Review API endpoints
- **src/web/routes/review.py** (406 LOC) - Review UI routes
- **src/web/routes/api_images.py** - Image review endpoints

### Database Layer
- **src/infra/db.py** (4,006 LOC) - SQL query construction
- **src/infra/validation.py** - Input validation utilities

### External Integrations
- **src/infra/sec_client.py** - SEC EDGAR API client (external data source)
- **src/infra/http_client.py** - HTTP client with retry logic
- **src/llm/openai_client.py** - OpenAI API integration

### Configuration
- **.env.template** - Environment variables template
- **config/** - Configuration files (metric_keywords.yaml)

---

## OWASP Top 10 Analysis

### 1. Injection (SQL, Command, HTML)

#### SQL Injection
**Risk Level**: Low (using parameterized queries)

**Good Practice** (db.py):
```python
def get_company_by_cik(self, cik: str):
    with self.get_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM companies WHERE cik = %s",  # Parameterized
            (cik,)
        )
        return cursor.fetchone()
```

**Areas to Review**:
- All 4,006 lines of db.py for string interpolation
- Dynamic query construction in `bulk_insert_review_candidates`
- Search functionality in web routes

**Recommendation**: Run static analysis for SQL injection patterns:
```bash
ast-grep run --pattern 'conn.execute(f"$$$")' --lang python src/
```

#### Command Injection
**Risk Level**: Low (no shell command execution from user input)

**Review Points**:
- No `os.system()`, `subprocess.call()` with user input
- FilingFetcher uses HTTP requests, not shell commands

#### HTML Injection / XSS
**Risk Level**: Medium (needs verification)

**Jinja2 Auto-Escaping**: Enabled by default (good)
```python
# src/web/app.py
app = Flask(__name__)
# Jinja2 auto-escaping enabled by default for .html templates
```

**Areas to Review**:
- Raw HTML rendering in review UI (segment display)
- User-provided notes/comments in review decisions
- Error messages displaying user input

**Example to Investigate** (review.py):
```python
@bp.route('/review/<int:filing_id>')
def review_filing(filing_id):
    # Does this sanitize segment.raw_html before rendering?
    segments = db.get_segments_for_filing(filing_id)
    return render_template('review.html', segments=segments)
```

**Recommendation**: Audit all `render_template` calls for unsafe context variables.

---

### 2. Broken Authentication
**Risk Level**: N/A (no authentication system)

**Current State**: No login, no sessions, no user accounts

**Implications**:
- Review decisions are anonymous
- No audit trail for who made changes
- No access control on endpoints

**Recommendation**: Add authentication before production deployment if multi-user.

---

### 3. Sensitive Data Exposure
**Risk Level**: Medium (API keys, database credentials)

#### Secrets Management

**Good Practices**:
- ✅ API keys in `.env` (gitignored)
- ✅ `.env.template` for documentation
- ✅ No hardcoded secrets in code

**Areas to Review**:
1. **Logging**: Are secrets logged in error messages?
   ```python
   # BAD: Logs connection string with password
   logger.error(f"DB connection failed: {connection_string}")

   # GOOD: Logs without sensitive data
   logger.error("DB connection failed")
   ```

2. **Error responses**: Are secrets exposed in Flask error pages?
   - Debug mode in production?
   - Stack traces with credentials?

3. **Database storage**: Are API keys stored encrypted?
   - Currently: N/A (no user API keys stored)

**Environment Variables**:
```bash
# .env.template
DATABASE_URL=postgresql://user:password@localhost/filings_analysis
SEC_USER_AGENT="YourName contact@example.com"
OPENAI_API_KEY=sk-...
```

**Recommendation**: Audit logging statements for credential leakage.

---

### 4. XML External Entities (XXE)
**Risk Level**: Medium (HTML parsing)

**HTML Parsing**:
- BeautifulSoup: Generally safe from XXE (no XML entity expansion)
- lxml (V2): Has XXE protections enabled by default in recent versions

**Areas to Review**:
- `html_segmenter.py` - BeautifulSoup usage
- `extraction_v2/ingestion_stage.py` - lxml usage
- Check for custom XML parsing (none found)

**Recommendation**: Verify lxml version >= 4.6.3 (XXE protection enabled).

---

### 5. Broken Access Control
**Risk Level**: Medium (no authorization checks)

**Current State**: No access control on any endpoint

**Examples**:
```python
@bp.route('/api/candidates/<int:candidate_id>/approve', methods=['POST'])
def approve_candidate(candidate_id):
    # Anyone can approve - no authorization check!
    db.update_candidate_decision(candidate_id, 'accept')
    return jsonify({'status': 'ok'})
```

**Implications**:
- Any user can modify review decisions
- No role-based access control (RBAC)
- No audit trail

**Recommendation**: Add authorization before production if multi-user.

---

### 6. Security Misconfiguration
**Risk Level**: High (needs verification)

#### Flask Configuration

**Areas to Review**:
1. **Debug mode**: Is `DEBUG=True` in production?
   ```python
   # src/web/app.py
   app.run(debug=True)  # DANGEROUS in production!
   ```

2. **Secret key**: Is `SECRET_KEY` set for session security?
   ```python
   app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev')  # Weak default!
   ```

3. **CORS**: Are CORS headers too permissive?
   ```python
   @app.after_request
   def after_request(response):
       response.headers['Access-Control-Allow-Origin'] = '*'  # Too permissive!
   ```

4. **Security headers**: Are security headers set?
   - Content-Security-Policy
   - X-Frame-Options
   - X-Content-Type-Options
   - Strict-Transport-Security

**Recommendation**: Add Flask-Talisman for security headers.

---

### 7. Cross-Site Scripting (XSS)
**Risk Level**: Medium (needs verification)

**Protection Mechanisms**:
- Jinja2 auto-escaping (enabled by default) ✅
- No `| safe` filter usage (needs verification)
- No `innerHTML` in JavaScript (needs verification)

**High-Risk Areas**:
1. **Segment display**: Raw HTML from filings rendered in review UI
   ```html
   {# Does this escape raw_html or render it raw? #}
   <div class="segment">{{ segment.raw_html }}</div>
   ```

2. **User notes**: Review decision notes/comments
   ```html
   {# Are notes escaped? #}
   <p>{{ decision.notes }}</p>
   ```

3. **Error messages**: User input in error messages
   ```python
   return jsonify({'error': f'Invalid candidate_id: {candidate_id}'}), 400
   ```

**Recommendation**:
- Audit templates for `| safe` usage
- Sanitize raw HTML before storage (not just rendering)
- Add CSP header to prevent inline scripts

---

### 8. Insecure Deserialization
**Risk Level**: Low (no pickle, limited JSON)

**Serialization Usage**:
- ✅ JSON for API responses (safe)
- ✅ No pickle usage found
- ✅ No eval() or exec() calls

**Areas to Review**:
- YAML parsing in `keyword_config.py` (safe if no arbitrary code execution)
- JSON parsing from external sources (SEC API) - validate structure

**Recommendation**: Add JSON schema validation for external API responses.

---

### 9. Using Components with Known Vulnerabilities
**Risk Level**: Medium (needs dependency audit)

**Dependencies** (from requirements.txt):
- Flask, psycopg3, beautifulsoup4, openai, pyyaml, etc.

**Vulnerability Scanning**:
```bash
# Check for known vulnerabilities
pip install safety
safety check

# Or use pip-audit
pip install pip-audit
pip-audit
```

**Recommendation**:
- Run `safety check` in CI
- Set up Dependabot for automated security updates
- Pin major versions, allow patch updates

---

### 10. Insufficient Logging & Monitoring
**Risk Level**: Medium (basic logging exists)

**Current Logging**:
- ✅ Extraction pipeline logs to logger
- ✅ Error logging in database operations
- ⚠️ No security event logging
- ❌ No centralized logging (just stdout)

**Missing Security Logs**:
- Failed authorization attempts (N/A - no auth)
- Suspicious input patterns (injection attempts)
- Rate limit violations
- Bulk data access

**Recommendation**: Add security event logging and monitoring.

---

## Review Questions

### 1. Input Validation
**Question**: Is input validation complete at all system boundaries? User input, API responses, file content?

**Validation Points**:
- ✅ Database: `src/infra/validation.py` validates enums, scores
- ⚠️ Web routes: Limited validation (Flask type hints only)
- ❌ SEC API responses: No schema validation
- ❌ File uploads: N/A (no upload feature)

**Code Sample** (validation.py):
```python
def validate_enum(value: str, allowed: set[str], name: str) -> None:
    if value not in allowed:
        raise ValidationError(f"{name} must be one of {allowed}, got {value}")

def validate_score(score: float, name: str = "score") -> None:
    if not 0.0 <= score <= 1.0:
        raise ValidationError(f"{name} must be between 0.0 and 1.0, got {score}")
```

**Gaps**:
- No max length validation on text inputs
- No regex validation on CIK/accession numbers
- No rate limiting on API endpoints

**Recommendation**: Add Pydantic models for request validation.

### 2. SQL Injection
**Question**: Are all SQL queries parameterized? Check db.py for string interpolation.

**Audit Needed**: Search db.py (4,006 LOC) for:
- f-strings in SQL: `f"SELECT * FROM {table}"`
- String concatenation: `"SELECT * FROM " + table`
- `.format()` in SQL: `"SELECT * FROM {}".format(table)`

**Grep Pattern**:
```bash
grep -n "execute(f\"" src/infra/db.py
grep -n "execute(\".*%s" src/infra/db.py | head -20  # Should use %s (parameterized)
```

**Expected**: All queries use `%s` placeholders, no f-strings.

### 3. XSS Prevention
**Question**: Is XSS prevented in web routes? How is user-provided content sanitized before rendering?

**Jinja2 Auto-Escaping**: Enabled by default ✅

**High-Risk Templates** (requires manual review):
- `templates/review/filing.html` - Displays segment raw_html
- `templates/review/candidate.html` - Displays user notes
- `templates/error.html` - Displays error messages

**Recommendation**: Search for `| safe` filter usage:
```bash
grep -r "| safe" src/web/templates/
```

### 4. Secret Handling
**Question**: Are secrets properly handled? Not logged, not in error messages, environment-based?

**Checklist**:
- ✅ Secrets in .env (not hardcoded)
- ✅ .env in .gitignore
- ⚠️ Logging: Needs audit for credential leakage
- ⚠️ Error messages: Needs audit for info disclosure

**Audit Commands**:
```bash
# Check for hardcoded secrets
grep -r "sk-" src/  # OpenAI keys
grep -r "password.*=" src/ | grep -v ".env"

# Check for secret logging
grep -r "logger.*connection_string" src/
grep -r "logger.*api_key" src/
```

### 5. File Path Safety
**Question**: Is file path handling safe? Check for path traversal in filing_fetcher and web routes.

**File Operations**:
- Filing cache: `data/filings/{cik}_{accession}.html`
- Gold standard: `data/gold_standard/golden_set_251218.csv`

**Path Traversal Risk**:
```python
# Potentially unsafe
filing_path = f"data/filings/{cik}_{accession}.html"
# What if cik = "../../etc/passwd"?
```

**Safe Approach**:
```python
from pathlib import Path

filing_dir = Path("data/filings")
filing_path = (filing_dir / f"{cik}_{accession}.html").resolve()
if not filing_path.is_relative_to(filing_dir):
    raise ValueError("Path traversal attempt detected")
```

**Recommendation**: Audit all `Path()` and file I/O for traversal protection.

### 6. Rate Limiting
**Question**: Is rate limiting implemented? SEC requires 100ms minimum between requests.

**SEC API Rate Limiting**:
```python
# src/infra/sec_client.py
class SECClient:
    MIN_REQUEST_INTERVAL = 0.1  # 100ms (SEC requirement) ✅

    def _fetch(self, url):
        time.sleep(self.MIN_REQUEST_INTERVAL)  # Enforced ✅
        response = requests.get(url)
        return response
```

**Web API Rate Limiting**: ❌ Not implemented

**Recommendation**: Add Flask-Limiter for API rate limiting:
```python
from flask_limiter import Limiter

limiter = Limiter(app, key_func=lambda: request.remote_addr)

@bp.route('/api/candidates')
@limiter.limit("100 per hour")
def get_candidates():
    pass
```

---

## Security Checklist

| Area | Status | Notes |
|------|--------|-------|
| SQL parameterization | ✅ Likely OK | Uses psycopg3 parameterized queries |
| XSS in templates | ⚠️ Needs audit | Jinja2 auto-escape enabled, check `\| safe` |
| CSRF protection | ❌ Missing | No Flask-WTF CSRF tokens |
| Session security | ⚠️ Needs audit | Check SECRET_KEY configuration |
| File path validation | ⚠️ Needs audit | Check for path traversal protection |
| Rate limiting | ⚠️ Partial | SEC client only, no web API limiting |
| Logging secrets | ⚠️ Needs audit | Check log statements for credentials |
| Error disclosure | ⚠️ Needs audit | Check debug mode, stack traces |
| Dependency vulnerabilities | ⚠️ Needs audit | Run `safety check` |
| Security headers | ❌ Missing | No CSP, X-Frame-Options, etc. |

---

## Known Security Concerns

1. **No authentication/authorization** - Anyone can access/modify data
2. **Debug mode in production?** - Needs verification
3. **No CSRF protection** - Vulnerable to cross-site request forgery
4. **No security headers** - Missing CSP, X-Frame-Options, HSTS
5. **No API rate limiting** - Vulnerable to abuse
6. **Secrets in logs?** - Needs audit for credential leakage
7. **XSS in segment display?** - Raw HTML rendering needs verification

---

## SEC API Compliance

### Rate Limiting
- ✅ Requirement: 100ms minimum between requests
- ✅ Implementation: `time.sleep(0.1)` in sec_client.py

### User-Agent
- ✅ Requirement: Required by SEC
- ✅ Implementation: Set via `SEC_USER_AGENT` env var

---

## Recommendations

### P0 - Critical
1. **Add authentication/authorization** - If multi-user deployment
2. **Disable debug mode in production** - Set `DEBUG=False`
3. **Add CSRF protection** - Use Flask-WTF
4. **Audit SQL queries** - Check all 4,006 lines of db.py for injection

### P1 - High
5. **Add security headers** - Use Flask-Talisman (CSP, X-Frame-Options, HSTS)
6. **Add API rate limiting** - Use Flask-Limiter
7. **Audit XSS risks** - Check template `| safe` usage, raw HTML rendering
8. **Audit secret logging** - Ensure no credentials in logs

### P2 - Medium
9. **Run dependency audit** - `safety check` or `pip-audit`
10. **Add file path validation** - Protect against path traversal
11. **Add security event logging** - Log suspicious activity
12. **Add JSON schema validation** - Validate external API responses

---

## Output Location
Write findings to: `ops/review_artifacts/claude/D6_findings.json`
