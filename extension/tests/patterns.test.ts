import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { defaultExclusion, isAllowedUrl, matchesPattern, normalizeAllowedOrigins, normalizePath, passesUrlPatterns } from "../src/shared/patterns";

describe("URL scope and normalization", () => {
  it("normalizes dynamic identifiers without changing API versions", () => {
    assert.equal(normalizePath("https://example.test/api/v1/users/123/orders/550e8400-e29b-41d4-a716-446655440000"),
      "/api/v1/users/{userId}/orders/{orderId}"
    );
    assert.equal(normalizePath("https://example.test/reports/2026-09-21"), "/reports/{date}");
    assert.equal(normalizePath("https://example.test/reset/token/short-secret"), "/reset/token/{secret}");
  });

  it("enforces exact origins and include/exclude patterns", () => {
    const origins = normalizeAllowedOrigins(["https://example.test/path", "http://localhost:3000", "javascript:alert(1)"]);
    assert.deepEqual(origins, ["http://localhost:3000", "https://example.test"]);
    assert.equal(isAllowedUrl("http://localhost:3000/api/users", origins), true);
    assert.equal(isAllowedUrl("http://localhost:3001/api/users", origins), false);
    assert.equal(matchesPattern("/api/users?active=true", "/api/*"), true);
    assert.equal(matchesPattern("http://localhost:3000/api/users", "/api/"), true);
    assert.equal(passesUrlPatterns("http://localhost:3000/api/users", ["*/api/*"], ["*/analytics/*"]), true);
    assert.equal(passesUrlPatterns("http://localhost:3000/api/analytics/events", ["*/api/*"], ["*/analytics/*"]), false);
  });

  it("classifies traffic that should be excluded by default", () => {
    assert.equal(defaultExclusion("https://example.test/api/telemetry/events", "application/json"), "telemetry");
    assert.equal(defaultExclusion("https://example.test/assets/logo.png", "image/png"), "static-resource");
    assert.equal(defaultExclusion("https://example.test/api/users", "application/json"), undefined);
  });
});
