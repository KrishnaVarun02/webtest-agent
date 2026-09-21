import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { shouldCapture, toCapturedOperation, type HarEntryLike } from "../src/shared/capture";
import { recordingToHar } from "../src/shared/har";
import { assertSanitized, REDACTED } from "../src/shared/sanitize";
import { EXTENSION_VERSION, RECORDING_SCHEMA_VERSION, type CaptureConfiguration, type Recording } from "../src/shared/schema";

const fixture = JSON.parse(
  readFileSync(fileURLToPath(new URL("./fixtures/fetch-entry.json", import.meta.url)), "utf8")
) as HarEntryLike;
const configuration: CaptureConfiguration = {
  allowedOrigins: ["http://localhost:3000"],
  includePatterns: ["*/api/*"],
  excludePatterns: [],
  maxOperations: 250
};
const secrets = [
  "seed-access-123",
  "seed-bearer-456",
  "seed-api-key-789",
  "seed-cookie-321",
  "seed-password-654",
  "seed-client-secret-987",
  "seed-set-cookie-111",
  "seed-refresh-secret-222"
];

describe("fixture-based DevTools capture", () => {
  it("captures an authorized fetch and correlates it to the latest action", () => {
    assert.equal(shouldCapture(fixture, configuration), true);
    const operation = toCapturedOperation(fixture, {
      sessionId: "recording_fixture",
      pageUrl: "http://localhost:3000/users?token=page-secret",
      relatedActionId: "action_create_user",
      configuration,
      responseText: '{"id":123,"name":"Ada","refreshToken":"seed-refresh-secret-222"}'
    });
    assert.equal(operation.relatedActionId, "action_create_user");
    assert.equal(operation.request.normalizedPath, "/api/users/{userId}");
    assert.deepEqual(operation.request.query, [
      { name: "access_token", value: REDACTED },
      { name: "expand", value: "teams" }
    ]);
    assert.equal(operation.response.status, 201);
    assert.equal(operation.included, true);
    assertSanitized(operation, [...secrets, "page-secret"]);
  });

  it("does not capture non-XHR resources or unauthorized origins", () => {
    const documentEntry = structuredClone(fixture);
    documentEntry._resourceType = "document";
    assert.equal(shouldCapture(documentEntry, configuration), false);
    const unauthorized = structuredClone(fixture);
    unauthorized.request.url = "https://unrelated.example/api/users/123";
    assert.equal(shouldCapture(unauthorized, configuration), false);
  });

  it("exports a sanitized HAR containing only included operations", () => {
    const included = toCapturedOperation(fixture, {
      sessionId: "recording_fixture",
      pageUrl: "http://localhost:3000/users",
      relatedActionId: "action_create_user",
      configuration,
      responseText: '{"id":123,"refreshToken":"seed-refresh-secret-222"}'
    });
    const excluded = structuredClone(included);
    excluded.id = "operation_excluded";
    excluded.included = false;
    excluded.exclusionReason = "user-excluded";
    const recording: Recording = {
      schemaVersion: RECORDING_SCHEMA_VERSION,
      product: "WebTest Agent",
      sessionId: "recording_fixture",
      inspectedTabId: 7,
      startedAt: "2026-01-10T12:00:00.000Z",
      configuration,
      actions: [],
      operations: [included, excluded],
      metadata: {
        extensionVersion: EXTENSION_VERSION,
        captureScope: "one-inspected-tab",
        protocols: ["REST"],
        formats: ["JSON", "form-urlencoded"],
        reloadObserved: true
      }
    };
    const har = recordingToHar(recording);
    assert.equal((har.log as { entries: unknown[] }).entries.length, 1);
    assertSanitized(har, secrets);
  });
});
