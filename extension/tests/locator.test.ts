import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { JSDOM } from "jsdom";
import { locatorFor, safeInputValue, secretReference } from "../src/content/locator";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "https://example.test/" });
Object.assign(globalThis, {
  document: dom.window.document,
  location: dom.window.location,
  Element: dom.window.Element,
  HTMLElement: dom.window.HTMLElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLSelectElement: dom.window.HTMLSelectElement,
  HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
  HTMLButtonElement: dom.window.HTMLButtonElement
});

describe("stable locator candidates and secret field values", () => {
  it("prefers explicit test attributes over role and IDs", () => {
    document.body.innerHTML = '<button id="save" data-testid="save-record">Save</button>';
    assert.deepEqual(locatorFor(document.querySelector("button")!), {
      strategy: "test-attribute",
      value: '[data-testid="save-record"]'
    });
  });

  it("uses accessible role and name before label, ID, or CSS", () => {
    document.body.innerHTML = '<label for="full-name">Full name</label><input id="full-name">';
    assert.deepEqual(locatorFor(document.querySelector("input")!), {
      strategy: "role",
      value: "textbox:Full name",
      role: "textbox",
      name: "Full name"
    });
  });

  it("replaces secret and identity values with references", () => {
    document.body.innerHTML = '<input id="username" name="username"><input id="password" type="password"><input id="token" aria-label="API token">';
    const [username, password, token] = [...document.querySelectorAll("input")];
    assert.equal(secretReference(username!), "${TEST_USERNAME}");
    assert.equal(safeInputValue(password!, "never-store-me"), "${TEST_PASSWORD}");
    assert.equal(safeInputValue(token!, "never-store-token"), "${API_TOKEN}");
  });
});
