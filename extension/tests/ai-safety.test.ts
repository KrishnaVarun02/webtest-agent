import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { prohibitedActionReason, requiresStateChangeApproval, snapshotStateHash, validateAiAction } from "../src/shared/ai-safety";
import type { ModelSnapshot } from "../src/shared/schema";

const snapshot: ModelSnapshot = {
  currentUrl: "https://app.example.test/records",
  title: "Records",
  headings: ["Records"],
  interactiveElements: [
    { ref: "el_create", role: "button", name: "Create record", enabled: true },
    { ref: "el_name", role: "textbox", name: "Record name", enabled: true },
    { ref: "el_pay", role: "button", name: "Pay now", enabled: true }
  ],
  visitedPageSummary: [],
  observedApis: []
};

describe("bounded AI action validation", () => {
  it("accepts a structured action that references the supplied snapshot", () => {
    assert.deepEqual(validateAiAction({ type: "fill", elementRef: "el_name", valueRef: "RECORD_NAME" }, snapshot.currentUrl, new Set(["el_name"]), new Set(["RECORD_NAME"])), {
      type: "fill",
      elementRef: "el_name",
      valueRef: "RECORD_NAME"
    });
  });

  it("rejects arbitrary fields, unknown references, and cross-origin navigation", () => {
    assert.throws(() => validateAiAction({ type: "click", elementRef: "el_name", javascript: "alert(1)" }, snapshot.currentUrl, new Set(["el_name"]), new Set()), /unsupported field/i);
    assert.throws(() => validateAiAction({ type: "click", elementRef: "missing" }, snapshot.currentUrl, new Set(["el_name"]), new Set()), /unknown element/i);
    assert.throws(() => validateAiAction({ type: "navigate", url: "https://evil.example/" }, snapshot.currentUrl, new Set(), new Set()), /same origin/i);
  });

  it("blocks prohibited flows and flags server-state actions for approval", () => {
    assert.match(prohibitedActionReason({ type: "click", elementRef: "el_pay" }, snapshot) ?? "", /prohibited/i);
    assert.equal(requiresStateChangeApproval({ type: "click", elementRef: "el_create" }, snapshot), true);
    assert.equal(requiresStateChangeApproval({ type: "click", elementRef: "el_name" }, snapshot), false);
  });

  it("creates stable repeated-state hashes", () => {
    assert.equal(snapshotStateHash(snapshot), snapshotStateHash(structuredClone(snapshot)));
    assert.notEqual(snapshotStateHash({ ...snapshot, title: "Changed" }), snapshotStateHash(snapshot));
  });
});
