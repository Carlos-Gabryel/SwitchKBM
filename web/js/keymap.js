// KeyboardEvent.code / botao do mouse -> nome de tecla (os de KEY_NAMES) e nomes de exibicao.

const CODE_TO_NAME = {
  Space: "space", Tab: "tab", Escape: "esc", Enter: "enter", NumpadEnter: "enter",
  Backspace: "backspace", CapsLock: "capslock",
  ShiftLeft: "lshift", ShiftRight: "rshift", ControlLeft: "lctrl", ControlRight: "rctrl",
  AltLeft: "alt", AltRight: "alt",
  Home: "home", End: "end", Insert: "insert", Delete: "delete", PageUp: "pgup", PageDown: "pgdn",
  ArrowLeft: "left", ArrowUp: "up", ArrowRight: "right", ArrowDown: "down",
  Minus: "minus", Equal: "equals", BracketLeft: "lbracket", BracketRight: "rbracket",
  Backslash: "backslash", Semicolon: "semicolon", Quote: "quote", Comma: "comma",
  Period: "period", Slash: "slash", Backquote: "backquote",
  IntlBackslash: "abnt_backslash", IntlRo: "abnt_slash",
  NumpadMultiply: "num_mul", NumpadAdd: "num_add", NumpadSubtract: "num_sub",
  NumpadDecimal: "num_dec", NumpadDivide: "num_div",
};
for (let i = 0; i < 26; i++) CODE_TO_NAME["Key" + String.fromCharCode(65 + i)] = String.fromCharCode(97 + i);
for (let i = 0; i < 10; i++) {
  CODE_TO_NAME["Digit" + i] = String(i);
  CODE_TO_NAME["Numpad" + i] = "num" + i;
}
for (let i = 1; i <= 24; i++) CODE_TO_NAME["F" + i] = "f" + i;

export const MOUSE_BUTTON_NAMES = ["lmb", "mmb", "rmb", "x1", "x2"]; // event.button 0..4

export function codeToName(code) {
  return CODE_TO_NAME[code] ?? null;
}

export function mouseButtonName(button) {
  return MOUSE_BUTTON_NAMES[button] ?? null;
}

// Nomes de KEY_NAMES sem nenhum KeyboardEvent.code correspondente (nenhum)
export const UNREACHABLE_NAMES = [];

const DISPLAY = {
  space: "Espaço", tab: "Tab", esc: "Esc", enter: "Enter", backspace: "Backspace",
  capslock: "Caps Lock", lshift: "Shift Esq.", rshift: "Shift Dir.",
  lctrl: "Ctrl Esq.", rctrl: "Ctrl Dir.", alt: "Alt", home: "Home", end: "End",
  insert: "Insert", delete: "Delete", pgup: "Page Up", pgdn: "Page Down",
  up: "Seta ↑", down: "Seta ↓", left: "Seta ←", right: "Seta →",
  num_mul: "Num *", num_add: "Num +", num_sub: "Num −", num_dec: "Num .", num_div: "Num /",
  minus: "-", equals: "=", lbracket: "[", rbracket: "]", backslash: "\\",
  semicolon: ";", quote: "'", comma: ",", period: ".", slash: "/",
  backquote: "`", abnt_backslash: "\\ (ABNT)", abnt_slash: "/ (ABNT)",
  lmb: "Botão Esq. Mouse", rmb: "Botão Dir. Mouse", mmb: "Botão Meio Mouse",
  x1: "Botão Lateral 1 Mouse", x2: "Botão Lateral 2 Mouse",
  wheel_up: "Roda ↑", wheel_down: "Roda ↓",
};

export function displayName(name) {
  if (!name) return "";
  if (name in DISPLAY) return DISPLAY[name];
  if (/^num\d+$/.test(name)) return "Num " + name.slice(3);
  return name.toUpperCase();
}
