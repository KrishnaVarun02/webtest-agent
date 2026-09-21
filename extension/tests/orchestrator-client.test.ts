import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { OrchestratorClient } from "../src/panel/orchestrator-client";
import { EXTENSION_VERSION, RECORDING_SCHEMA_VERSION, type ExplorationRequest, type Recording } from "../src/shared/schema";

const recording: Recording = {
  schemaVersion: RECORDING_SCHEMA_VERSION,
  product: "WebTest Agent",
  sessionId: "recording_contract",
  inspectedTabId: 1,
  startedAt: "2026-09-21T10:00:00.000Z",
  configuration: { allowedOrigins: ["https://app.example.test"], includePatterns: [], excludePatterns: [], maxOperations: 1000 },
  actions: [],
  operations: [],
  metadata: {
    extensionVersion: EXTENSION_VERSION,
    captureScope: "one-inspected-tab",
    protocols: ["REST"],
    formats: ["JSON", "form-urlencoded"],
    reloadObserved: true
  }
};

const exploration: ExplorationRequest = {
  schemaVersion: "1.0.0",
  snapshot: {
    currentUrl: "https://app.example.test/login",
    title: "Login",
    headings: ["Login"],
    interactiveElements: [{ ref: "username", role: "textbox", name: "Username", enabled: true }],
    visitedPageSummary: [],
    observedApis: []
  },
  history: [],
  observedApis: [],
  availableTestDataRefs: ["TEST_USERNAME"],
  limits: { maxActions: 5, maxRuntimeMs: 5_000, maxRetries: 2, maxRepeatedStates: 2 }
};

describe("local orchestrator HTTP contract", () => {
  it("rejects credentialed and non-loopback orchestrator URLs", () => {
    assert.throws(() => new OrchestratorClient("https://orchestrator.example.test"), /local loopback/i);
    assert.throws(() => new OrchestratorClient("http://user:secret@127.0.0.1:8000"), /credentials/i);
  });

  it("uses the exact exploration, review, generation, and health routes", async () => {
    const originalFetch = globalThis.fetch;
    const requests: Array<{ path: string; method: string; body?: unknown }> = [];
    globalThis.fetch = async (input, init) => {
      const url = new URL(String(input));
      requests.push({
        path: url.pathname,
        method: init?.method ?? "GET",
        ...(typeof init?.body === "string" ? { body: JSON.parse(init.body) } : {})
      });
      const payload =
        url.pathname.endsWith("/explore/next")
          ? { type: "fill", elementRef: "username", valueRef: "TEST_USERNAME" }
          : url.pathname.endsWith("/review")
            ? { plan: { planId: "plan_contract", status: "draft" }, warnings: [] }
            : url.pathname.endsWith("/generate")
              ? { status: "completed", projectPath: "/tmp/generated" }
              : { status: "ok" };
      return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
    };

    try {
      const client = new OrchestratorClient("http://127.0.0.1:8000/");
      await client.health();
      await client.nextAction(exploration);
      await client.review(recording);
      await client.generate(recording.sessionId, { planId: "plan_contract", approved: true });
    } finally {
      globalThis.fetch = originalFetch;
    }

    assert.deepEqual(requests.map(({ path, method }) => ({ path, method })), [
      { path: "/health", method: "GET" },
      { path: "/api/v1/explore/next", method: "POST" },
      { path: "/api/v1/review", method: "POST" },
      { path: "/api/v1/generate", method: "POST" }
    ]);
    assert.deepEqual(requests[1]?.body, exploration);
    assert.deepEqual(requests[2]?.body, recording);
    assert.deepEqual(requests[3]?.body, {
      recordingId: "recording_contract",
      approved: true,
      approvedPlan: { planId: "plan_contract", approved: true }
    });
  });
});
