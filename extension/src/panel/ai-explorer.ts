import { prohibitedActionReason, requiresStateChangeApproval, snapshotStateHash, validateAiAction } from "../shared/ai-safety";
import { isAllowedUrl } from "../shared/patterns";
import type { CommandResponse } from "../shared/messages";
import type { AiAction, ExplorationLimits, ExplorationRequest, ModelSnapshot, PageSnapshot, Recording } from "../shared/schema";
import { OrchestratorClient } from "./orchestrator-client";

export interface AiExplorerDependencies {
  recording(): Recording | null;
  testData(): Record<string, string>;
  limits(): ExplorationLimits;
  client(): OrchestratorClient;
  snapshot(): Promise<PageSnapshot>;
  execute(action: AiAction, resolvedValue: string | undefined, stateChangeApproved: boolean): Promise<CommandResponse>;
  approve(description: string): boolean;
  status(message: string, level?: "info" | "success" | "warning" | "error"): void;
  stopped(): void;
}

export class AiExplorer {
  #dependencies: AiExplorerDependencies;
  #running = false;
  #history: AiAction[] = [];
  #visits = new Map<string, { title: string; visits: number }>();
  #stateCounts = new Map<string, number>();

  constructor(dependencies: AiExplorerDependencies) {
    this.#dependencies = dependencies;
  }

  get running(): boolean {
    return this.#running;
  }

  start(): void {
    if (this.#running) return;
    this.#running = true;
    this.#history = [];
    this.#visits.clear();
    this.#stateCounts.clear();
    void this.#loop();
  }

  stop(reason = "AI exploration stopped."): void {
    if (!this.#running) return;
    this.#running = false;
    this.#dependencies.status(reason, "info");
    this.#dependencies.stopped();
  }

  async #loop(): Promise<void> {
    const startedAt = Date.now();
    let retries = 0;
    try {
      while (this.#running) {
        const recording = this.#dependencies.recording();
        if (!recording) throw new Error("Start a recording before AI exploration.");
        const limits = this.#dependencies.limits();
        if (this.#history.length >= limits.maxActions) {
          this.stop(`AI exploration reached its ${limits.maxActions}-action limit.`);
          break;
        }
        if (Date.now() - startedAt >= limits.maxRuntimeMs) {
          this.stop("AI exploration reached its runtime limit.");
          break;
        }

        const page = await this.#dependencies.snapshot();
        if (!isAllowedUrl(page.currentUrl, recording.configuration.allowedOrigins)) throw new Error("The inspected page left the authorized origins.");
        const priorVisit = this.#visits.get(page.currentUrl);
        this.#visits.set(page.currentUrl, { title: page.title, visits: (priorVisit?.visits ?? 0) + 1 });
        const observedApis = recording.operations
          .filter((operation) => operation.included)
          .map((operation) => ({
            method: operation.request.method,
            normalizedPath: operation.request.normalizedPath,
            status: operation.response.status
          }))
          .filter(
            (operation, index, all) =>
              all.findIndex(
                (candidate) =>
                  candidate.method === operation.method &&
                  candidate.normalizedPath === operation.normalizedPath &&
                  candidate.status === operation.status
              ) === index
          )
          .slice(0, 200);
        const snapshot: ModelSnapshot = {
          ...page,
          visitedPageSummary: [...this.#visits.entries()].map(([url, visit]) => ({ url, ...visit })).slice(-50),
          observedApis
        };
        const hash = snapshotStateHash(snapshot);
        const repeats = (this.#stateCounts.get(hash) ?? 0) + 1;
        this.#stateCounts.set(hash, repeats);
        if (repeats > limits.maxRepeatedStates) {
          this.stop("AI exploration stopped after detecting a repeated page state.");
          break;
        }

        const testData = this.#dependencies.testData();
        const request: ExplorationRequest = {
          schemaVersion: "1.0.0",
          snapshot,
          history: this.#history,
          observedApis,
          availableTestDataRefs: Object.keys(testData),
          limits
        };
        this.#dependencies.status(`AI is choosing action ${this.#history.length + 1} of ${limits.maxActions}…`);
        try {
          const raw = await this.#dependencies.client().nextAction(request);
          const action = validateAiAction(
            raw,
            page.currentUrl,
            new Set(page.interactiveElements.map((element) => element.ref)),
            new Set(Object.keys(testData))
          );
          const prohibited = prohibitedActionReason(action, snapshot);
          if (prohibited) throw new Error(prohibited);
          if (action.type === "stop") {
            this.stop(action.reason ? `AI stopped: ${action.reason}` : "AI found no further useful safe actions.");
            break;
          }
          const approvalNeeded = requiresStateChangeApproval(action, snapshot);
          const approved = !approvalNeeded || this.#dependencies.approve(this.#description(action, snapshot));
          if (!approved) {
            this.stop("AI exploration stopped because a state-changing action was not approved.");
            break;
          }
          const resolvedValue = "valueRef" in action ? testData[action.valueRef] : undefined;
          let result = await this.#dependencies.execute(action, resolvedValue, approvalNeeded && approved);
          if (!result.ok && result.stateChanged && !approvalNeeded) {
            const defenseApproved = this.#dependencies.approve(this.#description(action, snapshot));
            if (!defenseApproved) {
              this.stop("AI exploration stopped because a state-changing action was not approved.");
              break;
            }
            result = await this.#dependencies.execute(action, resolvedValue, true);
          }
          if (!result.ok) throw new Error(result.error ?? "The browser rejected the AI action.");
          this.#history.push(action);
          retries = 0;
          await new Promise((resolve) => setTimeout(resolve, 650));
        } catch (error) {
          retries += 1;
          const message = error instanceof Error ? error.message : String(error);
          if (retries > limits.maxRetries) throw new Error(`AI exploration exhausted its retry budget: ${message}`);
          this.#dependencies.status(`AI action failed (${retries}/${limits.maxRetries}); retrying safely: ${message}`, "warning");
          await new Promise((resolve) => setTimeout(resolve, 750));
        }
      }
    } catch (error) {
      this.stop(error instanceof Error ? error.message : String(error));
    } finally {
      if (this.#running) this.stop();
    }
  }

  #description(action: AiAction, snapshot: ModelSnapshot): string {
    const element = "elementRef" in action
      ? snapshot.interactiveElements.find((candidate) => candidate.ref === action.elementRef)
      : undefined;
    return `Allow AI to ${action.type} ${element ? `“${element.name || element.role}”` : "the selected control"}? This may change server-side state.`;
  }
}
