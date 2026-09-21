import { stableHash } from "./ids";
import type { AiAction, ModelSnapshot } from "./schema";

const PROHIBITED = /(?:captcha|purchase|checkout|payment|pay now|buy now|delete account|close account|remove account|\bupload\b|become admin|elevate privilege|authentication bypass|bypass auth)/i;
const STATE_CHANGE = /(?:create|add|save|update|submit|send|publish|archive|delete|remove|confirm|approve|register|sign up)/i;

function assertExactKeys(value: Record<string, unknown>, required: string[], optional: string[] = []): void {
  const keys = Object.keys(value);
  for (const key of required) if (!(key in value)) throw new Error(`AI action is missing '${key}'.`);
  const allowed = new Set([...required, ...optional]);
  const extra = keys.find((key) => !allowed.has(key));
  if (extra) throw new Error(`AI action contains unsupported field '${extra}'.`);
}

function objectValue(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("AI response must be exactly one action object.");
  const record = value as Record<string, unknown>;
  if (record.action && typeof record.action === "object" && !Array.isArray(record.action) && Object.keys(record).length === 1) {
    return record.action as Record<string, unknown>;
  }
  return record;
}

export function validateAiAction(
  input: unknown,
  currentUrl: string,
  validElementRefs: Set<string>,
  validDataRefs: Set<string>
): AiAction {
  const value = objectValue(input);
  const type = value.type;
  if (typeof type !== "string") throw new Error("AI action type must be a string.");
  if (type === "click") {
    assertExactKeys(value, ["type", "elementRef"]);
    if (typeof value.elementRef !== "string" || !validElementRefs.has(value.elementRef)) throw new Error("AI selected an unknown element reference.");
    return { type, elementRef: value.elementRef };
  }
  if (type === "fill" || type === "select") {
    assertExactKeys(value, ["type", "elementRef", "valueRef"]);
    if (typeof value.elementRef !== "string" || !validElementRefs.has(value.elementRef)) throw new Error("AI selected an unknown element reference.");
    if (typeof value.valueRef !== "string" || !validDataRefs.has(value.valueRef)) throw new Error("AI selected an unknown local test-data reference.");
    return { type, elementRef: value.elementRef, valueRef: value.valueRef };
  }
  if (type === "scroll") {
    assertExactKeys(value, ["type", "direction"], ["amount"]);
    if (value.direction !== "up" && value.direction !== "down") throw new Error("Scroll direction must be up or down.");
    if (value.amount !== undefined && (typeof value.amount !== "number" || value.amount <= 0 || value.amount > 1_500)) {
      throw new Error("Scroll amount is outside the allowed range.");
    }
    return { type, direction: value.direction, ...(typeof value.amount === "number" ? { amount: value.amount } : {}) };
  }
  if (type === "wait") {
    assertExactKeys(value, ["type", "durationMs"]);
    if (typeof value.durationMs !== "number" || !Number.isInteger(value.durationMs) || value.durationMs < 0 || value.durationMs > 10_000) {
      throw new Error("Wait duration must be an integer from 0 to 10000 ms.");
    }
    return { type, durationMs: value.durationMs };
  }
  if (type === "back") {
    assertExactKeys(value, ["type"]);
    return { type };
  }
  if (type === "navigate") {
    assertExactKeys(value, ["type", "url"]);
    if (typeof value.url !== "string") throw new Error("Navigate action requires a URL.");
    const current = new URL(currentUrl);
    const destination = new URL(value.url, current);
    if (destination.origin !== current.origin) throw new Error("AI navigation must remain on the same origin.");
    if (PROHIBITED.test(destination.href)) throw new Error("AI navigation targets a prohibited flow.");
    return { type, url: destination.href };
  }
  if (type === "stop") {
    assertExactKeys(value, ["type"], ["reason"]);
    if (value.reason !== undefined && typeof value.reason !== "string") throw new Error("Stop reason must be a string.");
    return { type, ...(typeof value.reason === "string" ? { reason: value.reason.slice(0, 300) } : {}) };
  }
  throw new Error(`Unsupported AI action '${type}'.`);
}

export function prohibitedActionReason(action: AiAction, snapshot: ModelSnapshot): string | undefined {
  const elementRef = "elementRef" in action ? action.elementRef : undefined;
  const element = snapshot.interactiveElements.find((candidate) => candidate.ref === elementRef);
  const description = `${element?.role ?? ""} ${element?.name ?? ""} ${action.type === "navigate" ? action.url : ""}`;
  return PROHIBITED.test(description) ? "CAPTCHA, payments, account deletion, file upload, privilege escalation, and authentication bypass are prohibited." : undefined;
}

export function requiresStateChangeApproval(action: AiAction, snapshot: ModelSnapshot): boolean {
  if (action.type !== "click") return false;
  const element = snapshot.interactiveElements.find((candidate) => candidate.ref === action.elementRef);
  return STATE_CHANGE.test(`${element?.role ?? ""} ${element?.name ?? ""}`);
}

export function snapshotStateHash(snapshot: ModelSnapshot): string {
  return stableHash(
    JSON.stringify({
      currentUrl: snapshot.currentUrl,
      title: snapshot.title,
      headings: snapshot.headings,
      interactiveElements: snapshot.interactiveElements,
      observedApis: snapshot.observedApis
    })
  );
}
