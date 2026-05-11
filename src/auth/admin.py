"""
``admin_required`` — Flask route decorator that hard-gates admin-only routes.

Unlike ``src.auth.middleware.require()``, this decorator does **NOT** consult
the ``auth_enforcement_enabled`` feature flag.  It is always active regardless
of the Stage B / Stage C rollout state.

Rationale: admin pages must be protected from the moment they are deployed.
The flag-gated ``require()`` is safe to merge pre-flip because it is a no-op
until the operator flips the flag.  Admin pages do not have that luxury —
an unprotected admin endpoint in a partially-deployed state is a security
risk, not just an inconvenience.

Usage::

    from src.auth.admin import admin_required

    @app.route("/admin/review")
    @admin_required
    def admin_review():
        ...

``g.user`` must be populated by ``load_session_user`` (registered as a
``before_request`` hook on the Flask app) before this decorator runs.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any

from flask import g, jsonify

logger = logging.getLogger(__name__)

# Type alias for Flask view functions.
_ViewFunc = Callable[..., Any]


def admin_required(f: _ViewFunc) -> _ViewFunc:
    """Decorator that restricts a Flask route to users with ``role='admin'``.

    Returns a 403 JSON response when:
    - ``g.user`` is ``None`` (unauthenticated).
    - ``g.user.role`` is anything other than ``'admin'``.

    Delegates to the wrapped function when ``g.user.role == 'admin'``.

    This decorator is **flag-independent**: it does not consult
    ``auth_enforcement_enabled`` and is always enforced.

    Args:
        f: The Flask view function to protect.

    Returns:
        The wrapped view function.
    """

    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        user = getattr(g, "user", None)
        if user is None or getattr(user, "role", None) != "admin":
            logger.debug(
                "admin_required: access denied for %s",
                getattr(user, "role", "anonymous"),
            )
            return jsonify({"error": "admin access required"}), 403
        return f(*args, **kwargs)

    return wrapper
