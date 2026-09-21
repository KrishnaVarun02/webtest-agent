# WebTest Agent Chrome extension

This directory contains the Manifest V3 DevTools capture client. It records XHR/fetch calls from one inspected tab, correlates them with safe UI-action observations, sanitizes data before local persistence, exports versioned JSON or HAR, and connects to the local orchestrator for bounded AI exploration, review, and generation.

## Build and test

```bash
cd webtest-agent/extension
npm install
npm run check
```

The unpacked extension is written to `webtest-agent/extension/dist`.

## Load unpacked and record

1. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**, and select `webtest-agent/extension/dist`.
2. Open an authorized HTTP(S) site in a normal Chrome tab.
3. Open DevTools, select **WebTest Agent**, then reload the inspected page as requested by the panel.
4. Enter one or more exact allowed origins, such as `http://localhost:3000`. Optionally enter newline-separated include/exclude globs such as `*/api/*`.
5. Choose **Start**, use the website, inspect the captured operations, and uncheck irrelevant calls.
6. Choose **Stop** and then **Export JSON**, **Export HAR**, or **Review**.

The panel intentionally refuses to start before an allowed origin is configured and the inspected page has been reloaded. A non-production confirmation is shown for non-loopback/non-test hosts.

## Local orchestrator API

The orchestrator URL defaults to `http://127.0.0.1:8000` and is restricted to a loopback hostname. The extension calls:

- `POST /api/v1/explore/next` with a compact accessibility-oriented snapshot, action history, observed API summaries, local test-data *reference names* (never their values), and exploration limits. The response is exactly one structured action or `{ "action": <structured-action> }`.
- `POST /api/v1/review` with the full sanitized `Recording` object described by `schema/recording.v1.schema.json` (`schemaVersion: "1.0.0"`).
- `POST /api/v1/generate` with `{ "recordingId": "...", "approved": true, "approvedPlan": { ... } }` after the user checks the approval box.
- `GET /health` is supported by the client for local diagnostics.

Local AI test-data values stay in the panel and are resolved only when executing a validated `fill` or `select` action. They are not stored and are not sent to the model.

## Bounded AI exploration

AI exploration sends URL, title, headings, visible interactive element references/roles/names/enabled state, visited-page summary, and observed API summaries. It never sends the complete DOM and never executes model-provided JavaScript. Locally enforced limits cover origin, action count, runtime, retry count, repeated states, and scroll/wait size. Element actions must reference the latest snapshot. Navigation must stay on the same origin.

The extension blocks CAPTCHA, payment/purchase, account deletion, file upload, privilege escalation, and authentication-bypass actions. It asks the user before controls likely to create, add, save, update, submit, publish, archive, delete, remove, confirm, approve, register, or sign up. Manual recording works without AI or an LLM connection.

## Permissions

- `devtools_page` and the DevTools network API provide the WebTest Agent panel and completed XHR/fetch request metadata/body access.
- `tabs` lets the DevTools panel send bounded start/snapshot/action messages only to its inspected tab.
- `<all_urls>` is needed because the product is generic. Runtime allowed-origin checks in both the panel and content script deny capture outside the user's explicit whitelist.
- `storage` stores sanitized settings and the latest versioned sanitized recording locally.
- `unlimitedStorage` prevents a longer authorized capture from failing Chrome's small extension storage quota. Capture still has a user-visible maximum of 1,000 calls and 64 KiB per captured body.

Passwords, authorization/cookie headers, API keys, access/refresh tokens, credentials, authentication session IDs, secret-named fields, and sensitive query parameters are redacted before persistence, export, model calls, or generation. Exported HAR includes only calls currently marked **Use**; recording JSON retains sanitized excluded calls plus their reason.

## Version-one boundaries

Supported: Chrome, one inspected tab, DevTools-open capture, same-origin exploration, XHR/fetch, REST, JSON, form-urlencoded request bodies, common browser authentication traffic, JSON/HAR export, and local orchestrator review/generation.

Recorded only or unsupported for semantic automation: WebSockets, SSE, gRPC, protobuf, binary/encrypted bodies, file uploads, multi-tab flows, mobile, CAPTCHA, payments, cross-origin exploration, and arbitrary JavaScript. Static assets and known analytics/telemetry/advertising/tracker calls are excluded by default.
