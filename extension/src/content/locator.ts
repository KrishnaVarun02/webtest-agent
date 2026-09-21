import { stableHash } from "../shared/ids";
import { isSensitiveName, redactText, REDACTED } from "../shared/sanitize";
import type { InteractiveElementSnapshot, LocatorCandidate } from "../shared/schema";

const TEST_ATTRIBUTES = ["data-testid", "data-test", "data-qa", "data-cy"] as const;
const UNSTABLE_ID = /(?:^|[-_])(?:ember|react|vue|generated|auto|random)[-_]?\d|\d{5,}|[0-9a-f]{8}-[0-9a-f-]{27,}/i;

function cssEscape(value: string): string {
  if (globalThis.CSS?.escape) return globalThis.CSS.escape(value);
  return value.replace(/[^A-Za-z0-9_-]/g, (character) => `\\${character.codePointAt(0)?.toString(16)} `);
}

export function implicitRole(element: Element): string {
  const explicit = element.getAttribute("role")?.trim();
  if (explicit) return explicit;
  const tag = element.tagName.toLowerCase();
  if (tag === "a" && element.hasAttribute("href")) return "link";
  if (tag === "button") return "button";
  if (tag === "select") return "combobox";
  if (tag === "textarea") return "textbox";
  if (tag === "summary") return "button";
  if (tag === "img") return "img";
  if (tag === "form") return "form";
  if (tag === "input") {
    const type = (element.getAttribute("type") ?? "text").toLowerCase();
    if (["button", "submit", "reset"].includes(type)) return "button";
    if (type === "checkbox") return "checkbox";
    if (type === "radio") return "radio";
    if (type === "range") return "slider";
    if (type === "number") return "spinbutton";
    return "textbox";
  }
  return tag;
}

export function accessibleName(element: Element): string {
  const ariaLabel = element.getAttribute("aria-label")?.trim();
  if (ariaLabel) return redactText(ariaLabel).slice(0, 160);

  const labelledBy = element.getAttribute("aria-labelledby")?.trim();
  if (labelledBy) {
    const value = labelledBy
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent?.trim() ?? "")
      .filter(Boolean)
      .join(" ");
    if (value) return redactText(value).slice(0, 160);
  }

  if (element instanceof HTMLInputElement || element instanceof HTMLSelectElement || element instanceof HTMLTextAreaElement) {
    const labels = [...(element.labels ?? [])].map((label) => label.textContent?.trim() ?? "").filter(Boolean).join(" ");
    if (labels) return redactText(labels).slice(0, 160);
  }

  const direct =
    element.getAttribute("alt") ??
    element.getAttribute("title") ??
    (element instanceof HTMLInputElement ? element.value || element.placeholder : "") ??
    element.textContent ??
    "";
  return redactText(direct.replace(/\s+/g, " ").trim()).slice(0, 160);
}

function associatedLabel(element: Element): string | undefined {
  if (element instanceof HTMLInputElement || element instanceof HTMLSelectElement || element instanceof HTMLTextAreaElement) {
    const label = [...(element.labels ?? [])].map((entry) => entry.textContent?.trim() ?? "").find(Boolean);
    if (label) return redactText(label).slice(0, 160);
  }
  return undefined;
}

function isStableId(value: string): boolean {
  return Boolean(value && value.length <= 80 && !UNSTABLE_ID.test(value) && !isSensitiveName(value));
}

export function stableCssLocator(element: Element): string {
  const parts: string[] = [];
  let current: Element | null = element;
  while (current && parts.length < 6 && current !== document.documentElement) {
    let part = current.tagName.toLowerCase();
    if (current.id && isStableId(current.id)) {
      parts.unshift(`#${cssEscape(current.id)}`);
      break;
    }
    const parent: Element | null = current.parentElement;
    if (parent) {
      const siblings = [...parent.children].filter((sibling) => sibling.tagName === current?.tagName);
      if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
    }
    parts.unshift(part);
    current = parent;
  }
  return parts.join(" > ");
}

export function locatorFor(element: Element): LocatorCandidate {
  for (const attribute of TEST_ATTRIBUTES) {
    const value = element.getAttribute(attribute)?.trim();
    if (value) {
      const sanitized = isSensitiveName(value) ? REDACTED : redactText(value);
      return { strategy: "test-attribute", value: `[${attribute}="${sanitized.replace(/"/g, "\\\"")}"]` };
    }
  }

  const role = implicitRole(element);
  const name = accessibleName(element);
  if (role && name) return { strategy: "role", value: `${role}:${name}`, role, name };

  const label = associatedLabel(element);
  if (label) return { strategy: "label", value: label, name: label };
  if (element.id && isStableId(element.id)) return { strategy: "id", value: element.id };
  return { strategy: "css", value: stableCssLocator(element) };
}

export function isVisible(element: Element): boolean {
  if (!(element instanceof HTMLElement) || element.hidden || element.getAttribute("aria-hidden") === "true") return false;
  const style = getComputedStyle(element);
  if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
  const rectangle = element.getBoundingClientRect();
  return rectangle.width > 0 && rectangle.height > 0;
}

export function isEnabled(element: Element): boolean {
  return !(element instanceof HTMLButtonElement || element instanceof HTMLInputElement || element instanceof HTMLSelectElement || element instanceof HTMLTextAreaElement)
    ? element.getAttribute("aria-disabled") !== "true"
    : !element.disabled && element.getAttribute("aria-disabled") !== "true";
}

export function elementReference(element: Element): string {
  const locator = locatorFor(element);
  return `el_${stableHash(`${location.origin}|${locator.strategy}|${locator.value}`)}`;
}

export function elementSnapshot(element: Element): InteractiveElementSnapshot {
  return {
    ref: elementReference(element),
    role: implicitRole(element),
    name: accessibleName(element),
    enabled: isEnabled(element)
  };
}

export function secretReference(element: Element): string | undefined {
  const hint = [
    element.getAttribute("name"),
    element.getAttribute("id"),
    element.getAttribute("autocomplete"),
    element.getAttribute("aria-label"),
    accessibleName(element),
    element instanceof HTMLInputElement ? element.type : undefined
  ]
    .filter(Boolean)
    .join("-");
  if (/pass(?:word|wd)?/i.test(hint)) return "${TEST_PASSWORD}";
  if (/(?:api[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|bearer|secret|credential)/i.test(hint) || isSensitiveName(hint)) {
    return "${API_TOKEN}";
  }
  if (/(?:user(?:name)?|login|email)/i.test(hint)) return "${TEST_USERNAME}";
  return undefined;
}

export function safeInputValue(element: Element, value: string): string {
  return secretReference(element) ?? value.replace(/(?:Bearer|Basic)\s+\S+/gi, REDACTED).slice(0, 500);
}
