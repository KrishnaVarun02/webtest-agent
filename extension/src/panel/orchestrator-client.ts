import type { AiAction, ExplorationRequest, GenerateResponse, JsonValue, Recording, ReviewResponse } from "../shared/schema";

export class OrchestratorClient {
  readonly baseUrl: string;

  constructor(baseUrl: string) {
    const parsed = new URL(baseUrl);
    if (!/^https?:$/.test(parsed.protocol)) throw new Error("Orchestrator URL must use HTTP or HTTPS.");
    if (parsed.username || parsed.password) throw new Error("Orchestrator URL must not contain credentials.");
    if (!["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname)) {
      throw new Error("Version one only sends recordings to a local loopback orchestrator.");
    }
    this.baseUrl = parsed.href.replace(/\/$/, "");
  }

  async #request<T>(path: string, init?: RequestInit): Promise<T> {
    const controller = new AbortController();
    const timeout = globalThis.setTimeout(() => controller.abort(), 20_000);
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        signal: controller.signal,
        headers: { "content-type": "application/json", ...init?.headers }
      });
      const text = await response.text();
      let payload: unknown = {};
      if (text) {
        try {
          payload = JSON.parse(text);
        } catch {
          throw new Error(`Orchestrator returned non-JSON (${response.status}).`);
        }
      }
      if (!response.ok) {
        const detail = payload && typeof payload === "object" && "detail" in payload ? String((payload as { detail: unknown }).detail) : response.statusText;
        throw new Error(`Orchestrator request failed (${response.status}): ${detail}`);
      }
      return payload as T;
    } finally {
      clearTimeout(timeout);
    }
  }

  health(): Promise<JsonValue> {
    return this.#request<JsonValue>("/health", { method: "GET" });
  }

  nextAction(request: ExplorationRequest): Promise<AiAction | { action: AiAction }> {
    return this.#request<AiAction | { action: AiAction }>("/api/v1/explore/next", { method: "POST", body: JSON.stringify(request) });
  }

  review(recording: Recording): Promise<ReviewResponse> {
    return this.#request<ReviewResponse>("/api/v1/review", { method: "POST", body: JSON.stringify(recording) });
  }

  generate(recordingId: string, approvedPlan: JsonValue): Promise<GenerateResponse> {
    return this.#request<GenerateResponse>("/api/v1/generate", {
      method: "POST",
      body: JSON.stringify({ recordingId, approved: true, approvedPlan })
    });
  }
}
