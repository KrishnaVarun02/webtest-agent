import type { CapturedOperation, Recording } from "./schema";

function bodyText(body: CapturedOperation["request"]["body"]): string | undefined {
  if (body === undefined) return undefined;
  return typeof body === "string" ? body : JSON.stringify(body);
}

export function recordingToHar(recording: Recording): Record<string, unknown> {
  const pageId = `page_${recording.sessionId}`;
  return {
    log: {
      version: "1.2",
      creator: { name: "WebTest Agent", version: recording.metadata.extensionVersion },
      pages: [
        {
          startedDateTime: recording.startedAt,
          id: pageId,
          title: recording.operations[0]?.pageUrl ?? "Inspected page",
          pageTimings: {}
        }
      ],
      entries: recording.operations.filter((operation) => operation.included).map((operation) => ({
        pageref: pageId,
        startedDateTime: operation.timestamp,
        time: operation.timing.totalMs,
        request: {
          method: operation.request.method,
          url: operation.request.url,
          httpVersion: "",
          headers: operation.request.headers,
          queryString: operation.request.query,
          cookies: [],
          headersSize: -1,
          bodySize: bodyText(operation.request.body)?.length ?? 0,
          ...(operation.request.body !== undefined
            ? {
                postData: {
                  mimeType: operation.request.contentType ?? "application/octet-stream",
                  text: bodyText(operation.request.body)
                }
              }
            : {})
        },
        response: {
          status: operation.response.status,
          statusText: operation.response.statusText ?? "",
          httpVersion: "",
          headers: operation.response.headers,
          cookies: [],
          content: {
            size: bodyText(operation.response.body)?.length ?? 0,
            mimeType: operation.response.contentType ?? "application/octet-stream",
            ...(operation.response.body !== undefined ? { text: bodyText(operation.response.body) } : {})
          },
          redirectURL: "",
          headersSize: -1,
          bodySize: bodyText(operation.response.body)?.length ?? -1
        },
        cache: {},
        timings: {
          blocked: operation.timing.blockedMs ?? -1,
          dns: operation.timing.dnsMs ?? -1,
          connect: operation.timing.connectMs ?? -1,
          send: operation.timing.sendMs ?? -1,
          wait: operation.timing.waitMs ?? -1,
          receive: operation.timing.receiveMs ?? -1,
          ssl: operation.timing.sslMs ?? -1
        },
        _webTestAgent: {
          operationId: operation.id,
          recordingId: operation.sessionId,
          relatedActionId: operation.relatedActionId,
          normalizedPath: operation.request.normalizedPath
        }
      }))
    }
  };
}
