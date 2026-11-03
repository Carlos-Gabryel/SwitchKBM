import { test } from "node:test";
import assert from "node:assert/strict";
import { codeToName, mouseButtonName, displayName, UNREACHABLE_NAMES } from "../js/keymap.js";
import { KEY_NAMES } from "../js/mapping.js";

// codigos conhecidos de KeyboardEvent.code, para varrer todos os nomes
const CODES = [];
for (let i = 0; i < 26; i++) CODES.push("Key" + String.fromCharCode(65 + i));
for (let i = 0; i < 10; i++) CODES.push("Digit" + i, "Numpad" + i);
for (let i = 1; i <= 24; i++) CODES.push("F" + i);
CODES.push("Space", "Tab", "Escape", "Enter", "NumpadEnter", "Backspace", "CapsLock", "ShiftLeft",
  "ShiftRight", "ControlLeft", "ControlRight", "AltLeft", "AltRight", "Home", "End", "Insert", "Delete",
  "PageUp", "PageDown", "ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown", "Minus", "Equal",
  "BracketLeft", "BracketRight", "Backslash", "Semicolon", "Quote", "Comma", "Period", "Slash",
  "Backquote", "IntlBackslash", "IntlRo", "NumpadMultiply", "NumpadAdd", "NumpadSubtract",
  "NumpadDecimal", "NumpadDivide");

test("todo nome de KEY_NAMES tem um codigo (exceto os impossiveis)", () => {
  const got = new Set(CODES.map(codeToName).filter(Boolean));
  const missing = KEY_NAMES.filter((n) => !got.has(n) && !UNREACHABLE_NAMES.includes(n));
  assert.deepEqual(missing, []);
});

test("todo codigo mapeado resulta num nome valido", () => {
  const valid = new Set(KEY_NAMES);
  for (const c of CODES) assert.ok(valid.has(codeToName(c)), c);
});

test("exemplos pedidos", () => {
  const ex = { KeyA: "a", Digit1: "1", F12: "f12", ShiftLeft: "lshift", ControlLeft: "lctrl",
    AltLeft: "alt", AltRight: "alt", Escape: "esc", Minus: "minus", Equal: "equals",
    BracketLeft: "lbracket", IntlBackslash: "abnt_backslash", IntlRo: "abnt_slash",
    Numpad7: "num7", PageUp: "pgup" };
  for (const [c, n] of Object.entries(ex)) assert.equal(codeToName(c), n, c);
  assert.equal(codeToName("MediaPlayPause"), null);
});

test("botoes do mouse", () => {
  assert.deepEqual([0, 1, 2, 3, 4].map(mouseButtonName), ["lmb", "mmb", "rmb", "x1", "x2"]);
  assert.equal(mouseButtonName(7), null);
});

test("nomes de exibicao", () => {
  assert.equal(displayName("space"), "Espaço");
  assert.equal(displayName("num5"), "Num 5");
  assert.equal(displayName("a"), "A");
  assert.equal(displayName("f8"), "F8");
  assert.equal(displayName("abnt_backslash"), "\\ (ABNT)");
  assert.equal(displayName(""), "");
});
