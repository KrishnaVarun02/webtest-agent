import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { OrchestratorClient } from "../src/panel/orchestrator-client";
import { sanitizeReviewPlan } from "../src/shared/plan-sanitize";

function reviewPlan(): Record<string, unknown> {
  return {
    schemaVersion: "1.0",
    planId: "plan_roundtrip",
    recordingId: "recording_roundtrip",
    revision: 1,
    status: "draft",
    workflows: [
      {
        workflowId: "workflow_login",
        name: "Login workflow",
        approval: "pending",
        setupStepIds: ["step_login"],
        cleanupStepIds: [],
        assumptions: [],
        uncertainties: [],
        destructive: false,
        steps: [
          {
            stepId: "step_login",
            operationId: "operation_login",
            name: "POST /api/login",
            order: 1,
            uiActionIds: ["action_login"],
            dependencies: [],
            extracts: { api_token: "$.accessToken" },
            expectedStatuses: [200],
            stateChanging: true,
            destructive: false,
            asynchronous: false,
            reviewNotes: []
          }
        ],
        scenarios: []
      }
    ],
    apiInventory: [
      {
        operationId: "operation_login",
        method: "POST",
        origin: "http://127.0.0.1:8765",
        normalizedPath: "/api/login",
        resourcePattern: "/api/login",
        pathParameters: [],
        examples: [
          {
            requestId: "request_login",
            timestamp: "2026-09-21T10:00:00.000Z",
            url: "http://127.0.0.1:8765/api/login",
            queryParameters: {},
            requestHeaders: { Authorization: "${API_TOKEN}" },
            requestContentType: "application/json",
            requestBody: { username: "${TEST_USERNAME}", password: "${TEST_PASSWORD}" },
            responseStatus: 200,
            responseHeaders: { "content-type": "application/json" },
            responseBody: { accessToken: "${API_TOKEN}", tokenType: "Bearer" },
            relatedUiActionId: "action_login",
            pageUrl: "http://127.0.0.1:8765/"
          }
        ],
        observedStatuses: [200],
        requestContentTypes: ["application/json"],
        responseContentTypes: ["application/json"],
        relatedUiActionIds: ["action_login"],
        authEvidence: true,
        stateChanging: true,
        asynchronousEvidence: false,
        responseSchema: {
          type: "object",
          properties: {
            accessToken: { type: "string" },
            tokenType: { type: "string" }
          },
          observedRequired: ["accessToken", "tokenType"]
        }
      }
    ],
    assumptions: ["token=seed-plan-secret-must-not-survive"],
    uncertainties: [],
    missingTestData: ["API_TOKEN"],
    suppliedTestData: { API_TOKEN: "seed-supplied-secret-must-not-survive" },
    createdAt: "2026-09-21T10:00:00.000Z",
    updatedAt: "2026-09-21T10:00:00.000Z"
  };
}

describe("review plan-aware sanitization", () => {
  it("preserves extractor JSONPaths and JSON Schema property names without preserving secret values", () => {
    const source = reviewPlan();
    const originalInventory = structuredClone(source.apiInventory);
    const firstPass = sanitizeReviewPlan(source);
    const roundTripped = sanitizeReviewPlan(JSON.parse(JSON.stringify(firstPass)));
    const workflow = (roundTripped.workflows as Array<Record<string, unknown>>)[0]!;
    const step = (workflow.steps as Array<Record<string, unknown>>)[0]!;
    const inventory = (roundTripped.apiInventory as Array<Record<string, unknown>>)[0]!;
    const responseSchema = inventory.responseSchema as Record<string, unknown>;
    const properties = responseSchema.properties as Record<string, unknown>;

    assert.deepEqual(step.extracts, { api_token: "$.accessToken" });
    assert.equal("accessToken" in properties, true);
    assert.equal("tokenType" in properties, true);
    assert.deepEqual(roundTripped.apiInventory, originalInventory);
    assert.deepEqual(roundTripped.suppliedTestData, { API_TOKEN: "${API_TOKEN}" });
    const serialized = JSON.stringify(roundTripped);
    assert.doesNotMatch(serialized, /seed-plan-secret-must-not-survive|seed-supplied-secret-must-not-survive/);
  });

  it("rejects invalid extractor paths and literal secrets in the immutable API inventory", () => {
    const invalidPath = reviewPlan();
    const workflow = (invalidPath.workflows as Array<Record<string, unknown>>)[0]!;
    const step = (workflow.steps as Array<Record<string, unknown>>)[0]!;
    step.extracts = { api_token: "accessToken" };
    assert.throws(() => sanitizeReviewPlan(invalidPath), /structural JSONPath/i);

    const unsafeInventory = reviewPlan();
    const operation = (unsafeInventory.apiInventory as Array<Record<string, unknown>>)[0]!;
    const example = (operation.examples as Array<Record<string, unknown>>)[0]!;
    example.responseBody = { accessToken: "literal-token-value" };
    assert.throws(() => sanitizeReviewPlan(unsafeInventory), /environment reference/i);
  });

  it("round-trips the preserved extractor through the exact Generate request contract", async () => {
    const originalFetch = globalThis.fetch;
    let generatedBody: Record<string, unknown> | undefined;
    globalThis.fetch = async (_input, init) => {
      generatedBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
      return new Response(JSON.stringify({ status: "completed" }), {
        status: 200,
        headers: { "content-type": "application/json" }
      });
    };
    try {
      const plan = sanitizeReviewPlan(JSON.parse(JSON.stringify(sanitizeReviewPlan(reviewPlan()))));
      plan.approved = true;
      await new OrchestratorClient("http://127.0.0.1:8000").generate("recording_roundtrip", plan);
    } finally {
      globalThis.fetch = originalFetch;
    }

    const approvedPlan = generatedBody?.approvedPlan as Record<string, unknown>;
    const workflow = (approvedPlan.workflows as Array<Record<string, unknown>>)[0]!;
    const step = (workflow.steps as Array<Record<string, unknown>>)[0]!;
    assert.deepEqual(step.extracts, { api_token: "$.accessToken" });
    assert.equal(generatedBody?.approved, true);
  });
});
