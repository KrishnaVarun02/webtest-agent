# Recording schema

Recordings are versioned JSON documents. Version 1 describes one inspected
Chrome tab and is intentionally limited to UI actions plus XHR/fetch traffic.
Export always passes through the extension redactor; the orchestrator validates
and redacts the document again before persistence.

## Top-level shape

```json
{
  "schemaVersion": "1.0.0",
  "product": "WebTest Agent",
  "sessionId": "rec_<stable-random-id>",
  "inspectedTabId": 42,
  "startedAt": "2026-09-21T10:00:00.000Z",
  "endedAt": "2026-09-21T10:02:00.000Z",
  "configuration": {
    "allowedOrigins": ["http://127.0.0.1:8765"],
    "includePatterns": ["/api/"],
    "excludePatterns": ["analytics", "telemetry"],
    "maxOperations": 1000
  },
  "actions": [],
  "operations": [],
  "metadata": {
    "extensionVersion": "0.1.0",
    "captureScope": "one-inspected-tab",
    "protocols": ["REST"],
    "formats": ["JSON", "form-urlencoded"],
    "reloadObserved": true
  }
}
```

IDs are opaque stable identifiers within one recording. Timestamps use UTC
ISO-8601 strings. An absent response body is represented as unavailable, not
as an empty successful response.

## UI action

Each action records its ID, session ID, type, timestamp, page URL, its highest
priority safe locator candidate, and a redacted value reference if applicable. Supported
types are click, input, select, navigation, submit, back, wait, and page change.
Locator candidates are ordered by testing attribute, role/name, associated
label, stable ID, then stable CSS.

Password and secret-like inputs never include the entered value. They contain
an environment reference such as `${TEST_PASSWORD}`. Input events are
coalesced so typing does not create a secret-bearing keystroke log.

## Captured operation

An operation contains an `id`, `sessionId`, capture metadata, nested `request`
and `response` objects, and:

- operation/request ID and session ID;
- method, full URL, normalized path, and parsed query parameters;
- sanitized request headers, content type, and parsed or textual body;
- response status, sanitized headers, and body/availability metadata;
- page URL, timestamp, and DevTools timing data;
- the most recent eligible UI action ID;
- inclusion/exclusion state and the reason for automatic classification.

The full URL is sanitized. Sensitive query values are never retained. Binary
body metadata can be recorded as unsupported, but binary bytes are not stored.

## Normalization

The orchestrator converts observed IDs in equivalent paths into named
parameters, for example `/api/records/2a...` and `/api/records/7b...` become
`/api/records/{recordId}`. It deduplicates method/path pairs while retaining
distinct payload/status examples needed to support scenario evidence.

## HAR compatibility

HAR export uses a standard `log.entries` envelope for captured operations and
adds WebTest Agent IDs under `_webTestAgent`. Content unavailable through the
DevTools response-content callback is marked unavailable. HAR export has the
same redaction guarantees as recording JSON.

## Unsupported traffic

WebSocket, SSE, gRPC/protobuf, binary, file-upload, and encrypted-payload
traffic is inventoried with a reason when observable. Version 1 does not infer
semantic tests for it.
