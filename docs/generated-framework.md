# Generated Java framework

Every approved plan produces a standalone Maven project targeting Java 21.
Framework files are deterministic; scenario files and versioned flow resources
are derived only from approved structured data.

## Layout

```text
generated/<project-name>/
  pom.xml
  testng.xml
  README.md
  .env.example
  src/test/java/framework/
  src/test/java/generated/clients/
  src/test/java/generated/scenarios/
  src/test/java/generated/listeners/
  src/test/resources/config/
  src/test/resources/recordings/
  src/test/resources/flows/
```

## Core responsibilities

- `Config` reads environment/system configuration and validates the base origin.
- `RequestDefinition` is an immutable request description.
- `RequestExecutor` applies auth, performs the request, and captures a redacted
  diagnostic event.
- `AuthProvider` implementations support none, bearer, basic, API key, cookie,
  and a project-local custom hook without embedding secrets.
- `ScenarioContext` substitutes values produced by previous steps.
- `DynamicValueExtractor` extracts JSON-path values into that context.
- `TestDataFactory` creates non-recorded unique test data.
- `PollingUtility` implements bounded polling with history.
- `AssertionUtility` checks status/content type/required fields/formats.
- `SecretRedactor` sanitizes all diagnostic material.
- The TestNG listener writes the Extent HTML execution report.

## Runtime safeguards

`WEBTEST_BASE_URL` must be an exact member of
`WEBTEST_AUTHORIZED_ORIGINS`. Negative scenarios require a reviewed
non-production name in `WEBTEST_ENVIRONMENT`. Destructive scenarios remain
excluded from the default suite and additionally require
`ALLOW_DESTRUCTIVE_TESTS=true`.
Absolute cross-origin request paths are rejected.

## Assertions

Generated positive assertions use observed statuses, content types, required
example fields, dependency reuse, and follow-up observable state. UUIDs and
timestamps are checked by presence/format rather than exact value. Complete
response bodies are never compared when dynamic values are present.

Negative scenarios retain the valid baseline request and apply one mutation.
When the expected result lacks evidence, the plan carries a review note and the
generator does not invent an executable assertion.

## Reports

Surefire XML is written below `target/surefire-reports/`; the sanitized human
report is written to `target/webtest-report/index.html`. Report events contain
scenario/step, redacted exchange data, expected/actual outcome, extractions,
polling history, duration, status, and failure diagnostics.
