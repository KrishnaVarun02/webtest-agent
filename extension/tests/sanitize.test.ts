import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { REDACTED, assertSanitized, isSensitiveName, sanitizeBody, sanitizeHeaders, sanitizeUnknown, sanitizeUrl } from "../src/shared/sanitize";

describe("secret sanitization", () => {
  it("detects common sensitive field and header names", () => {
    for (const name of ["Authorization", "x-api-key", "refreshToken", "client_secret", "password", "sessionId", "credential"]) {
      assert.equal(isSensitiveName(name), true, name);
    }
    assert.equal(isSensitiveName("monkeyCount"), false);
  });

  it("removes secrets from URLs, headers, and nested JSON", () => {
    const output = {
      url: sanitizeUrl("https://example.test/session/path-secret?access_token=url-secret&safe=yes"),
      headers: sanitizeHeaders([
        { name: "Authorization", value: "Bearer bearer-secret" },
        { name: "Cookie", value: "sid=cookie-secret" },
        { name: "x-note", value: "token=embedded-secret" }
      ]),
      body: sanitizeBody('{"password":"password-secret","nested":{"apiKey":"key-secret"},"safe":"visible"}', "application/json")
    };
    assertSanitized(output, ["path-secret", "url-secret", "bearer-secret", "cookie-secret", "embedded-secret", "password-secret", "key-secret"]);
    assert.match(JSON.stringify(output), new RegExp(REDACTED.replace(/[\[\]]/g, "\\$&")));
    assert.match(JSON.stringify(output), /visible/);
  });

  it("preserves environment references while redacting literal secret fields", () => {
    assert.deepEqual(sanitizeUnknown({ password: "${TEST_PASSWORD}", token: "literal-secret" }), {
      password: "${TEST_PASSWORD}",
      token: REDACTED
    });
  });

  it("sanitizes form-urlencoded bodies", () => {
    assert.deepEqual(sanitizeBody("username=tester&password=seeded&count=2", "application/x-www-form-urlencoded"), {
      username: "tester",
      password: REDACTED,
      count: "2"
    });
  });
});
