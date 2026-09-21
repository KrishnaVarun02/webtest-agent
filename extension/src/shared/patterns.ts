import type { ExclusionCategory } from "./schema";
import { isSensitiveName } from "./sanitize";

const DYNAMIC_SEGMENT = /^(?:\d{1,20}|[0-9a-f]{8}-[0-9a-f-]{27,}|[0-9a-f]{16,}|[A-Za-z0-9_-]{24,})$/i;
const DATE_SEGMENT = /^\d{4}-\d{2}-\d{2}(?:T.*)?$/;
const STATIC_EXTENSION = /\.(?:avif|bmp|css|eot|gif|ico|jpe?g|js|map|mp3|mp4|ogg|otf|pdf|png|svg|ttf|webm|webp|woff2?)(?:$|\?)/i;
const ANALYTICS = /(?:^|[./_-])(?:analytics|telemetry|metrics|beacon|collect|tracking)(?:$|[./?_-])/i;
const ADVERTISEMENT = /(?:^|[./_-])(?:ads?|doubleclick|adservice|sponsor)(?:$|[./?_-])/i;
const TRACKER = /(?:segment\.io|google-analytics|googletagmanager|mixpanel|hotjar|sentry\.io|newrelic)/i;

function singular(value: string): string {
  if (value.endsWith("ies")) return `${value.slice(0, -3)}y`;
  if (value.endsWith("ses")) return value.slice(0, -2);
  if (value.endsWith("s") && !value.endsWith("ss")) return value.slice(0, -1);
  return value || "resource";
}

function parameterName(previous: string | undefined): string {
  const cleaned = decodeURIComponent(previous ?? "resource").replace(/[^A-Za-z0-9]/g, " ");
  const words = cleaned.trim().split(/\s+/).filter(Boolean);
  const base = singular(words.at(-1)?.toLowerCase() ?? "resource");
  return `${base.replace(/[^a-z0-9]/g, "") || "resource"}Id`;
}

export function normalizePath(rawUrl: string): string {
  try {
    const url = new URL(rawUrl);
    const segments = url.pathname.split("/");
    return segments
      .map((segment, index) => {
        const decoded = decodeURIComponent(segment);
        if (isSensitiveName(decodeURIComponent(segments[index - 1] ?? ""))) return "{secret}";
        if (DATE_SEGMENT.test(decoded)) return "{date}";
        if (DYNAMIC_SEGMENT.test(decoded)) return `{${parameterName(segments[index - 1])}}`;
        return segment;
      })
      .join("/");
  } catch {
    return rawUrl.split("?")[0] ?? rawUrl;
  }
}

export function normalizeAllowedOrigins(lines: string[]): string[] {
  const origins = new Set<string>();
  for (const candidate of lines.map((line) => line.trim()).filter(Boolean)) {
    try {
      const url = new URL(candidate);
      if (!/^https?:$/.test(url.protocol) || url.username || url.password) continue;
      origins.add(url.origin);
    } catch {
      // Invalid entries are rejected by omission and surfaced by the panel validation.
    }
  }
  return [...origins].sort();
}

export function isAllowedUrl(rawUrl: string, allowedOrigins: string[]): boolean {
  try {
    return allowedOrigins.includes(new URL(rawUrl).origin);
  } catch {
    return false;
  }
}

export function matchesPattern(value: string, pattern: string): boolean {
  const trimmed = pattern.trim();
  if (!trimmed) return false;
  if (!/[?*]/.test(trimmed)) return value.toLowerCase().includes(trimmed.toLowerCase());
  const escaped = trimmed.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
  return new RegExp(`^${escaped}$`, "i").test(value);
}

export function passesUrlPatterns(rawUrl: string, includes: string[], excludes: string[]): boolean {
  let path = rawUrl;
  try {
    const url = new URL(rawUrl);
    path = `${url.pathname}${url.search}`;
  } catch {
    // Match the original text when URL parsing fails.
  }
  const included = includes.length === 0 || includes.some((pattern) => matchesPattern(rawUrl, pattern) || matchesPattern(path, pattern));
  const excluded = excludes.some((pattern) => matchesPattern(rawUrl, pattern) || matchesPattern(path, pattern));
  return included && !excluded;
}

export function defaultExclusion(rawUrl: string, contentType = ""): ExclusionCategory | undefined {
  if (TRACKER.test(rawUrl)) return "third-party-tracking";
  if (ADVERTISEMENT.test(rawUrl)) return "advertisement";
  if (ANALYTICS.test(rawUrl)) return rawUrl.toLowerCase().includes("telemetry") ? "telemetry" : "analytics";
  if (STATIC_EXTENSION.test(rawUrl) || /^(?:image|font|audio|video)\//i.test(contentType)) return "static-resource";
  return undefined;
}
