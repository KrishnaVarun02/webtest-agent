import type { HeaderValue, JsonValue, QueryParameter } from "./schema";

export const REDACTED = "[REDACTED]";
export const MAX_CAPTURED_BODY_CHARS = 65_536;

const SENSITIVE_NAME = /(?:^|[-_.])(authorization|proxy[-_]?authorization|cookie|set[-_]?cookie|api[-_]?key|access[-_]?token|refresh[-_]?token|token|secret|pass(?:word|wd)?|credential|session(?:id)?|jwt|client[-_]?secret|private[-_]?key)(?:$|[-_.])/i;
const SENSITIVE_QUERY_NAME = /^(?:code|auth|signature|sig)$/i;
const JWT = /\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b/g;
const AUTH_VALUE = /\b(?:Bearer|Basic)\s+[A-Za-z0-9+/=._~-]{6,}/gi;
const ASSIGNMENT_SECRET = /((?:token|secret|password|passwd|api[_-]?key|session[_-]?id|credential)\s*[=:]\s*)[^\s,;&]+/gi;

export function isSensitiveName(name: string): boolean {
  const normalized = name.trim().replace(/([a-z])([A-Z])/g, "$1-$2");
  return SENSITIVE_NAME.test(normalized) || SENSITIVE_QUERY_NAME.test(normalized);
}

export function redactText(value: string): string {
  return value
    .replace(JWT, REDACTED)
    .replace(AUTH_VALUE, REDACTED)
    .replace(ASSIGNMENT_SECRET, `$1${REDACTED}`);
}

export function sanitizeUrl(rawUrl: string): string {
  try {
    const url = new URL(rawUrl);
    for (const [name] of [...url.searchParams.entries()]) {
      if (isSensitiveName(name)) url.searchParams.set(name, REDACTED);
    }
    const pathSegments = url.pathname.split("/");
    for (let index = 1; index < pathSegments.length; index += 1) {
      const previous = decodeURIComponent(pathSegments[index - 1] ?? "");
      const current = decodeURIComponent(pathSegments[index] ?? "");
      if (isSensitiveName(previous) || redactText(current) !== current) pathSegments[index] = REDACTED;
    }
    url.pathname = pathSegments.join("/");
    url.username = "";
    url.password = "";
    return redactText(url.toString());
  } catch {
    return redactText(rawUrl);
  }
}

export function sanitizeHeaders(
  headers: HeaderValue[] | Record<string, string | string[] | undefined> | undefined
): HeaderValue[] {
  if (!headers) return [];
  const pairs: HeaderValue[] = Array.isArray(headers)
    ? headers.map(({ name, value }) => ({ name: String(name), value: String(value) }))
    : Object.entries(headers).flatMap(([name, rawValue]) => {
        if (rawValue === undefined) return [];
        return [{ name, value: Array.isArray(rawValue) ? rawValue.join(", ") : rawValue }];
      });

  return pairs.map(({ name, value }) => ({
    name: name.toLowerCase(),
    value: isSensitiveName(name) ? REDACTED : redactText(value)
  }));
}

export function sanitizeUnknown(value: unknown, keyHint = "", depth = 0): JsonValue {
  if (isSensitiveName(keyHint)) {
    if (typeof value === "string" && /^\$\{[A-Z][A-Z0-9_]*\}$/.test(value)) return value;
    return REDACTED;
  }
  if (depth > 20) return "[MAX_DEPTH]";
  if (value === null || typeof value === "boolean" || typeof value === "number") return value;
  if (typeof value === "string") return redactText(value).slice(0, MAX_CAPTURED_BODY_CHARS);
  if (Array.isArray(value)) return value.slice(0, 1_000).map((entry) => sanitizeUnknown(entry, "", depth + 1));
  if (typeof value === "object") {
    const sanitized: Record<string, JsonValue> = {};
    for (const [key, entry] of Object.entries(value as Record<string, unknown>).slice(0, 1_000)) {
      sanitized[key] = sanitizeUnknown(entry, key, depth + 1);
    }
    return sanitized;
  }
  return String(value);
}

export function sanitizeBody(body: string | undefined, contentType = ""): JsonValue | undefined {
  if (!body) return undefined;
  const limited = body.slice(0, MAX_CAPTURED_BODY_CHARS);
  const type = contentType.toLowerCase();
  if (type.includes("json") || /^[\s]*[{[]/.test(limited)) {
    try {
      return sanitizeUnknown(JSON.parse(limited));
    } catch {
      return redactText(limited);
    }
  }
  if (type.includes("application/x-www-form-urlencoded")) {
    const params = new URLSearchParams(limited);
    const result: Record<string, JsonValue> = {};
    for (const [name, value] of params) {
      result[name] = isSensitiveName(name) ? REDACTED : redactText(value);
    }
    return result;
  }
  return redactText(limited);
}

export function sanitizedQuery(rawUrl: string): QueryParameter[] {
  try {
    const url = new URL(rawUrl);
    return [...url.searchParams.entries()].map(([name, value]) => ({
      name,
      value: isSensitiveName(name) ? REDACTED : redactText(value)
    }));
  } catch {
    return [];
  }
}

export function assertSanitized(value: unknown, seededSecrets: string[]): void {
  const serialized = JSON.stringify(value);
  const leaked = seededSecrets.find((secret) => secret && serialized.includes(secret));
  if (leaked) throw new Error("Sanitization invariant failed: a seeded secret remains in the payload");
}
