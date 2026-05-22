"""Centralized Sentry initialization shared by every process entry point.

One hardened ``init_sentry()`` so the web app, the onboarding worker, batch
scripts, and the V2 extraction pipeline all report errors with identical
configuration: PII scrubbing, errors-only sampling (the free tier shares a
single quota across errors and traces), and deploy-SHA release tagging.

No-op when ``SENTRY_DSN`` is unset or when running under the testing config —
so local dev, CI, and the test suite never emit events. See
``.claude/rules/infrastructure.md`` (Environment Variables) for the operator
contract and ``docs/operations/setup-guide.md`` for the toggle.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Project-specific keys to scrub from event payloads, on top of the SDK's
# DEFAULT_DENYLIST (password / secret / api_key / auth / token / ...). These
# cover reviewer PII and connection secrets that can surface in stack-trace
# locals or request data even with ``send_default_pii=False``.
_EXTRA_DENYLIST = [
    "reviewer_id",
    "reviewer_name",
    "email",
    "normalized_email",
    "google_sub",
    "database_url",
    "test_database_url",
    "filings_api_key",
    "secret_key",
    "sec_user_agent",
    "openai_api_key",
    "google_api_key",
    "anthropic_api_key",
    "r2_access_key_id",
    "r2_secret_access_key",
]


def init_sentry(app_env: str | None = None) -> bool:
    """Initialize Sentry once, with hardened defaults. Returns True if active.

    No-op (returns False) when:
      - ``app_env`` (or ``APP_ENV``) is ``"testing"`` — guards the test suite,
        which builds the app via ``create_app("testing")`` and would otherwise
        emit events if a contributor's ``.env`` has ``SENTRY_DSN`` uncommented;
      - ``SENTRY_DSN`` is unset / empty;
      - ``sentry-sdk`` is not importable;
      - Sentry is already initialized (idempotent — safe to call from each
        entry point).

    Args:
        app_env: Resolved environment name. The web app passes its Flask config
            name; other callers leave it ``None`` to read ``APP_ENV``.
    """
    if app_env is None:
        app_env = os.environ.get("APP_ENV", "development")
    if app_env == "testing":
        return False

    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; skipping Sentry init")
        return False

    # Idempotent: a second call (e.g. create_app re-invoked, or a worker that
    # also runs configure_logging) is a no-op.
    if sentry_sdk.get_client().is_active():
        return True

    sentry_sdk.init(
        dsn=dsn,
        environment=app_env,
        # Ties each issue to a deploy. RENDER_GIT_COMMIT is the same SHA the
        # /version endpoint reports; None (local dev) is accepted by the SDK.
        release=os.environ.get("RENDER_GIT_COMMIT"),
        # Errors only — keep within the free 5K events/month budget.
        traces_sample_rate=0.0,
        profiles_sample_rate=0.0,
        # Never send PII. Under this flag the SDK strips cookies, client IP, and
        # auth headers; the scrubber additionally removes the keys below from
        # request data and stack-trace locals.
        send_default_pii=False,
        event_scrubber=EventScrubber(
            denylist=DEFAULT_DENYLIST + _EXTRA_DENYLIST,
            recursive=True,
        ),
        # logger.error -> Sentry event (this is the SDK default, stated
        # explicitly as the #1 quota tuning knob: handled errors that route
        # handlers already turn into 4xx still emit events. If a noisy logger
        # dominates the free budget, raise event_level or call
        # sentry_sdk.integrations.logging.ignore_logger("<name>"). Unhandled web
        # 500s (FlaskIntegration, auto-enabled) and worker crashes (excepthook)
        # are captured independently of this integration.
        integrations=[
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
    )
    logger.info("Sentry initialized (environment=%s)", app_env)
    return True
