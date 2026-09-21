import type { AiAction, CaptureConfiguration, PageSnapshot, UiAction } from "./schema";

export type PanelCommand =
  | { source: "webtest-agent-panel"; command: "start"; sessionId: string; configuration: CaptureConfiguration }
  | { source: "webtest-agent-panel"; command: "stop" }
  | { source: "webtest-agent-panel"; command: "clear" }
  | { source: "webtest-agent-panel"; command: "snapshot" }
  | {
      source: "webtest-agent-panel";
      command: "execute";
      action: AiAction;
      resolvedValue?: string;
      stateChangeApproved?: boolean;
    };

export type ContentEvent =
  | { source: "webtest-agent-content"; event: "action"; action: UiAction }
  | { source: "webtest-agent-content"; event: "ready"; pageUrl: string };

export interface CommandResponse {
  ok: boolean;
  error?: string;
  snapshot?: PageSnapshot;
  stateChanged?: boolean;
}

export function isContentEvent(value: unknown): value is ContentEvent {
  return Boolean(value && typeof value === "object" && (value as { source?: string }).source === "webtest-agent-content");
}
