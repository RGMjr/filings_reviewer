# Worker Prompt: Add Authentication to API Routes

## Task ID: REV-02
## Priority: P0 (Security Critical)
## Effort: S (2-4 hours)
## Finding IDs: G-D6-001, S-D6-001

---

## Problem Statement

All API endpoints are callable by anyone who can reach the server. Endpoints include decision creation, bulk decisions, skipping candidates, and undoing decisions. This is a **critical security risk** if the service is ever reachable beyond localhost.

### Attack Scenario

An attacker on the same network (or malware on the host) sends POST `/api/decisions` or `/api/bulk-decisions` to accept/reject/reclassify candidates at scale, corrupting your dataset and audit trail.

---

## Files to Modify

- `src/web/app.py` - Add auth configuration
- `src/web/routes/api.py` - Protect all routes
- `src/web/routes/api_images.py` - Protect image routes
- `.env.template` - Add API_KEY variable

---

## Acceptance Criteria

1. [ ] Flask binds to 127.0.0.1 by default (not 0.0.0.0)
2. [ ] API key required for all `/api/*` routes
3. [ ] Invalid/missing API key returns 401 Unauthorized
4. [ ] API key configurable via environment variable
5. [ ] Development mode allows bypass for local testing
6. [ ] Existing tests updated to pass API key

---

## Implementation Steps

### Step 1: Bind to Localhost by Default

```python
# src/web/app.py
def run_dev_server():
    app = create_app()
    host = os.environ.get("FLASK_HOST", "127.0.0.1")  # Default to localhost
    port = int(os.environ.get("FLASK_PORT", 5000))

    if host != "127.0.0.1":
        logger.warning("Running on non-localhost. Ensure authentication is enabled!")

    app.run(host=host, port=port, debug=app.config.get("DEBUG", False))
```

### Step 2: Add API Key Configuration

```python
# src/web/app.py
class Config:
    API_KEY = os.environ.get("FILINGS_API_KEY")
    API_KEY_REQUIRED = os.environ.get("API_KEY_REQUIRED", "true").lower() == "true"

class DevelopmentConfig(Config):
    API_KEY_REQUIRED = False  # Allow bypass in dev

class ProductionConfig(Config):
    API_KEY_REQUIRED = True

    @classmethod
    def validate(cls):
        if not cls.API_KEY:
            raise ValueError("FILINGS_API_KEY must be set in production")
```

### Step 3: Create Auth Decorator

```python
# src/web/auth.py
from functools import wraps
from flask import request, jsonify, current_app

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_app.config.get("API_KEY_REQUIRED"):
            return f(*args, **kwargs)

        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = current_app.config.get("API_KEY")

        if not expected_key:
            return jsonify({"error": "Server misconfigured: no API key set"}), 500

        if not api_key:
            return jsonify({"error": "Missing API key"}), 401

        # Constant-time comparison to prevent timing attacks
        import hmac
        if not hmac.compare_digest(api_key, expected_key):
            return jsonify({"error": "Invalid API key"}), 401

        return f(*args, **kwargs)
    return decorated
```

### Step 4: Protect All API Routes

```python
# src/web/routes/api.py
from src.web.auth import require_api_key

# Apply to all routes:
@bp.route("/decisions", methods=["POST"])
@require_api_key
def create_decision():
    ...

@bp.route("/bulk-decisions", methods=["POST"])
@require_api_key
def create_bulk_decisions():
    ...

# OR apply to entire blueprint:
@bp.before_request
def check_auth():
    if current_app.config.get("API_KEY_REQUIRED"):
        # Check API key for all requests to this blueprint
        ...
```

### Step 5: Update .env.template

```bash
# .env.template
# Security
FILINGS_API_KEY=your-secure-api-key-here  # Required in production
API_KEY_REQUIRED=true  # Set to false for local development
FLASK_HOST=127.0.0.1  # Never bind to 0.0.0.0 without auth
```

### Step 6: Update Tests

```python
# tests/conftest.py
@pytest.fixture
def api_client(app):
    """Client with API key for authenticated requests."""
    app.config["API_KEY"] = "test-api-key"
    app.config["API_KEY_REQUIRED"] = True

    client = app.test_client()
    client.environ_base["HTTP_X_API_KEY"] = "test-api-key"
    return client

# In tests:
def test_create_decision(api_client):
    response = api_client.post("/api/decisions", json={...})
    assert response.status_code == 201
```

---

## Verification Commands

```bash
# Test without API key (should fail)
curl -X POST http://localhost:5000/api/decisions -H "Content-Type: application/json" -d '{}'
# Expected: 401 Unauthorized

# Test with API key (should work)
curl -X POST http://localhost:5000/api/decisions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"candidate_id": 1, "decision": "accept"}'
# Expected: 201 Created

# Run tests
pytest tests/unit/web/ -v
```

---

## Security Notes

- Use a cryptographically secure random key (32+ characters)
- Rotate keys periodically
- Log authentication failures for monitoring
- Consider adding rate limiting (see REV-07)
- For multi-user scenarios, consider upgrading to Flask-Login or OIDC
