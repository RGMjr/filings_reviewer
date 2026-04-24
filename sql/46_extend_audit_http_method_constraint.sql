-- Extend the http_method allowlist to include HEAD and OPTIONS.
-- Render's health prober issues HEAD requests which previously violated
-- the constraint on every probe cycle, generating rollbacks and log noise.
ALTER TABLE v2_audit_log DROP CONSTRAINT check_v2_audit_http_method;
ALTER TABLE v2_audit_log ADD CONSTRAINT check_v2_audit_http_method
    CHECK (http_method IN ('GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'));
