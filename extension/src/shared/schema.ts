export const RECORDING_SCHEMA_VERSION = "1.0.0" as const;
export const EXTENSION_VERSION = "0.1.0" as const;

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export type UiActionType =
  | "click"
  | "input"
  | "select"
  | "navigation"
  | "submit"
  | "back"
  | "wait"
  | "page_change";

export type LocatorStrategy = "test-attribute" | "role" | "label" | "id" | "css";

export interface LocatorCandidate {
  strategy: LocatorStrategy;
  value: string;
  role?: string;
  name?: string;
}

export interface UiAction {
  id: string;
  sessionId: string;
  type: UiActionType;
  timestamp: string;
  pageUrl: string;
  locator?: LocatorCandidate;
  value?: string;
  metadata?: Record<string, JsonValue>;
}

export interface CaptureConfiguration {
  allowedOrigins: string[];
  includePatterns: string[];
  excludePatterns: string[];
  maxOperations: number;
}

export interface HeaderValue {
  name: string;
  value: string;
}

export interface QueryParameter {
  name: string;
  value: string;
}

export interface TimingInformation {
  totalMs: number;
  blockedMs?: number;
  dnsMs?: number;
  connectMs?: number;
  sendMs?: number;
  waitMs?: number;
  receiveMs?: number;
  sslMs?: number;
}

export interface RecordedRequest {
  method: string;
  url: string;
  normalizedPath: string;
  query: QueryParameter[];
  headers: HeaderValue[];
  contentType?: string;
  body?: JsonValue;
}

export interface RecordedResponse {
  status: number;
  statusText?: string;
  headers: HeaderValue[];
  contentType?: string;
  body?: JsonValue;
  bodyUnavailableReason?: string;
}

export type ExclusionCategory =
  | "analytics"
  | "telemetry"
  | "static-resource"
  | "advertisement"
  | "third-party-tracking"
  | "user-excluded";

export interface CapturedOperation {
  id: string;
  sessionId: string;
  timestamp: string;
  pageUrl: string;
  resourceType: "xhr" | "fetch";
  request: RecordedRequest;
  response: RecordedResponse;
  timing: TimingInformation;
  relatedActionId?: string;
  included: boolean;
  exclusionReason?: ExclusionCategory;
}

export interface Recording {
  schemaVersion: typeof RECORDING_SCHEMA_VERSION;
  product: "WebTest Agent";
  sessionId: string;
  inspectedTabId: number;
  startedAt: string;
  endedAt?: string;
  configuration: CaptureConfiguration;
  actions: UiAction[];
  operations: CapturedOperation[];
  metadata: {
    extensionVersion: typeof EXTENSION_VERSION;
    captureScope: "one-inspected-tab";
    protocols: ["REST"];
    formats: ["JSON", "form-urlencoded"];
    reloadObserved: boolean;
  };
}

export interface InteractiveElementSnapshot {
  ref: string;
  role: string;
  name: string;
  enabled: boolean;
}

export interface PageSnapshot {
  currentUrl: string;
  title: string;
  headings: string[];
  interactiveElements: InteractiveElementSnapshot[];
}

export interface ModelSnapshot extends PageSnapshot {
  visitedPageSummary: Array<{ url: string; title: string; visits: number }>;
  observedApis: Array<{ method: string; normalizedPath: string; status: number }>;
}

export type AiAction =
  | { type: "click"; elementRef: string }
  | { type: "fill"; elementRef: string; valueRef: string }
  | { type: "select"; elementRef: string; valueRef: string }
  | { type: "scroll"; direction: "up" | "down"; amount?: number }
  | { type: "wait"; durationMs: number }
  | { type: "back" }
  | { type: "navigate"; url: string }
  | { type: "stop"; reason?: string };

export interface ExplorationLimits {
  maxActions: number;
  maxRuntimeMs: number;
  maxRetries: number;
  maxRepeatedStates: number;
}

export interface ExplorationRequest {
  schemaVersion: "1.0.0";
  snapshot: ModelSnapshot;
  history: AiAction[];
  observedApis: ModelSnapshot["observedApis"];
  availableTestDataRefs: string[];
  limits: ExplorationLimits;
}

export interface ReviewResponse {
  plan: JsonValue;
  warnings?: string[];
}

export interface GenerateResponse {
  runId?: string;
  projectPath?: string;
  reportPath?: string;
  status: string;
  [key: string]: JsonValue | undefined;
}
