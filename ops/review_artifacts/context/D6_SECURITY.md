# D6: Security Review Context

## Dimension Focus
Input validation, SQL injection prevention, XSS, secrets handling, file path safety, rate limiting.

## Primary Files to Review

### Web Layer
- `src/web/app.py` - Flask app factory
- `src/web/routes/api.py` (341 LOC) - Review API endpoints
- `src/web/routes/review.py` (406 LOC) - Review UI routes
- `src/web/routes/api_images.py` - Image review endpoints

### Database Layer
- `src/infra/db.py` (4,006 LOC) - SQL query construction
- `src/infra/validation.py` - Input validation

### External Integrations
- `src/infra/sec_client.py` - SEC EDGAR API client
- `src/infra/http_client.py` - HTTP client with retry
- `src/llm/openai_client.py` - OpenAI API integration

### Configuration
- `.env.template` - Environment variables template
- `config/` - Configuration files

## Review Questions

1. **Input Validation**: Is input validation complete at all system boundaries? User input, API responses, file content?

2. **SQL Injection**: Are all SQL queries parameterized? Check db.py for string interpolation.

3. **XSS Prevention**: Is XSS prevented in web routes? How is user-provided content sanitized before rendering?

4. **Secret Handling**: Are secrets properly handled? Not logged, not in error messages, environment-based?

5. **File Path Safety**: Is file path handling safe? Check for path traversal in filing_fetcher and web routes.

6. **Rate Limiting**: Is rate limiting implemented? SEC requires 100ms minimum between requests.

## Known Security Considerations

### SEC API Compliance
- Rate limiting: 100ms minimum between requests (required by SEC)
- User-Agent: Required, set via SEC_USER_AGENT env var

### Database
- Uses psycopg3 with parameterized queries (generally safe)
- Connection pooling with credential management

### Secrets
- API keys in .env (gitignored)
- DATABASE_URL, OPENAI_API_KEY, SEC_USER_AGENT

### File Handling
- Filing cache in data/filings/
- User uploads not supported (read-only system)

## Security Checklist

| Area | Status | Notes |
|------|--------|-------|
| SQL parameterization | Likely OK | psycopg3 default |
| XSS in templates | Unknown | Check Jinja2 escaping |
| CSRF protection | Unknown | Check Flask-WTF |
| Session security | Unknown | Check cookie settings |
| File path validation | Unknown | Check filing paths |
| Rate limiting | Partial | SEC client only |
| Logging secrets | Unknown | Check log statements |
| Error disclosure | Unknown | Check error handlers |

## OWASP Top 10 Focus Areas

1. **Injection** - SQL, command injection via user input
2. **Broken Authentication** - Session management
3. **Sensitive Data Exposure** - API keys, credentials
4. **XML External Entities** - HTML/XML parsing
5. **Broken Access Control** - Authorization checks
6. **Security Misconfiguration** - Debug mode, headers
7. **XSS** - Template rendering
8. **Insecure Deserialization** - Pickle, JSON parsing
9. **Components with Known Vulnerabilities** - Dependencies
10. **Insufficient Logging** - Security events

## Output Location
Write findings to: `ops/review_artifacts/claude/D6_findings.json`
