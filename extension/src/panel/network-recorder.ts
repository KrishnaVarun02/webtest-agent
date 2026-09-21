import { shouldCapture, toCapturedOperation, type HarEntryLike } from "../shared/capture";
import type { CaptureConfiguration, CapturedOperation } from "../shared/schema";

interface DevtoolsNetworkRequest extends HarEntryLike {
  getContent(callback: (content: string | null, encoding: string) => void): void;
}

export interface NetworkContext {
  active(): boolean;
  sessionId(): string;
  configuration(): CaptureConfiguration;
  latestActionId(): string | undefined;
  currentPageUrl(): string;
  operationCount(): number;
  onOperation(operation: CapturedOperation): void;
  onError(message: string): void;
}

function getContent(request: DevtoolsNetworkRequest): Promise<{ content: string | null; encoding?: string }> {
  return new Promise((resolve) => {
    let resolved = false;
    const timeout = window.setTimeout(() => {
      if (!resolved) {
        resolved = true;
        resolve({ content: null });
      }
    }, 3_000);
    try {
      request.getContent((content, encoding) => {
        if (resolved) return;
        resolved = true;
        clearTimeout(timeout);
        resolve({ content, ...(encoding ? { encoding } : {}) });
      });
    } catch {
      clearTimeout(timeout);
      resolved = true;
      resolve({ content: null });
    }
  });
}

export class NetworkRecorder {
  #context: NetworkContext;

  constructor(context: NetworkContext) {
    this.#context = context;
    chrome.devtools.network.onRequestFinished.addListener((request) => {
      void this.#capture(request as unknown as DevtoolsNetworkRequest);
    });
  }

  async #capture(request: DevtoolsNetworkRequest): Promise<void> {
    if (!this.#context.active()) return;
    const configuration = this.#context.configuration();
    if (this.#context.operationCount() >= configuration.maxOperations || !shouldCapture(request, configuration)) return;
    const correlation = this.#context.latestActionId();
    const pageUrl = this.#context.currentPageUrl();
    const { content, encoding } = await getContent(request);
    if (!this.#context.active()) return;
    try {
      this.#context.onOperation(
        toCapturedOperation(request, {
          sessionId: this.#context.sessionId(),
          pageUrl,
          configuration,
          ...(correlation ? { relatedActionId: correlation } : {}),
          responseText: content,
          ...(encoding ? { responseEncoding: encoding } : {})
        })
      );
    } catch (error) {
      this.#context.onError(error instanceof Error ? error.message : String(error));
    }
  }
}
