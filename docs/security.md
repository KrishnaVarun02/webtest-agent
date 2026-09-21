# Security and privacy

WebTest Agent is an authorized-testing tool. The user must own the target or
have explicit permission to test it. The extension refuses to start until at
least one allowed origin is configured, and generated tests independently
validate `WEBTEST_BASE_URL` against `WEBTEST_AUTHORIZED_ORIGINS`.

## Trust boundaries

Browser content is untrusted. Recordings are validated and sanitized before
they are persisted or sent to a model. Model output is also untrusted: AI
exploration accepts one schema-validated action at a time, only against a
provided element reference, and never executes model-supplied JavaScript.
Generated source comes from deterministic templates and an approved plan.

The reference ZIP is untrusted input. It is never executed or packaged.

## Redaction

Header names such as `Authorization`, `Cookie`, `Set-Cookie`, and API-key
headers are replaced with `${REDACTED}`. Query parameters and object fields
whose names contain `token`, `key`, `secret`, `password`, `authorization`,
`credential`, or `session` are treated as sensitive. Bearer/JWT-like strings
and common secret assignments are scrubbed as a second line of defense.

Redaction happens before:

1. extension recording storage and export;
2. orchestrator model input and SQLite persistence;
3. generated source/resource creation;
4. execution logs and HTML reports.

Secret values are supplied to generated tests only through environment
variables. Tests seed marker secrets and scan recordings, database rows,
prompt payloads, generated files, and reports for leakage.

## Exploration limits

Exploration is same-origin and constrained by action count, elapsed time,
retry count, and repeated-state detection. CAPTCHA, payment/purchase, account
deletion, file upload, privilege change, authentication bypass, and arbitrary
script execution are rejected. Potential server mutations require a separate
user approval. Manual capture does not depend on AI exploration.

## Replay limits

WebTest Agent does not automatically replay captured mutations. A human must
approve the plan before generation. Negative tests require an explicit
non-production declaration. Destructive tests remain excluded unless
`ALLOW_DESTRUCTIVE_TESTS=true`, and the sample application requires an
additional confirmation header for archival.

## Operational advice

- Use a dedicated non-production tenant with least-privilege test accounts.
- Keep `.env` files outside version control and rotate exposed credentials.
- Review proposed data dependencies and destructive flags before approval.
- Limit allowed origins to exact scheme/host/port values.
- Do not send a recording to an external model provider unless its sanitized
  content and the provider's data policy are acceptable.
