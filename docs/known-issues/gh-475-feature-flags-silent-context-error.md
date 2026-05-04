---
id: 475
source: gh
slug: feature-flags-silent-context-error
title: "auth: feature_flags _read_flag_from_db silently swallows context errors, hides config bugs"
status: open
severity: medium
autonomy: skip
estimated: S
touches:
  - src/auth/feature_flags.py
  - src/auth/csrf.py
  - src/auth/load_user.py
discovered: 2026-05-04
updated: 2026-05-04
gh_issue: 475
pr_refs:
  - 472
note: broad except in feature_flags swallowed RuntimeError during Stage B activation; symptom fixed in #472, broader hazard remains
---

### Problem

During Stage B activation on 2026-05-04, the `auth_bp` blueprint failed to register despite `feature_flags.google_login_enabled='true'` being correctly set in the DB. Root cause: `is_enabled()` was called from `create_app()` (boot time, no Flask app context active), `_read_flag_from_db` calls `get_db()` which touches `current_app`, raising `RuntimeError: Working outside of application context`. The broad `except Exception` in `src/auth/feature_flags.py::_read_flag_from_db` swallowed this and silently returned False. The single WARNING line in the deploy log was easy to miss until `/auth/login` returned 404.

The symptom-level fix shipped in #472 (wrap the boot-time check in `with app.app_context():`). The broader hazard remains: any future configuration error or programmer error that raises during a flag read silently degrades to default-off — and on a security-sensitive flag, default-off is the wrong direction in some cases.

### Next Steps

- Distinguish transient DB errors (connection, network) from programmer errors (`RuntimeError: Working outside of application context`, `ImportError`, attribute errors). Log the latter at `ERROR` or re-raise instead of swallowing as WARNING.
- Consider a fail-closed mode for security-sensitive flags: if `is_enabled()` raises an unexpected exception type, raise rather than default to False, so misconfigurations surface loudly instead of silently.
- Audit other `except Exception` blocks in the auth surface (`src/auth/csrf.py`, `src/auth/load_user.py`) for similar silent-fallback hazards.
