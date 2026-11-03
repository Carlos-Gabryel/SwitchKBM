import { BTN } from "./proto.js";
import { LAYOUT, PAGE_TAB, bfs, cellId, nav, allNodes } from "./kb-layout.js";

const bit = (b) => 1 << b;
// Nomes do CONSOLE -> bit enviado. O firmware troca A/B e X/Y por posicao fisica.
// Sem X (fecha o teclado), L e R: nao existem aqui para ser impossivel usa-los.
export const SWITCH_BTN = {
  A: bit(BTN.B), B: bit(BTN.A), Y: bit(BTN.X),
  "+": bit(BTN.START),
  L3: bit(BTN.L3),
  DPAD_UP: bit(BTN.DPAD_UP), DPAD_DOWN: bit(BTN.DPAD_DOWN),
  DPAD_LEFT: bit(BTN.DPAD_LEFT), DPAD_RIGHT: bit(BTN.DPAD_RIGHT),
};
const DIR_BTN = { up: "DPAD_UP", down: "DPAD_DOWN", left: "DPAD_LEFT", right: "DPAD_RIGHT" };

// Medido: 34/34 perdeu 1 aperto em 250, 42/42 nenhum, 30/30 ou menos perde muito
export const PRESETS = {
  seguro: { hold: 50, gap: 50 },
  normal: { hold: 42, gap: 42 },
  rapido: { hold: 34, gap: 34 },
};
export const DEFAULT_PRESET = "normal";
export const MIN_MS = 25;
export const MAX_MS = 100;
export const MAX_PENDING = 500;
const RATE_WINDOW_MS = 3000;
const MAX_NAV = 4;

// Preferencia salva (possivelmente antiga) -> valida; fora da faixa ou preset inexistente volta ao padrao
export function migratePrefs(p) {
  const d = p && typeof p === "object" ? p : {};
  let preset = d.preset in PRESETS || d.preset === "custom" ? d.preset : DEFAULT_PRESET;
  let ms = Number(d.ms);
  const msOk = Number.isFinite(ms) && ms >= MIN_MS && ms <= MAX_MS;
  if (!msOk) { ms = PRESETS[DEFAULT_PRESET].hold; if (preset === "custom") preset = DEFAULT_PRESET; }
  if (preset in PRESETS) ms = PRESETS[preset].hold;
  return { preset, ms: Math.round(ms), stripAccents: d.stripAccents === true };
}

// Diferenca por prefixo comum (em pontos de codigo): quantos apagar e o que inserir
export function textDiff(prev, next) {
  const a = [...prev], b = [...next];
  let i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i++;
  return { backspaces: a.length - i, insert: b.slice(i).join("") };
}

const COMBINING = new RegExp("[\\u0300-\\u036f]", "g");
const baseOf = (ch) => ch.normalize("NFD").replace(COMBINING, "");

export class TypingEngine {
  constructor(opts = {}) {
    this.layout = opts.layout ?? LAYOUT;
    this.holdMs = opts.holdMs ?? PRESETS[DEFAULT_PRESET].hold;
    this.gapMs = opts.gapMs ?? PRESETS[DEFAULT_PRESET].gap;
    this.stripAccents = !!opts.stripAccents;
    const sc = this.layout.shortcuts;
    this.mask = { space: SWITCH_BTN[sc.space], backspace: SWITCH_BTN[sc.backspace], submit: SWITCH_BTN[sc.submit], shift: SWITCH_BTN[sc.shift], a: SWITCH_BTN.A };
    // indice caractere -> ocorrencias {page, shift, node}
    this.occ = new Map();
    for (const [page, p] of Object.entries(this.layout.pages)) {
      for (const [shift, g] of [[false, p.lower], [true, p.upper]]) {
        if (!g) continue;
        g.forEach((row, r) => row.forEach((ch, c) => {
          if (ch === null) return;
          if (!this.occ.has(ch)) this.occ.set(ch, []);
          this.occ.get(ch).push({ page, shift, node: cellId(r, c) });
        }));
      }
    }
    this._tabBfs = new Map();
    this.cursor = this.layout.start;
    this.page = this.layout.startPage;
    this.skipped = [];
    this._items = [];
    this._steps = [];
    this._cur = null; // passo pressionado: {mask, at, last}
    this._active = null; // item em andamento
    this._releasedAt = -Infinity;
    this._done = [];
    this._hist = []; // "t" digitado / "s" ignorado, para o backspace
    this._lastNow = 0;
    this._nodes = new Set(allNodes(this.layout));
  }

  setTiming(holdMs, gapMs = holdMs) {
    const c = (v) => Math.min(MAX_MS, Math.max(MIN_MS, Math.round(Number(v) || 0)));
    this.holdMs = c(holdMs);
    this.gapMs = c(gapMs);
  }

  // ---- fila ----
  enqueueChar(ch) { this._items.push({ type: "char", ch }); }
  enqueue(text) { for (const ch of text) this.enqueueChar(ch); }
  enqueueSubmit() { this._items.push({ type: "submit" }); }

  backspaceRequested() {
    const last = this._items[this._items.length - 1];
    if (last && last.type === "char") this._items.pop();
    else this._items.push({ type: "backspace" });
  }

  clearPending() {
    this._items = [];
    this._steps = [];
    if (!this._cur) this._active = null; // o passo atual termina sozinho
  }

  // Teclado reaberto na TV: cursor no 1 e fila limpa; o console lembra a pagina
  resetKeyboard() {
    this.clearPending();
    this._hist = [];
    this.cursor = this.layout.start;
  }

  syncCursor(id) { if (this._nodes.has(id)) this.cursor = id; }
  syncPage(page) { if (page in this.layout.pages) this.page = page; }

  // Direcao proibida vira nada: o plano so olha o grafo permitido
  pressManual(direction) {
    if (!(direction in DIR_BTN)) return;
    if (this._items.filter((i) => i.type === "nav").length >= MAX_NAV) return;
    this._items.push({ type: "nav", dir: direction });
  }

  // ---- estado ----
  get pendingCount() {
    return this._items.filter((i) => i.type !== "nav").length + (this._active && this._active.type !== "nav" ? 1 : 0);
  }
  get busy() { return !!this._cur || this._steps.length > 0 || this._items.length > 0; }
  get charsPerSecond() {
    const lo = this._lastNow - RATE_WINDOW_MS;
    this._done = this._done.filter((t) => t > lo);
    return this._done.length / (RATE_WINDOW_MS / 1000);
  }

  // ---- planejamento (preguicoso: um item por vez) ----
  _tab(tab) {
    if (!this._tabBfs.has(tab)) this._tabBfs.set(tab, bfs(tab, this.layout));
    return this._tabBfs.get(tab);
  }

  // Melhor ocorrencia do caractere a partir do estado atual (cursor + pagina)
  _find(ch) {
    const occ = this.occ.get(ch);
    if (!occ) return null;
    const fromCur = bfs(this.cursor, this.layout);
    let best = null;
    for (const o of occ) {
      let pre = null, dirs, cost;
      if (o.page === this.page) {
        dirs = fromCur.path(o.node);
        if (!dirs) continue;
        cost = dirs.length;
      } else {
        const tab = PAGE_TAB[o.page];
        pre = fromCur.path(tab);
        dirs = this._tab(tab).path(o.node);
        if (!pre || !dirs) continue;
        cost = pre.length + 1 + dirs.length;
      }
      cost += (o.shift ? 1 : 0) + 1;
      const key = [cost, o.page === this.page ? 0 : 1, o.shift ? 1 : 0];
      if (!best || key[0] < best.key[0] || (key[0] === best.key[0] && (key[1] < best.key[1] || (key[1] === best.key[1] && key[2] < best.key[2])))) {
        best = { key, o, pre, dirs };
      }
    }
    return best;
  }

  _resolve(ch) {
    const base = baseOf(ch);
    if (this.stripAccents) return this._find(base);
    return this._find(ch) ?? (base !== ch && [...base].length === 1 ? this._find(base) : null);
  }

  _walk(steps, from, dirs) {
    let cur = from;
    for (const d of dirs) {
      cur = nav(cur, d, this.layout);
      steps.push({ mask: SWITCH_BTN[DIR_BTN[d]], cursor: cur });
    }
    return cur;
  }

  _planItem(item) {
    const steps = [];
    if (item.type === "char") {
      if (item.ch === " ") {
        steps.push({ mask: this.mask.space });
        this._hist.push("t");
      } else {
        const r = this._resolve(item.ch);
        if (!r) {
          this.skipped.push(item.ch);
          this._hist.push("s");
        } else {
          let cur = this.cursor;
          if (r.pre) {
            cur = this._walk(steps, cur, r.pre);
            steps.push({ mask: this.mask.a, page: r.o.page }); // A na aba troca a pagina; cursor fica na aba
          }
          this._walk(steps, cur, r.dirs);
          if (r.o.shift) steps.push({ mask: this.mask.shift }); // L3 vale so para a proxima tecla
          steps.push({ mask: this.mask.a });
          this._hist.push("t");
        }
      }
    } else if (item.type === "backspace") {
      if (this._hist[this._hist.length - 1] === "s") this._hist.pop(); // o console nunca recebeu esse caractere
      else { this._hist.pop(); steps.push({ mask: this.mask.backspace }); }
    } else if (item.type === "submit") {
      steps.push({ mask: this.mask.submit, cursor: this.layout.start }); // teclado fecha; a pagina continua
      this._hist = [];
    } else if (item.type === "nav") {
      const to = nav(this.cursor, item.dir, this.layout);
      if (to) steps.push({ mask: SWITCH_BTN[DIR_BTN[item.dir]], cursor: to });
    }
    if (this._hist.length > 1000) this._hist.splice(0, 500);
    if (steps.length) steps[steps.length - 1].last = true;
    return steps;
  }

  _nextStep() {
    while (!this._steps.length) {
      const item = this._items.shift();
      if (!item) { this._active = null; return null; }
      this._active = item;
      this._steps = this._planItem(item);
      if (!this._steps.length) this._active = null;
    }
    return this._steps.shift();
  }

  // Mascara de botoes (bits do firmware) no instante nowMs
  tick(nowMs) {
    this._lastNow = nowMs;
    if (this._cur) {
      if (nowMs - this._cur.at < this.holdMs) return this._cur.mask;
      const s = this._cur;
      this._cur = null;
      this._releasedAt = nowMs; // sempre solta num tick proprio, mesmo atrasado
      if (s.last && s.item && s.item.type !== "nav") this._done.push(nowMs);
      if (!this._steps.length) this._active = null;
      return 0;
    }
    if (nowMs - this._releasedAt < this.gapMs) return 0;
    const step = this._nextStep();
    if (!step) return 0;
    if (step.cursor) this.cursor = step.cursor;
    if (step.page) this.page = step.page;
    this._cur = { mask: step.mask, at: nowMs, last: !!step.last, item: this._active };
    return step.mask;
  }
}

// So para testes: passos planejados de um caractere ({mask, cursor?, page?}) sem rodar o relogio
export function planCharForTest(engine, ch) {
  return engine._planItem({ type: "char", ch });
}
