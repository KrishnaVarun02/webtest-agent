import { createId } from "./ids";
import { defaultExclusion, isAllowedUrl, normalizePath, passesUrlPatterns } from "./patterns";
import { sanitizeBody, sanitizeHeaders, sanitizedQuery, sanitizeUnknown, sanitizeUrl } from "./sanitize";
import type { CaptureConfiguration, CapturedOperation, HeaderValue, JsonValue, TimingInformation } from "./schema";

export interface HarPostDataLike {
  mimeType?: string;
  text?: string;
  params?: Array<{ name: string; value?: string }>;
}

export interface HarRequestLike {
  method: string;
  url: string;
  headers?: HeaderValue[];
  postData?: HarPostDataLike;
  _resourceType?: string;
}

export interface HarResponseLike {
  status: number;
  statusText?: string;
  headers?: HeaderValue[];
  content?: { mimeType?: string; text?: string };
}

export interface HarEntryLike {
  startedDateTime?: string;
  time?: number;
  request: HarRequestLike;
  response: HarResponseLike;
  timings?: Partial<Record<"blocked" | "dns" | "connect" | "send" | "wait" | "receive" | "ssl", number>>;
  _resourceType?: string;
}

export interface CaptureContext {
  sessionId: string;
  pageUrl: string;
  relatedActionId?: string;
  configuration: CaptureConfiguration;
  responseText?: string | null;
  responseEncoding?: string;
}

function header(headers: HeaderValue[] | undefined, name: string): string | undefined {
  return headers?.find((entry) => entry.name.toLowerCase() === name.toLowerCase())?.value;
}

export function apiResourceType(entry: HarEntryLike): "xhr" | "fetch" | undefined {
  const value = (entry._resourceType ?? entry.request._resourceType ?? "").toLowerCase();
  if (value === "xhr" || value === "xmlhttprequest") return "xhr";
  if (value === "fetch") return "fetch";
  return undefined;
}

export function shouldCapture(entry: HarEntryLike, configuration: CaptureConfiguration): boolean {
  return Boolean(
    apiResourceType(entry) &&
      isAllowedUrl(entry.request.url, configuration.allowedOrigins) &&
      passesUrlPatterns(entry.request.url, configuration.includePatterns, configuration.excludePatterns)
  );
}

function timingInformation(entry: HarEntryLike): TimingInformation {
  const result: TimingInformation = { totalMs: Math.max(0, entry.time ?? 0) };
  const mapping: Array<[keyof NonNullable<HarEntryLike["timings"]>, keyof Omit<TimingInformation, "totalMs">]> = [
    ["blocked", "blockedMs"],
    ["dns", "dnsMs"],
    ["connect", "connectMs"],
    ["send", "sendMs"],
    ["wait", "waitMs"],
    ["receive", "receiveMs"],
    ["ssl", "sslMs"]
  ];
  for (const [source, destination] of mapping) {
    const value = entry.timings?.[source];
    if (typeof value === "number" && value >= 0) result[destination] = value;
  }
  return result;
}

function requestBody(postData: HarPostDataLike | undefined, contentType: string): JsonValue | undefined {
  if (!postData) return undefined;
  if (postData.text) return sanitizeBody(postData.text, postData.mimeType ?? contentType);
  if (postData.params) {
    return sanitizeUnknown(Object.fromEntries(postData.params.map((entry) => [entry.name, entry.value ?? ""]))) as JsonValue;
  }
  return undefined;
}

function responseBody(text: string | null | undefined, encoding: string | undefined, contentType: string): {
  body?: JsonValue;
  bodyUnavailableReason?: string;
} {
  if (encoding) return { bodyUnavailableReason: `encoded-response-body:${encoding}` };
  if (text === null || text === undefined) return { bodyUnavailableReason: "response-content-unavailable" };
  if (/^(?:image|font|audio|video)\//i.test(contentType) || /(?:octet-stream|zip|protobuf|grpc)/i.test(contentType)) {
    return { bodyUnavailableReason: "binary-response-body" };
  }
  return { body: sanitizeBody(text, contentType) };
}

export function toCapturedOperation(entry: HarEntryLike, context: CaptureContext): CapturedOperation {
  const resourceType = apiResourceType(entry);
  if (!resourceType) throw new Error("Only XHR and fetch entries can become captured operations.");
  if (!isAllowedUrl(entry.request.url, context.configuration.allowedOrigins)) throw new Error("Request origin is not authorized.");

  const requestContentType = entry.request.postData?.mimeType ?? header(entry.request.headers, "content-type") ?? undefined;
  const responseContentType = entry.response.content?.mimeType ?? header(entry.response.headers, "content-type") ?? undefined;
  const exclusionReason = defaultExclusion(entry.request.url, responseContentType);
  const bodyResult = responseBody(
    context.responseText ?? entry.response.content?.text,
    context.responseEncoding,
    responseContentType ?? ""
  );
  return {
    id: createId("operation"),
    sessionId: context.sessionId,
    timestamp: entry.startedDateTime ?? new Date().toISOString(),
    pageUrl: sanitizeUrl(context.pageUrl),
    resourceType,
    request: {
      method: entry.request.method.toUpperCase(),
      url: sanitizeUrl(entry.request.url),
      normalizedPath: normalizePath(entry.request.url),
      query: sanitizedQuery(entry.request.url),
      headers: sanitizeHeaders(entry.request.headers),
      ...(requestContentType ? { contentType: requestContentType } : {}),
      ...(requestBody(entry.request.postData, requestContentType ?? "") !== undefined
        ? { body: requestBody(entry.request.postData, requestContentType ?? "") }
        : {})
    },
    response: {
      status: entry.response.status,
      ...(entry.response.statusText ? { statusText: entry.response.statusText } : {}),
      headers: sanitizeHeaders(entry.response.headers),
      ...(responseContentType ? { contentType: responseContentType } : {}),
      ...bodyResult
    },
    timing: timingInformation(entry),
    ...(context.relatedActionId ? { relatedActionId: context.relatedActionId } : {}),
    included: exclusionReason === undefined,
    ...(exclusionReason ? { exclusionReason } : {})
  };
}
