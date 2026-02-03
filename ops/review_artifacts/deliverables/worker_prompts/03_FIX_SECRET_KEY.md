# Worker Prompt: Remove Hardcoded SECRET_KEY

## Task ID: REV-03
## Priority: P0 (Security Critical)
## Effort: XS (< 30 minutes)
## Finding IDs: G-D6-002, S-D6-002

---

## Problem Statement

Flask app uses a hardcoded fallback SECRET_KEY (`"dev-secret-key-not-for-production"`). Flask signs session cookies with SECRET_KEY. If the app is ever reachable by others:

- Attackers can **forge session cookies**
- Attackers can **tamper with session data**
- Future auth controls can be **bypassed**
- Audit logging becomes **unreliable**

---

## Files to Modify

- `src/web/app.py` - Remove default, fail fast
- `.env.template` - Document requirement

---

## Acceptance Criteria

1. [ ] No hardcoded SECRET_KEY in source code
2. [ ] App fails fast on startup if SECRET_KEY not set (except dev mode)
3. [ ] Development mode auto-generates random key with warning
4. [ ] Production mode requires explicit SECRET_KEY
5. [ ] .env.template documents requirement

---

## Implementation

### Before (Insecure)

```python
# src/web/app.py
class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-not-for-production")
```

### After (Secure)

```python
# src/web/app.py
import secrets
import warnings

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")

    @classmethod
    def validate(cls):
        if not cls.SECRET_KEY:
            raise ValueError(
                "SECRET_KEY environment variable must be set. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )

class DevelopmentConfig(Config):
    DEBUG = True

    @classmethod
    def validate(cls):
        if not cls.SECRET_KEY:
            cls.SECRET_KEY = secrets.token_hex(32)
            warnings.warn(
                "No SECRET_KEY set - generated random key for development. "
                "Sessions will not persist across restarts.",
                UserWarning
            )

class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key-for-testing-only"  # OK for tests

class ProductionConfig(Config):
    DEBUG = False

    @classmethod
    def validate(cls):
        if not cls.SECRET_KEY:
            raise ValueError("SECRET_KEY must be set in production!")
        if len(cls.SECRET_KEY) < 32:
            raise ValueError("SECRET_KEY should be at least 32 characters")

def create_app(config_class=None):
    if config_class is None:
        env = os.environ.get("FLASK_ENV", "development")
        config_class = {
            "development": DevelopmentConfig,
            "testing": TestingConfig,
            "production": ProductionConfig,
        }.get(env, DevelopmentConfig)

    # Validate config before creating app
    config_class.validate()

    app = Flask(__name__)
    app.config.from_object(config_class)
    ...
```

### Update .env.template

```bash
# .env.template

# REQUIRED: Flask secret key for session signing
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=

# Optional: Set to 'production' to enforce strict validation
FLASK_ENV=development
```

---

## Verification Commands

```bash
# Test production mode fails without SECRET_KEY
FLASK_ENV=production python -c "from src.web.app import create_app; create_app()"
# Expected: ValueError: SECRET_KEY must be set in production!

# Test development mode works with warning
FLASK_ENV=development python -c "from src.web.app import create_app; create_app()"
# Expected: UserWarning about generated key

# Generate a production key
python -c "import secrets; print(secrets.token_hex(32))"

# Run tests
pytest tests/unit/web/ -v
```

---

## Time Estimate

- Implementation: 15 minutes
- Testing: 10 minutes
- Documentation: 5 minutes

**Total: ~30 minutes**
