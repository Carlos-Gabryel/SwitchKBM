// Edicao de teclas por botao do Switch (porta de tools/kbm/bindings.py): linhas, conversao perfil<->linhas, conflitos.
import { KEY_NAMES, MOUSE_NAMES, DEFAULT_BINDS, DEFAULT_MOVE, isReserved } from "./mapping.js";

// [id da linha, rotulo do Switch]. O id e o nome do botao do bridge (posicao estilo PlayStation).
export const BUTTON_ROWS = [
  ["B", "A"], ["A", "B"], ["Y", "X"], ["X", "Y"],
  ["L1", "L"], ["R1", "R"], ["L2", "ZL"], ["R2", "ZR"],
  ["L3", "Clique analógico esq."], ["R3", "Clique analógico dir."],
  ["SELECT", "−"], ["START", "+"], ["SYSTEM", "Home"], ["CAPTURE", "Captura"],
  ["DPAD_UP", "Direcional ↑"], ["DPAD_DOWN", "Direcional ↓"],
  ["DPAD_LEFT", "Direcional ←"], ["DPAD_RIGHT", "Direcional →"],
];
export const MOVE_ROWS = [
  ["move:up", "Frente"], ["move:down", "Trás"], ["move:left", "Esquerda"],
  ["move:right", "Direita"], ["move:walk", "Andar devagar"],
];
export const ROW_LABELS = Object.fromEntries([...BUTTON_ROWS, ...MOVE_ROWS]);
export const BUTTON_IDS = BUTTON_ROWS.map((r) => r[0]);
export const MOVE_IDS = MOVE_ROWS.map((r) => r[0]);
export const SLOTS = 2;

const SETTING_DEFAULTS = {
  aim_mode: "gyro", deg_per_count: 0.05, invert_yaw: true, invert_pitch: true, walk_scale: 0.5,
  wheel_pulse_ms: 80.0, stick_sens: 1.0, stick_deadzone_comp: 60,
};
const KEYS = new Set([...KEY_NAMES, ...MOUSE_NAMES]);
export const validKey = (name) => KEYS.has(name);

// null se a tecla pode ser atribuida; senao a mensagem (a mesma do programa)
export function checkKey(name) {
  if (isReserved(name)) return name.toUpperCase() + " é reservada (hotkey do programa)";
  if (!validKey(name)) return "tecla desconhecida: " + name;
  return null;
}

export function emptyRows() {
  const rows = {};
  for (const r of BUTTON_IDS) rows[r] = ["", ""];
  for (const r of MOVE_IDS) rows[r] = [""];
  return rows;
}

export function profileToRows(data) {
  const rows = emptyRows();
  const binds = data.binds || DEFAULT_BINDS;
  for (const [key, btn] of Object.entries(binds)) {
    const k = key.toLowerCase();
    if (btn in rows && validKey(k) && !isReserved(k)) {
      rows[btn] = rows[btn].filter((x) => x).concat([k]);
      while (rows[btn].length < SLOTS) rows[btn].push("");
    }
  }
  const move = { ...DEFAULT_MOVE, ...(data.move || {}) };
  for (const d of Object.keys(DEFAULT_MOVE)) rows["move:" + d] = [String(move[d] ?? "").toLowerCase()];
  return rows;
}

export function rowsToProfile(rows, settings = {}, base = null) {
  const data = base ? JSON.parse(JSON.stringify(base)) : {};
  for (const [k, v] of Object.entries(SETTING_DEFAULTS)) if (!(k in data)) data[k] = v;
  Object.assign(data, settings);
  const binds = {};
  for (const rid of BUTTON_IDS) for (const k of rows[rid] || []) if (k) binds[k] = rid;
  data.binds = binds;
  data.move = {};
  for (const d of Object.keys(DEFAULT_MOVE)) data.move[d] = (rows["move:" + d] || [""])[0] || "";
  return data;
}

export function findKey(rows, key) {
  for (const [rid, keys] of Object.entries(rows)) {
    const i = keys.indexOf(key);
    if (i >= 0) return [rid, i];
  }
  return null;
}

// Atribui key ao slot; devolve {rows, moved} (moved = linha de onde a tecla saiu). Lanca Error se invalida.
export function assignKey(rows, rowId, slot, key) {
  const err = checkKey(key);
  if (err) throw new Error(err);
  const next = JSON.parse(JSON.stringify(rows));
  if (!(rowId in next)) throw new Error("linha desconhecida: " + rowId);
  const slots = next[rowId];
  while (slots.length <= slot) slots.push("");
  if (slots[slot] === key) return { rows: next, moved: null };
  let moved = null;
  const where = findKey(next, key);
  if (where) { next[where[0]][where[1]] = ""; moved = where[0]; }
  next[rowId][slot] = key;
  return { rows: next, moved };
}

export function clearRow(rows, rowId) {
  const next = JSON.parse(JSON.stringify(rows));
  next[rowId] = next[rowId].map(() => "");
  return next;
}

// "+ F" abaixo do nome quando a linha tem mais de duas teclas (so botoes)
export function extras(rows, rowId, nameOf) {
  const more = (rows[rowId] || []).slice(SLOTS).filter((k) => k).map(nameOf);
  return more.length && BUTTON_IDS.includes(rowId) ? "+ " + more.join(", ") : "";
}
