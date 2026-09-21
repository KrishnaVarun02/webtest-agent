import { accessibleName, elementReference, elementSnapshot, isEnabled, isVisible, locatorFor, safeInputValue } from "./locator";
import { createId, stableHash } from "../shared/ids";
import type { CommandResponse, ContentEvent, PanelCommand } from "../shared/messages";
import type { AiAction, CaptureConfiguration, PageSnapshot, UiAction, UiActionType } from "../shared/schema";
import { redactText, sanitizeUrl } from "../shared/sanitize";

const INTERACTIVE_SELECTOR = "a[href],button,input,select,textarea,[role],[tabindex]:not([tabindex='-1'])";
const BLOCKED_AI_TARGET = /(?:captcha|purchase|checkout|payment|pay now|buy now|delete account|close account|remove account|\bupload\b|become admin|elevate privilege|bypass)/i;
const STATE_CHANGING_TARGET = /(?:create|add|save|update|submit|send|publish|archive|delete|remove|confirm|approve|upload|register|sign up)/i;

let active = false;
let sessionId = "";
let configuration: CaptureConfiguration | undefined;
let lastActivityAt = 0;
let waitEmitted = false;
let lastUrl = location.href;
let pageFingerprint = "";
let pageChangeTimer: number | undefined;
const inputTimers = new Map<Element, number>();
const referencedElements = new Map<string, Element>();
const aiValueReferences = new WeakMap<Element, string>();

function originAuthorized(): boolean {
  return Boolean(configuration?.allowedOrigins.includes(location.origin));
}

function emit(event: ContentEvent): void {
  try {
    chrome.runtime.sendMessage(event, () => void chrome.runtime.lastError);
  } catch {
    // The extension may be reloaded while the inspected page is still open.
  }
}

function record(type: UiActionType, element?: Element, value?: string, metadata?: UiAction["metadata"]): void {
  if (!active || !originAuthorized()) return;
  const action: UiAction = {
    id: createId("action"),
    sessionId,
    type,
    timestamp: new Date().toISOString(),
    pageUrl: sanitizeUrl(location.href),
    ...(element ? { locator: locatorFor(element) } : {}),
    ...(value !== undefined ? { value } : {}),
    ...(metadata ? { metadata } : {})
  };
  lastActivityAt = Date.now();
  waitEmitted = false;
  emit({ source: "webtest-agent-content", event: "action", action });
}

function actionTarget(event: Event): Element | undefined {
  const target = event.composedPath().find((entry): entry is Element => entry instanceof Element);
  return target?.closest(INTERACTIVE_SELECTOR) ?? target;
}

document.addEventListener(
  "click",
  (event) => {
    const target = actionTarget(event);
    if (!target) return;
    const anchor = target.closest("a[href]") as HTMLAnchorElement | null;
    record("click", target, undefined, anchor ? { targetUrl: sanitizeUrl(anchor.href) } : undefined);
  },
  true
);

document.addEventListener(
  "input",
  (event) => {
    if (!active) return;
    const target = actionTarget(event);
    if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) return;
    const existing = inputTimers.get(target);
    if (existing) clearTimeout(existing);
    inputTimers.set(
      target,
      window.setTimeout(() => {
        inputTimers.delete(target);
        const valueReference = aiValueReferences.get(target);
        aiValueReferences.delete(target);
        record("input", target, valueReference ?? safeInputValue(target, target.value));
      }, 300)
    );
  },
  true
);

document.addEventListener(
  "change",
  (event) => {
    const target = actionTarget(event);
    if (target instanceof HTMLSelectElement) {
      const valueReference = aiValueReferences.get(target);
      aiValueReferences.delete(target);
      record("select", target, valueReference ?? safeInputValue(target, target.value));
    }
  },
  true
);

document.addEventListener(
  "submit",
  (event) => {
    const target = event.target instanceof Element ? event.target : undefined;
    record("submit", target, undefined, { stateChanging: true });
  },
  true
);

addEventListener("popstate", () => record("back", undefined, undefined, { destination: sanitizeUrl(location.href) }));
addEventListener("hashchange", () => record("navigation", undefined, undefined, { destination: sanitizeUrl(location.href) }));

function currentFingerprint(): string {
  const main = document.querySelector("main,[role='main']")?.textContent?.replace(/\s+/g, " ").trim().slice(0, 300) ?? "";
  const heading = document.querySelector("h1")?.textContent?.trim() ?? "";
  return stableHash(`${location.href}|${document.title}|${heading}|${main}`);
}

function observePageChange(): void {
  if (!active) return;
  if (pageChangeTimer) clearTimeout(pageChangeTimer);
  pageChangeTimer = window.setTimeout(() => {
    const nextFingerprint = currentFingerprint();
    if (nextFingerprint !== pageFingerprint) {
      pageFingerprint = nextFingerprint;
      record("page_change", undefined, undefined, { stateHash: nextFingerprint, title: redactText(document.title) });
    }
  }, 400);
}

const observer = new MutationObserver(observePageChange);
const startObserver = (): void => {
  if (document.documentElement) observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true });
};
if (document.documentElement) startObserver();
else document.addEventListener("DOMContentLoaded", startObserver, { once: true });

setInterval(() => {
  if (!active) return;
  if (location.href !== lastUrl) {
    const previousUrl = lastUrl;
    lastUrl = location.href;
    record("navigation", undefined, undefined, { previousUrl: sanitizeUrl(previousUrl), destination: sanitizeUrl(location.href) });
  }
  if (!waitEmitted && lastActivityAt > 0 && Date.now() - lastActivityAt >= 2_000) {
    waitEmitted = true;
    record("wait", undefined, undefined, { durationMs: Date.now() - lastActivityAt });
    waitEmitted = true;
  }
}, 500);

function snapshotPage(): PageSnapshot {
  referencedElements.clear();
  const interactiveElements = [...document.querySelectorAll(INTERACTIVE_SELECTOR)]
    .filter(isVisible)
    .slice(0, 100)
    .map((element) => {
      let ref = elementReference(element);
      let suffix = 1;
      while (referencedElements.has(ref)) {
        suffix += 1;
        ref = `${elementReference(element)}_${suffix}`;
      }
      referencedElements.set(ref, element);
      return { ...elementSnapshot(element), ref };
    });
  const headings = [...document.querySelectorAll("h1,h2,h3,[role='heading']")]
    .filter(isVisible)
    .map((heading) => redactText(heading.textContent?.replace(/\s+/g, " ").trim() ?? ""))
    .filter(Boolean)
    .slice(0, 30);
  return { currentUrl: sanitizeUrl(location.href), title: redactText(document.title), headings, interactiveElements };
}

function isStateChanging(action: AiAction, element?: Element): boolean {
  if (action.type !== "click") return false;
  const targetText = element ? `${accessibleName(element)} ${element.getAttribute("type") ?? ""}` : "";
  return STATE_CHANGING_TARGET.test(targetText);
}

async function executeAction(command: Extract<PanelCommand, { command: "execute" }>): Promise<CommandResponse> {
  const { action } = command;
  if (!active || !originAuthorized()) return { ok: false, error: "Recording is inactive or the current origin is not authorized." };
  if (action.type === "stop") return { ok: true };
  if (action.type === "wait") {
    await new Promise((resolve) => setTimeout(resolve, Math.min(Math.max(action.durationMs, 0), 10_000)));
    return { ok: true };
  }
  if (action.type === "scroll") {
    const amount = Math.min(Math.max(action.amount ?? 600, 1), 1_500);
    scrollBy({ top: action.direction === "down" ? amount : -amount, behavior: "smooth" });
    return { ok: true };
  }
  if (action.type === "back") {
    history.back();
    return { ok: true };
  }
  if (action.type === "navigate") {
    let target: URL;
    try {
      target = new URL(action.url, location.href);
    } catch {
      return { ok: false, error: "The requested navigation URL is invalid." };
    }
    if (target.origin !== location.origin) return { ok: false, error: "AI navigation must remain on the current origin." };
    if (BLOCKED_AI_TARGET.test(target.href)) return { ok: false, error: "The requested navigation is prohibited by the exploration policy." };
    location.assign(target.href);
    return { ok: true };
  }

  const element = referencedElements.get(action.elementRef);
  if (!element || !isVisible(element)) return { ok: false, error: "The selected element reference is missing or no longer visible." };
  if (!isEnabled(element)) return { ok: false, error: "The selected element is disabled." };
  const anchorUrl = element.closest("a[href]") instanceof HTMLAnchorElement ? element.closest<HTMLAnchorElement>("a[href]")?.href ?? "" : "";
  const targetDescription = `${accessibleName(element)} ${element.getAttribute("name") ?? ""} ${element.getAttribute("type") ?? ""} ${anchorUrl}`;
  if (BLOCKED_AI_TARGET.test(targetDescription)) return { ok: false, error: "The selected action is prohibited by the exploration policy." };
  if (element instanceof HTMLInputElement && element.type === "file") return { ok: false, error: "AI exploration cannot upload files." };

  const stateChanged = isStateChanging(action, element);
  if (stateChanged && !command.stateChangeApproved) {
    return { ok: false, error: "This action requires explicit user approval.", stateChanged: true };
  }
  if (action.type === "click") {
    (element as HTMLElement).click();
    return { ok: true, stateChanged };
  }
  if (action.type === "fill") {
    if (!(element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement)) {
      return { ok: false, error: "The selected element cannot be filled." };
    }
    if (command.resolvedValue === undefined) return { ok: false, error: "No local test-data value was supplied." };
    if (!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(action.valueRef)) return { ok: false, error: "The test-data reference is invalid." };
    element.focus();
    aiValueReferences.set(element, `\${${action.valueRef}}`);
    element.value = command.resolvedValue.slice(0, 10_000);
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    return { ok: true };
  }
  if (!(element instanceof HTMLSelectElement)) return { ok: false, error: "The selected element is not a select control." };
  if (command.resolvedValue === undefined) return { ok: false, error: "No local test-data value was supplied." };
  if (!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(action.valueRef)) return { ok: false, error: "The test-data reference is invalid." };
  const option = [...element.options].find((entry) => entry.value === command.resolvedValue || entry.label === command.resolvedValue);
  if (!option) return { ok: false, error: "The supplied value is not an available option." };
  aiValueReferences.set(element, `\${${action.valueRef}}`);
  element.value = option.value;
  element.dispatchEvent(new Event("change", { bubbles: true }));
  return { ok: true };
}

async function handleCommand(command: PanelCommand): Promise<CommandResponse> {
  if (command.source !== "webtest-agent-panel") return { ok: false, error: "Unknown message source." };
  if (command.command === "start") {
    if (!command.configuration.allowedOrigins.includes(location.origin)) {
      return { ok: false, error: `The current origin (${location.origin}) is not in the allowed-origin list.` };
    }
    active = true;
    sessionId = command.sessionId;
    configuration = command.configuration;
    lastActivityAt = Date.now();
    waitEmitted = false;
    lastUrl = location.href;
    pageFingerprint = currentFingerprint();
    record("page_change", undefined, undefined, { stateHash: pageFingerprint, title: redactText(document.title), initial: true });
    return { ok: true };
  }
  if (command.command === "stop") {
    active = false;
    for (const timer of inputTimers.values()) clearTimeout(timer);
    inputTimers.clear();
    return { ok: true };
  }
  if (command.command === "clear") {
    sessionId = "";
    referencedElements.clear();
    return { ok: true };
  }
  if (command.command === "snapshot") return { ok: true, snapshot: snapshotPage() };
  return executeAction(command);
}

chrome.runtime.onMessage.addListener((message: unknown, _sender, sendResponse) => {
  if (!message || typeof message !== "object" || (message as { source?: string }).source !== "webtest-agent-panel") return false;
  void handleCommand(message as PanelCommand).then(sendResponse, (error: unknown) => {
    sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) } satisfies CommandResponse);
  });
  return true;
});

emit({ source: "webtest-agent-content", event: "ready", pageUrl: location.href });
