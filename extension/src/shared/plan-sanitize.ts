import { isSensitiveName, redactText, REDACTED, sanitizeUnknown } from "./sanitize";
import type { JsonValue } from "./schema";

type JsonObject = { [key: string]: JsonValue };

const ENV_REFERENCE = /^\$\{[A-Z][A-Z0-9_]*\}$/;
const SAFE_SECRET_VALUE = /^(?:\[REDACTED]|\$\{REDACTED\}|\$\{[A-Z][A-Z0-9_]*\}|(?:Bearer|Basic)\s+\$\{[A-Z][A-Z0-9_]*\})$/i;
const EXTRACT_VARIABLE = /^[A-Za-z_][A-Za-z0-9_]{0,127}$/;
const STRUCTURAL_JSON_PATH = /^\$(?:(?:\.[A-Za-z_][A-Za-z0-9_]*)|(?:\[[0-9]+\])|(?:\["(?:[^"\\]|\\.)+"\]))*$/;
const NON_SECRET_METADATA_SUFFIX = /(?:type|format|name|length|present|expires|expiry|expiration|ttl)$/i;
const SCHEMA_MAP_KEYWORDS = new Set(["properties", "patternProperties", "$defs", "definitions", "dependentSchemas"]);
const SCHEMA_PROPERTY_LISTS = new Set(["required", "observedRequired"]);
const SCHEMA_LITERAL_KEYWORDS = new Set(["const", "default", "enum", "examples", "example"]);

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function planError(path: string, message: string): Error {
  return new Error(`Review plan ${path}: ${message}`);
}

function isSecretBearingName(name: string): boolean {
  if (!isSensitiveName(name)) return false;
  const compact = name.replace(/[^A-Za-z0-9]/g, "");
  return !NON_SECRET_METADATA_SUFFIX.test(compact);
}

function safeReferenceFor(name: string): string {
  if (ENV_REFERENCE.test(name)) return name;
  const upper = name.toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  if (/PASS/.test(upper)) return "${TEST_PASSWORD}";
  if (/(?:COOKIE|SESSION)/.test(upper)) return "${SESSION_COOKIE}";
  if (/CREDENTIAL/.test(upper)) return "${CREDENTIAL}";
  if (EXTRACT_VARIABLE.test(upper) && upper.length <= 64) return `\${${upper}}`;
  return "${API_TOKEN}";
}

function assertStructuralName(value: unknown, path: string): asserts value is string {
  if (typeof value !== "string" || value.length === 0 || value.length > 512 || /[\u0000-\u001f]/.test(value)) {
    throw planError(path, "contains an invalid structural property name");
  }
}

function cloneJson(value: unknown, path: string, depth = 0): JsonValue {
  if (depth > 60) throw planError(path, "exceeds the maximum nesting depth");
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw planError(path, "contains a non-finite number");
    return value;
  }
  if (Array.isArray(value)) {
    if (value.length > 10_000) throw planError(path, "contains too many array items");
    return value.map((entry, index) => cloneJson(entry, `${path}[${index}]`, depth + 1));
  }
  if (!isObject(value)) throw planError(path, "must contain only JSON-compatible values");
  const entries = Object.entries(value);
  if (entries.length > 10_000) throw planError(path, "contains too many object properties");
  return Object.fromEntries(
    entries.map(([key, entry]) => {
      assertStructuralName(key, `${path}.${key}`);
      return [key, cloneJson(entry, `${path}.${key}`, depth + 1)];
    })
  ) as JsonObject;
}

function assertSafeString(value: string, path: string): void {
  if (redactText(value) !== value) throw planError(path, "contains an unredacted secret-like value");
}

function assertSafeSchema(value: unknown, path: string, propertyName?: string, depth = 0): void {
  if (depth > 60) throw planError(path, "schema exceeds the maximum nesting depth");
  if (value === null || typeof value === "boolean" || typeof value === "number") return;
  if (typeof value === "string") {
    assertSafeString(value, path);
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((entry, index) => assertSafeSchema(entry, `${path}[${index}]`, propertyName, depth + 1));
    return;
  }
  if (!isObject(value)) throw planError(path, "schema must be JSON-compatible");

  for (const [keyword, entry] of Object.entries(value)) {
    if (SCHEMA_MAP_KEYWORDS.has(keyword)) {
      if (!isObject(entry)) throw planError(`${path}.${keyword}`, "must be an object");
      for (const [structuralName, childSchema] of Object.entries(entry)) {
        assertStructuralName(structuralName, `${path}.${keyword}.${structuralName}`);
        assertSafeSchema(childSchema, `${path}.${keyword}.${structuralName}`, structuralName, depth + 1);
      }
      continue;
    }
    if (SCHEMA_PROPERTY_LISTS.has(keyword)) {
      if (!Array.isArray(entry)) throw planError(`${path}.${keyword}`, "must be an array of property names");
      for (const [index, name] of entry.entries()) assertStructuralName(name, `${path}.${keyword}[${index}]`);
      continue;
    }
    if (SCHEMA_LITERAL_KEYWORDS.has(keyword) && propertyName && isSecretBearingName(propertyName)) {
      assertSafePlanValue(entry, `${path}.${keyword}`, propertyName, depth + 1);
      continue;
    }
    assertSafeSchema(entry, `${path}.${keyword}`, propertyName, depth + 1);
  }
}

function assertSafePlanValue(value: unknown, path: string, keyHint = "", depth = 0): void {
  if (depth > 60) throw planError(path, "exceeds the maximum nesting depth");
  if (keyHint && isSecretBearingName(keyHint)) {
    if (value === null || value === "") return;
    if (typeof value !== "string" || !SAFE_SECRET_VALUE.test(value.trim())) {
      throw planError(path, "contains a literal secret where an environment reference is required");
    }
    return;
  }
  if (value === null || typeof value === "boolean" || typeof value === "number") return;
  if (typeof value === "string") {
    assertSafeString(value, path);
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((entry, index) => assertSafePlanValue(entry, `${path}[${index}]`, "", depth + 1));
    return;
  }
  if (!isObject(value)) throw planError(path, "must contain only JSON-compatible values");
  for (const [key, entry] of Object.entries(value)) {
    if (/schema$/i.test(key)) assertSafeSchema(entry, `${path}.${key}`, undefined, depth + 1);
    else assertSafePlanValue(entry, `${path}.${key}`, key, depth + 1);
  }
}

function validatedExtracts(value: unknown, path: string): JsonObject {
  if (!isObject(value)) throw planError(path, "must be an object of variable names and JSONPaths");
  const entries = Object.entries(value).map(([name, jsonPath]) => {
    if (!EXTRACT_VARIABLE.test(name)) throw planError(`${path}.${name}`, "has an invalid extraction variable name");
    if (typeof jsonPath !== "string" || jsonPath.length > 512 || !STRUCTURAL_JSON_PATH.test(jsonPath)) {
      throw planError(`${path}.${name}`, "must be a structural JSONPath");
    }
    return [name, jsonPath] as const;
  });
  return Object.fromEntries(entries) as JsonObject;
}

function sanitizeSuppliedTestData(value: unknown, path: string): JsonObject {
  if (!isObject(value)) throw planError(path, "must be an object");
  return Object.fromEntries(
    Object.entries(value).map(([name, supplied]) => {
      if (!EXTRACT_VARIABLE.test(name)) throw planError(`${path}.${name}`, "has an invalid test-data reference name");
      if (typeof supplied !== "string") throw planError(`${path}.${name}`, "must be a string or environment reference");
      if (isSecretBearingName(name)) return [name, ENV_REFERENCE.test(supplied.trim()) ? supplied.trim() : safeReferenceFor(name)];
      return [name, redactText(supplied)];
    })
  ) as JsonObject;
}

function requiredString(plan: Record<string, unknown>, key: string): string {
  const value = plan[key];
  if (typeof value !== "string" || !value.trim()) throw planError(`$.${key}`, "must be a non-empty string");
  return value;
}

/**
 * Sanitizes editable review-plan values without confusing structural metadata
 * (extractor names, JSONPaths, or JSON Schema property names) with credentials.
 * The immutable API inventory is validated as already-redacted and preserved
 * byte-for-byte so Review -> Generate cannot corrupt observed evidence.
 */
export function sanitizeReviewPlan(input: unknown): JsonObject {
  if (!isObject(input)) throw planError("$", "must be an object");
  if (requiredString(input, "schemaVersion") !== "1.0") throw planError("$.schemaVersion", "must equal '1.0'");
  requiredString(input, "planId");
  requiredString(input, "recordingId");
  if (!Array.isArray(input.workflows)) throw planError("$.workflows", "must be an array");
  if (!Array.isArray(input.apiInventory)) throw planError("$.apiInventory", "must be an array");

  const inventory = cloneJson(input.apiInventory, "$.apiInventory");
  assertSafePlanValue(inventory, "$.apiInventory");
  const generic = sanitizeUnknown(input) as JsonObject;
  generic.apiInventory = inventory;

  const safeWorkflows = generic.workflows;
  if (!Array.isArray(safeWorkflows)) throw planError("$.workflows", "was corrupted during sanitization");
  input.workflows.forEach((workflow, workflowIndex) => {
    if (!isObject(workflow) || !Array.isArray(workflow.steps)) {
      throw planError(`$.workflows[${workflowIndex}].steps`, "must be an array");
    }
    const safeWorkflow = safeWorkflows[workflowIndex];
    if (!isObject(safeWorkflow) || !Array.isArray(safeWorkflow.steps)) {
      throw planError(`$.workflows[${workflowIndex}]`, "was corrupted during sanitization");
    }
    const safeSteps = safeWorkflow.steps;
    workflow.steps.forEach((step, stepIndex) => {
      if (!isObject(step)) throw planError(`$.workflows[${workflowIndex}].steps[${stepIndex}]`, "must be an object");
      const safeStep = safeSteps[stepIndex];
      if (!isObject(safeStep)) throw planError(`$.workflows[${workflowIndex}].steps[${stepIndex}]`, "was corrupted during sanitization");
      safeStep.extracts = validatedExtracts(step.extracts ?? {}, `$.workflows[${workflowIndex}].steps[${stepIndex}].extracts`);
    });
  });

  if (input.suppliedTestData !== undefined) {
    generic.suppliedTestData = sanitizeSuppliedTestData(input.suppliedTestData, "$.suppliedTestData");
  }
  return generic;
}

export function isSafePlanSecretValue(value: string): boolean {
  return value === REDACTED || SAFE_SECRET_VALUE.test(value.trim());
}
