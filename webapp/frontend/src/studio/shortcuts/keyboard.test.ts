import { describe, test, expect } from "vitest";
import { normalizeKey } from "./keyboard";

function makeEvent(init: Partial<KeyboardEventInit & { target?: EventTarget }>): KeyboardEvent {
  const ev = new KeyboardEvent("keydown", {
    key: init.key,
    ctrlKey: init.ctrlKey,
    altKey: init.altKey,
    metaKey: init.metaKey,
    shiftKey: init.shiftKey,
    bubbles: true,
    cancelable: true,
  });
  if (init.target) {
    Object.defineProperty(ev, "target", { value: init.target, writable: false });
  }
  return ev;
}

describe("normalizeKey", () => {
  test("returns plain lowercase for a printable letter", () => {
    expect(normalizeKey(makeEvent({ key: "v" }))).toBe("v");
  });

  test("lowercases uppercase letters (Shift+V → 'v')", () => {
    expect(normalizeKey(makeEvent({ key: "V", shiftKey: true }))).toBe("v");
  });

  test("returns 'Escape' for the Escape key", () => {
    expect(normalizeKey(makeEvent({ key: "Escape" }))).toBe("Escape");
  });

  test("returns 'Delete' for the Delete key", () => {
    expect(normalizeKey(makeEvent({ key: "Delete" }))).toBe("Delete");
  });

  test("returns null when ctrl is held", () => {
    expect(normalizeKey(makeEvent({ key: "s", ctrlKey: true }))).toBeNull();
  });

  test("returns null when meta (cmd) is held", () => {
    expect(normalizeKey(makeEvent({ key: "k", metaKey: true }))).toBeNull();
  });

  test("returns null when alt is held", () => {
    expect(normalizeKey(makeEvent({ key: "v", altKey: true }))).toBeNull();
  });

  test("returns null when target is an INPUT element", () => {
    const input = document.createElement("input");
    expect(normalizeKey(makeEvent({ key: "v", target: input }))).toBeNull();
  });

  test("returns null when target is a TEXTAREA element", () => {
    const ta = document.createElement("textarea");
    expect(normalizeKey(makeEvent({ key: "v", target: ta }))).toBeNull();
  });

  test("returns null when target is a SELECT element", () => {
    const sel = document.createElement("select");
    expect(normalizeKey(makeEvent({ key: "v", target: sel }))).toBeNull();
  });

  test("returns null for unknown multi-char keys", () => {
    expect(normalizeKey(makeEvent({ key: "ArrowLeft" }))).toBeNull();
    expect(normalizeKey(makeEvent({ key: "F1" }))).toBeNull();
  });

  test("returns digit keys verbatim", () => {
    expect(normalizeKey(makeEvent({ key: "1" }))).toBe("1");
    expect(normalizeKey(makeEvent({ key: "3" }))).toBe("3");
  });
});
