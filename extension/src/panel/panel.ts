import { AiExplorer } from "./ai-explorer";
import { NetworkRecorder } from "./network-recorder";
import { OrchestratorClient } from "./orchestrator-client";
import { recordingToHar } from "../shared/har";
import { createId } from "../shared/ids";
import { isContentEvent, type CommandResponse, type PanelCommand } from "../shared/messages";
import { isAllowedUrl, normalizeAllowedOrigins } from "../shared/patterns";
import { redactText, sanitizeUnknown, sanitizeUrl } from "../shared/sanitize";
import { sanitizeReviewPlan } from "../shared/plan-sanitize";
import {
  EXTENSION_VERSION,
  RECORDING_SCHEMA_VERSION,
  type AiAction,
  type CaptureConfiguration,
  type ExplorationLimits,
  type JsonValue,
  type Recording,
  type UiAction
} from "../shared/schema";

const inspectedTabId = chrome.devtools.inspectedWindow.tabId;
const STORAGE_SETTINGS = "webtestAgent.settings.v1";
const STORAGE_RECORDING = "webtestAgent.recording.v1";

interface StoredSettings {
  allowedOrigins: string;
  includePatterns: string;
  excludePatterns: string;
  orchestratorUrl: string;
  maxOperations: number;
  maxActions: number;
  maxRuntime: number;
  maxRetries: number;
  maxRepeatedStates: number;
}

function requiredElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Panel element '${id}' is missing.`);
  return element as T;
}

const elements = {
  reloadNotice: requiredElement<HTMLDivElement>("reloadNotice"),
  status: requiredElement<HTMLDivElement>("status"),
  badge: requiredElement<HTMLSpanElement>("recordingBadge"),
  allowedOrigins: requiredElement<HTMLTextAreaElement>("allowedOrigins"),
  includePatterns: requiredElement<HTMLTextAreaElement>("includePatterns"),
  excludePatterns: requiredElement<HTMLTextAreaElement>("excludePatterns"),
  orchestratorUrl: requiredElement<HTMLInputElement>("orchestratorUrl"),
  maxOperations: requiredElement<HTMLInputElement>("maxOperations"),
  testData: requiredElement<HTMLTextAreaElement>("testData"),
  maxActions: requiredElement<HTMLInputElement>("maxActions"),
  maxRuntime: requiredElement<HTMLInputElement>("maxRuntime"),
  maxRetries: requiredElement<HTMLInputElement>("maxRetries"),
  maxRepeatedStates: requiredElement<HTMLInputElement>("maxRepeatedStates"),
  start: requiredElement<HTMLButtonElement>("start"),
  stop: requiredElement<HTMLButtonElement>("stop"),
  clear: requiredElement<HTMLButtonElement>("clear"),
  exportJson: requiredElement<HTMLButtonElement>("export"),
  exportHar: requiredElement<HTMLButtonElement>("exportHar"),
  aiExplore: requiredElement<HTMLButtonElement>("aiExplore"),
  review: requiredElement<HTMLButtonElement>("review"),
  generate: requiredElement<HTMLButtonElement>("generate"),
  actionCount: requiredElement<HTMLElement>("actionCount"),
  operationCount: requiredElement<HTMLElement>("operationCount"),
  includedCount: requiredElement<HTMLElement>("includedCount"),
  excludedCount: requiredElement<HTMLElement>("excludedCount"),
  operations: requiredElement<HTMLTableSectionElement>("operations"),
  reviewSection: requiredElement<HTMLElement>("reviewSection"),
  planEditor: requiredElement<HTMLTextAreaElement>("planEditor"),
  approvePlan: requiredElement<HTMLInputElement>("approvePlan"),
  generationResult: requiredElement<HTMLPreElement>("generationResult")
};

let recording: Recording | null = null;
let recordingActive = false;
let reloadObserved = false;
let currentPageUrl = "";
let latestActionId: string | undefined;
let plan: JsonValue | null = null;
let persistTimer: number | undefined;

function lines(value: string): string[] {
  return value.split(/\r?\n|,/).map((line) => line.trim()).filter(Boolean);
}

function boundedInteger(input: HTMLInputElement, minimum: number, maximum: number): number {
  const value = Number(input.value);
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${input.previousSibling?.textContent?.trim() || input.id} must be an integer from ${minimum} to ${maximum}.`);
  }
  return value;
}

function configurationFromUi(): CaptureConfiguration {
  const rawOrigins = lines(elements.allowedOrigins.value);
  const allowedOrigins = normalizeAllowedOrigins(rawOrigins);
  if (rawOrigins.length === 0) throw new Error("Add at least one authorized origin before recording.");
  const invalid = rawOrigins.filter((candidate) => {
    try {
      const parsed = new URL(candidate);
      return !/^https?:$/.test(parsed.protocol) || Boolean(parsed.username || parsed.password);
    } catch {
      return true;
    }
  });
  if (invalid.length > 0) throw new Error("Allowed origins must be valid HTTP(S) origins without paths, queries, or credentials.");
  const nonOrigins = rawOrigins.filter((candidate) => {
    const parsed = new URL(candidate);
    return candidate.replace(/\/$/, "") !== parsed.origin;
  });
  if (nonOrigins.length > 0) throw new Error("Allowed-origin entries must contain only scheme, host, and optional port.");
  return {
    allowedOrigins,
    includePatterns: lines(elements.includePatterns.value).map(redactText),
    excludePatterns: lines(elements.excludePatterns.value).map(redactText),
    maxOperations: boundedInteger(elements.maxOperations, 1, 1_000)
  };
}

function limitsFromUi(): ExplorationLimits {
  return {
    maxActions: boundedInteger(elements.maxActions, 1, 50),
    maxRuntimeMs: boundedInteger(elements.maxRuntime, 10, 600) * 1_000,
    maxRetries: boundedInteger(elements.maxRetries, 0, 5),
    maxRepeatedStates: boundedInteger(elements.maxRepeatedStates, 1, 10)
  };
}

function testDataFromUi(): Record<string, string> {
  const raw = elements.testData.value.trim();
  if (!raw) return {};
  const parsed: unknown = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("AI test data must be a JSON object.");
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
    if (!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(key)) throw new Error("AI test-data keys must be short alphanumeric reference names.");
    if (!["string", "number", "boolean"].includes(typeof value)) throw new Error(`AI test-data value '${key}' must be a string, number, or boolean.`);
    result[key] = String(value).slice(0, 10_000);
  }
  return result;
}

function clientFromUi(): OrchestratorClient {
  return new OrchestratorClient(elements.orchestratorUrl.value.trim());
}

function setStatus(message: string, level: "info" | "success" | "warning" | "error" = "info"): void {
  elements.status.textContent = message;
  elements.status.className = `notice${level === "info" ? "" : ` ${level}`}`;
}

function friendlyError(error: unknown): string {
  if (error instanceof Error) {
    if (/Receiving end does not exist|Could not establish connection/i.test(error.message)) {
      return "The action recorder is not attached. Reload the inspected page after opening DevTools.";
    }
    if (error.name === "AbortError") return "The local orchestrator request timed out.";
    return error.message;
  }
  return String(error);
}

async function sendCommand(command: PanelCommand): Promise<CommandResponse> {
  try {
    const response = (await chrome.tabs.sendMessage(inspectedTabId, command)) as CommandResponse | undefined;
    if (!response) throw new Error("The inspected page did not respond.");
    return response;
  } catch (error) {
    throw new Error(friendlyError(error));
  }
}

function safeAction(action: UiAction): UiAction {
  return {
    ...action,
    pageUrl: sanitizeUrl(action.pageUrl),
    ...(action.value !== undefined
      ? { value: /^\$\{[A-Z][A-Z0-9_]*\}$/.test(action.value) ? action.value : redactText(action.value) }
      : {}),
    ...(action.metadata ? { metadata: sanitizeUnknown(action.metadata) as Record<string, JsonValue> } : {})
  };
}

function schedulePersist(): void {
  if (persistTimer) clearTimeout(persistTimer);
  persistTimer = window.setTimeout(() => {
    if (!recording) return;
    chrome.storage.local.set({ [STORAGE_RECORDING]: recording }).catch(() => {
      setStatus("Recording continues in memory, but Chrome could not persist the latest capture.", "warning");
    });
  }, 200);
}

function download(filename: string, data: unknown, type: string): void {
  const blob = new Blob([`${JSON.stringify(data, null, 2)}\n`], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

function renderOperations(): void {
  elements.operations.replaceChildren();
  if (!recording || recording.operations.length === 0) {
    const row = elements.operations.insertRow();
    const cell = row.insertCell();
    cell.colSpan = 6;
    cell.className = "empty";
    cell.textContent = "No API calls captured yet.";
    return;
  }
  for (const operation of recording.operations.slice().reverse()) {
    const row = elements.operations.insertRow();
    row.className = operation.included ? "" : "excluded";
    const useCell = row.insertCell();
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = operation.included;
    checkbox.title = operation.exclusionReason ? `Default exclusion: ${operation.exclusionReason}` : "Include in planning";
    checkbox.addEventListener("change", () => {
      operation.included = checkbox.checked;
      operation.exclusionReason = checkbox.checked ? undefined : "user-excluded";
      schedulePersist();
      render();
    });
    useCell.append(checkbox);
    const method = row.insertCell();
    method.textContent = operation.request.method;
    method.className = "method";
    const path = row.insertCell();
    path.textContent = operation.request.normalizedPath;
    path.title = operation.request.url;
    path.className = "path";
    row.insertCell().textContent = String(operation.response.status);
    row.insertCell().textContent = operation.resourceType;
    row.insertCell().textContent = operation.relatedActionId?.slice(-10) ?? "—";
  }
}

function render(): void {
  const actions = recording?.actions.length ?? 0;
  const operations = recording?.operations.length ?? 0;
  const included = recording?.operations.filter((operation) => operation.included).length ?? 0;
  elements.actionCount.textContent = String(actions);
  elements.operationCount.textContent = String(operations);
  elements.includedCount.textContent = String(included);
  elements.excludedCount.textContent = String(operations - included);
  elements.badge.textContent = recordingActive ? "Recording" : "Idle";
  elements.badge.className = `badge ${recordingActive ? "recording" : "idle"}`;
  elements.start.disabled = recordingActive;
  elements.stop.disabled = !recordingActive;
  elements.aiExplore.disabled = !recordingActive;
  elements.aiExplore.textContent = explorer.running ? "Stop AI" : "AI Explore";
  elements.review.disabled = !recording || included === 0;
  elements.generate.disabled = !plan || !elements.approvePlan.checked;
  elements.exportJson.disabled = !recording;
  elements.exportHar.disabled = !recording;
  renderOperations();
}

function storedSettings(): StoredSettings {
  return {
    allowedOrigins: elements.allowedOrigins.value,
    includePatterns: elements.includePatterns.value,
    excludePatterns: elements.excludePatterns.value,
    orchestratorUrl: elements.orchestratorUrl.value,
    maxOperations: Number(elements.maxOperations.value),
    maxActions: Number(elements.maxActions.value),
    maxRuntime: Number(elements.maxRuntime.value),
    maxRetries: Number(elements.maxRetries.value),
    maxRepeatedStates: Number(elements.maxRepeatedStates.value)
  };
}

function saveSettings(): void {
  const settings = storedSettings();
  settings.includePatterns = lines(settings.includePatterns).map(redactText).join("\n");
  settings.excludePatterns = lines(settings.excludePatterns).map(redactText).join("\n");
  settings.allowedOrigins = normalizeAllowedOrigins(lines(settings.allowedOrigins)).join("\n");
  void chrome.storage.local.set({ [STORAGE_SETTINGS]: settings });
}

function applySettings(settings: Partial<StoredSettings>): void {
  if (typeof settings.allowedOrigins === "string") elements.allowedOrigins.value = settings.allowedOrigins;
  if (typeof settings.includePatterns === "string") elements.includePatterns.value = settings.includePatterns;
  if (typeof settings.excludePatterns === "string") elements.excludePatterns.value = settings.excludePatterns;
  if (typeof settings.orchestratorUrl === "string") elements.orchestratorUrl.value = settings.orchestratorUrl;
  for (const [input, value] of [
    [elements.maxOperations, settings.maxOperations],
    [elements.maxActions, settings.maxActions],
    [elements.maxRuntime, settings.maxRuntime],
    [elements.maxRetries, settings.maxRetries],
    [elements.maxRepeatedStates, settings.maxRepeatedStates]
  ] as const) {
    if (typeof value === "number") input.value = String(value);
  }
}

const explorer = new AiExplorer({
  recording: () => (recordingActive ? recording : null),
  testData: testDataFromUi,
  limits: limitsFromUi,
  client: clientFromUi,
  snapshot: async () => {
    const response = await sendCommand({ source: "webtest-agent-panel", command: "snapshot" });
    if (!response.ok || !response.snapshot) throw new Error(response.error ?? "The page snapshot was unavailable.");
    return response.snapshot;
  },
  execute: (action: AiAction, resolvedValue: string | undefined, stateChangeApproved: boolean) =>
    sendCommand({
      source: "webtest-agent-panel",
      command: "execute",
      action,
      ...(resolvedValue !== undefined ? { resolvedValue } : {}),
      stateChangeApproved
    }),
  approve: (description) => window.confirm(description),
  status: setStatus,
  stopped: render
});

new NetworkRecorder({
  active: () => recordingActive,
  sessionId: () => recording?.sessionId ?? "",
  configuration: () => {
    if (!recording) throw new Error("No active recording configuration.");
    return recording.configuration;
  },
  latestActionId: () => latestActionId,
  currentPageUrl: () => currentPageUrl,
  operationCount: () => recording?.operations.length ?? 0,
  onOperation: (operation) => {
    if (!recording || operation.sessionId !== recording.sessionId) return;
    recording.operations.push(operation);
    schedulePersist();
    render();
  },
  onError: (message) => setStatus(`A network entry was skipped: ${message}`, "warning")
});

chrome.runtime.onMessage.addListener((message: unknown, sender) => {
  if (!isContentEvent(message) || sender.tab?.id !== inspectedTabId) return false;
  if (message.event === "ready") return false;
  if (!recordingActive || !recording || message.action.sessionId !== recording.sessionId) return false;
  const action = safeAction(message.action);
  latestActionId = action.id;
  recording.actions.push(action);
  schedulePersist();
  render();
  return false;
});

chrome.devtools.network.onNavigated.addListener((url) => {
  currentPageUrl = url;
  reloadObserved = true;
  if (recording) recording.metadata.reloadObserved = true;
  elements.reloadNotice.hidden = true;
  if (recordingActive && !isAllowedUrl(url, recording?.configuration.allowedOrigins ?? [])) {
    void stopRecording("Recording stopped because the inspected page left the authorized origins.", "warning");
  } else {
    setStatus("Page reloaded; the action recorder is ready.", "success");
  }
});

function readCurrentPageUrl(): Promise<string> {
  return new Promise((resolve, reject) => {
    chrome.devtools.inspectedWindow.eval("location.href", (result, exceptionInfo) => {
      if (exceptionInfo?.isException || typeof result !== "string") reject(new Error("Could not read the inspected page URL."));
      else resolve(result);
    });
  });
}

async function startRecording(): Promise<void> {
  if (!reloadObserved) throw new Error("Reload the inspected page after opening DevTools before starting a recording.");
  const configuration = configurationFromUi();
  currentPageUrl = currentPageUrl || (await readCurrentPageUrl());
  if (!isAllowedUrl(currentPageUrl, configuration.allowedOrigins)) {
    throw new Error(`The inspected origin (${new URL(currentPageUrl).origin}) is not authorized.`);
  }
  const host = new URL(currentPageUrl).hostname;
  if (!["localhost", "127.0.0.1", "::1"].includes(host) && !/\.(?:test|local|localhost)$/.test(host)) {
    const authorized = window.confirm(
      `Non-production check: confirm that ${new URL(currentPageUrl).origin} is an authorized non-production environment before recording.`
    );
    if (!authorized) throw new Error("Recording cancelled because authorization was not confirmed.");
  }
  explorer.stop();
  const now = new Date().toISOString();
  recording = {
    schemaVersion: RECORDING_SCHEMA_VERSION,
    product: "WebTest Agent",
    sessionId: createId("recording"),
    inspectedTabId,
    startedAt: now,
    configuration,
    actions: [],
    operations: [],
    metadata: {
      extensionVersion: EXTENSION_VERSION,
      captureScope: "one-inspected-tab",
      protocols: ["REST"],
      formats: ["JSON", "form-urlencoded"],
      reloadObserved
    }
  };
  latestActionId = undefined;
  plan = null;
  elements.reviewSection.hidden = true;
  elements.approvePlan.checked = false;
  const response = await sendCommand({ source: "webtest-agent-panel", command: "start", sessionId: recording.sessionId, configuration });
  if (!response.ok) {
    recording = null;
    throw new Error(response.error ?? "The action recorder rejected the session.");
  }
  recordingActive = true;
  saveSettings();
  schedulePersist();
  render();
  setStatus(`Recording authorized traffic from ${new URL(currentPageUrl).origin}.`, "success");
}

async function stopRecording(message = "Recording stopped. Review included calls before planning.", level: "info" | "success" | "warning" | "error" = "info"): Promise<void> {
  explorer.stop();
  if (recordingActive) {
    recordingActive = false;
    if (recording) recording.endedAt = new Date().toISOString();
    try {
      await sendCommand({ source: "webtest-agent-panel", command: "stop" });
    } catch {
      // A navigation can detach the content script; the panel session is still safely stopped.
    }
  }
  schedulePersist();
  render();
  setStatus(message, level);
}

elements.start.addEventListener("click", () => void startRecording().catch((error) => setStatus(friendlyError(error), "error")));
elements.stop.addEventListener("click", () => void stopRecording());
elements.clear.addEventListener("click", () => {
  void (async () => {
    await stopRecording("Recording cleared.");
    try {
      await sendCommand({ source: "webtest-agent-panel", command: "clear" });
    } catch {
      // Clear remains local if the inspected page is unavailable.
    }
    recording = null;
    plan = null;
    latestActionId = undefined;
    elements.reviewSection.hidden = true;
    elements.planEditor.value = "";
    elements.approvePlan.checked = false;
    await chrome.storage.local.remove(STORAGE_RECORDING);
    render();
  })().catch((error) => setStatus(friendlyError(error), "error"));
});
elements.exportJson.addEventListener("click", () => {
  if (!recording) return;
  download(`webtest-recording-${recording.sessionId}.json`, recording, "application/json");
  setStatus("Sanitized versioned recording JSON exported.", "success");
});
elements.exportHar.addEventListener("click", () => {
  if (!recording) return;
  download(`webtest-recording-${recording.sessionId}.har`, recordingToHar(recording), "application/json");
  setStatus("Sanitized HAR exported with included API calls.", "success");
});
elements.aiExplore.addEventListener("click", () => {
  try {
    if (explorer.running) explorer.stop();
    else {
      testDataFromUi();
      limitsFromUi();
      clientFromUi();
      explorer.start();
      setStatus("Bounded AI exploration started. State-changing actions require your approval.", "success");
      render();
    }
  } catch (error) {
    setStatus(friendlyError(error), "error");
  }
});
elements.review.addEventListener("click", () => {
  void (async () => {
    if (!recording) throw new Error("There is no recording to review.");
    if (recordingActive) await stopRecording("Recording stopped for a stable review snapshot.");
    setStatus("The local orchestrator is normalizing the capture and preparing an editable plan…");
    const response = await clientFromUi().review(recording);
    plan = sanitizeReviewPlan(response.plan);
    elements.planEditor.value = JSON.stringify(plan, null, 2);
    elements.reviewSection.hidden = false;
    elements.approvePlan.checked = false;
    elements.generationResult.hidden = true;
    render();
    elements.reviewSection.scrollIntoView({ behavior: "smooth", block: "start" });
    setStatus(response.warnings?.length ? `Plan ready with ${response.warnings.length} warning(s).` : "Editable plan ready for review.", "success");
  })().catch((error) => setStatus(friendlyError(error), "error"));
});
elements.planEditor.addEventListener("input", () => {
  elements.approvePlan.checked = false;
  elements.generate.disabled = true;
});
elements.approvePlan.addEventListener("change", render);
elements.generate.addEventListener("click", () => {
  void (async () => {
    if (!recording || !elements.approvePlan.checked) throw new Error("Approve the reviewed plan before generation.");
    const edited: unknown = JSON.parse(elements.planEditor.value);
    const sanitized = sanitizeReviewPlan(edited);
    plan =
      sanitized && typeof sanitized === "object" && !Array.isArray(sanitized)
        ? ({ ...(sanitized as Record<string, JsonValue>), approved: true } as JsonValue)
        : ({ plan: sanitized, approved: true } as JsonValue);
    setStatus("Generating the approved Java/TestNG project…");
    const result = await clientFromUi().generate(recording.sessionId, plan);
    elements.generationResult.textContent = JSON.stringify(result, null, 2);
    elements.generationResult.hidden = false;
    setStatus(`Generation request completed: ${result.status}.`, "success");
  })().catch((error) => setStatus(friendlyError(error), "error"));
});

for (const input of [
  elements.allowedOrigins,
  elements.includePatterns,
  elements.excludePatterns,
  elements.orchestratorUrl,
  elements.maxOperations,
  elements.maxActions,
  elements.maxRuntime,
  elements.maxRetries,
  elements.maxRepeatedStates
]) {
  input.addEventListener("change", saveSettings);
}

async function initialize(): Promise<void> {
  const stored = await chrome.storage.local.get([STORAGE_SETTINGS, STORAGE_RECORDING]);
  const settings = stored[STORAGE_SETTINGS] as Partial<StoredSettings> | undefined;
  if (settings) applySettings(settings);
  const previous = stored[STORAGE_RECORDING] as Recording | undefined;
  if (
    previous?.schemaVersion === RECORDING_SCHEMA_VERSION &&
    previous.product === "WebTest Agent" &&
    Array.isArray(previous.actions) &&
    Array.isArray(previous.operations)
  ) {
    recording = previous;
    setStatus("Restored the last sanitized recording. Start creates a new session.", "info");
  }
  try {
    currentPageUrl = await readCurrentPageUrl();
  } catch {
    setStatus("Open a normal HTTP(S) page in the inspected tab, then reload it.", "warning");
  }
  render();
}

void initialize().catch((error) => setStatus(friendlyError(error), "error"));
