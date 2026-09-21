# Reference patterns

`obp-qa.zip` was inspected as untrusted, read-only reference material. It was
not executed, added to this repository, or used as a dependency. The archive
contains application-specific code and data, build outputs, logs, reports,
Git history, plaintext credential assignments, private keys, and a PKCS#12
file. Those artifacts must be treated as compromised outside this project;
they are intentionally absent from WebTest Agent.

## General patterns retained

The reference showed several useful, domain-independent automation patterns:

- Maven keeps reusable HTTP/configuration/reporting code separate from TestNG
  scenario classes and suite XML.
- Request execution benefits from a single wrapper so authentication,
  serialization, diagnostics, timeouts, and redaction behave consistently.
- Structured request/test-data files reduce duplicated test code.
- A per-scenario value map carries IDs and other response-derived values into
  later requests.
- Response values are extracted through JSON paths and reused instead of
  hard-coding environment-specific identifiers.
- TestNG listeners can attach the most recent sanitized exchange and failure
  details to a human-readable HTML report.
- TestNG groups/suites provide useful smoke, regression, and ordering controls.
- Stateful workflows need bounded status polling, observable final-state
  assertions, and cleanup where a recorded safe cleanup operation exists.
- Positive and negative cases are easier to diagnose when each negative case
  changes exactly one part of a valid request.

## Generic implementation in WebTest Agent

The generator applies those ideas without retaining any source implementation:

- `RequestExecutor` centralizes Rest Assured requests and report events.
- `RequestDefinition` is the data-driven request model.
- `AuthProvider` adapters isolate no-auth, bearer, basic, API-key, cookie, and
  custom authentication.
- `ScenarioContext` and `DynamicValueExtractor` implement substitution and
  response-to-request dependencies.
- `PollingUtility` uses a deadline and fixed maximum request rate.
- `AssertionUtility` checks statuses, content types, required fields, and
  dynamic formats without exact whole-body comparisons.
- `SecretRedactor` is applied before persistence and reporting.
- The generated listener writes sanitized execution diagnostics.
- TestNG groups separate positive, negative, asynchronous, smoke, regression,
  and destructive tests. Destructive tests are opt-in.

## Patterns deliberately rejected

WebTest Agent does not reproduce provider names, URLs, credentials, payloads,
logos, proprietary configuration, infrastructure commands, domain models, or
business assertions from the reference. It also avoids fixed sleeps, global
mutable credentials, unredacted response logging, hard-coded IDs, implicit
production targeting, and packaging test secrets into build images.

