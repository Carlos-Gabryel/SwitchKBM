// Painel do modo digitacao: textarea, previa do teclado, contadores e velocidade (DOM).
import { PRESETS, MIN_MS, MAX_MS, MAX_PENDING, textDiff, migratePrefs } from "./typing.js";
import { cellId } from "./kb-layout.js";

const PREF_KEY = "switchkbm.typing.v1";
const LABELS = { seguro: "Seguro", normal: "Normal", rapido: "Rápido, pode errar", custom: "Personalizado" };

function loadPrefs() {
  try {
    const d = JSON.parse(localStorage.getItem(PREF_KEY) || "{}");
    return d && typeof d === "object" ? d : {};
  } catch { return {}; }
}
function savePrefs(p) {
  try { localStorage.setItem(PREF_KEY, JSON.stringify(p)); } catch { /* sem armazenamento */ }
}

// Preenche a parte esquerda da trilha do slider (--p) com a cor de destaque
export function paintRange(el) {
  const min = Number(el.min) || 0, max = Number(el.max) || 100, v = Number(el.value);
  const pct = max > min ? Math.min(100, Math.max(0, ((v - min) / (max - min)) * 100)) : 0;
  el.style.setProperty("--p", pct + "%");
}

export class TypingUI {
  // engine: TypingEngine; onToggle(): liga/desliga o modo; getTab(): aba atual
  constructor({ engine, onToggle, getTab }) {
    this.e = engine;
    this.onToggle = onToggle;
    this.getTab = getTab;
    this.on = false;
    this.prefs = migratePrefs(loadPrefs()); // preferencia antiga fora da faixa volta ao padrao
    this.ms = this.prefs.ms;
    this.e.stripAccents = this.prefs.stripAccents;
    this.prev = "";
    this.composing = false;
    this._shownCursor = null;
    this._shownPage = null;
    this._timer = null;
    const $ = (id) => document.getElementById(id);
    this.el = { sec: $("tab-typing"), ta: $("ty-input"), kb: $("ty-kb"), pend: $("ty-pend"),
      cps: $("ty-cps"), skip: $("ty-skip"), msg: $("ty-msg"), presets: $("ty-presets"), range: $("ty-range"),
      num: $("ty-ms"), test: $("ty-test"), toggle: $("ty-toggle"), strip: $("ty-strip"), reopen: $("ty-reopen") };
    this.el.range.min = this.el.num.min = MIN_MS;
    this.el.range.max = this.el.num.max = MAX_MS;
    this._buildKeyboard();
    this._buildPresets();
    this._wire();
    this._applyTiming();
    this.el.strip.checked = this.prefs.stripAccents;
    this.update();
  }

  // Mesma disposicao do console: grade 4x11 + coluna direita; abaixo, abas e Espaco
  _buildKeyboard() {
    const L = this.e.layout, kb = this.el.kb;
    kb.style.setProperty("--cols", L.cols + 1);
    this.keyEls = new Map();
    const mk = (id, cls, span, name) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "kb-key " + cls;
      b.style.gridColumn = "span " + span;
      b.dataset.key = id;
      b.setAttribute("aria-label", "Cursor em " + name);
      this.keyEls.set(id, b);
      return b;
    };
    this.cellEls = [];
    for (let r = 0; r < L.rows; r++) {
      const row = document.createElement("div");
      row.className = "kb-row";
      for (let c = 0; c < L.cols; c++) {
        const b = mk(cellId(r, c), "kb-cell", 1, "linha " + (r + 1) + " coluna " + (c + 1));
        this.cellEls.push([b, r, c]);
        row.append(b);
      }
      const rt = L.right[r];
      const b = mk(rt.id, "kb-side", 1, rt.name);
      b.textContent = rt.label;
      row.append(b);
      kb.append(row);
    }
    const tabs = document.createElement("div");
    tabs.className = "kb-row";
    for (const t of L.tabs) {
      const b = mk(t.id, "kb-tab", 1, "aba " + t.name);
      b.textContent = t.label;
      if (t.page) b.dataset.page = t.page;
      tabs.append(b);
    }
    const sp = document.createElement("div");
    sp.className = "kb-space";
    sp.textContent = "espaço";
    sp.style.gridColumn = "span " + (L.cols + 1 - L.tabs.length);
    tabs.append(sp);
    kb.append(tabs);
  }

  _renderPage() {
    const p = this.e.layout.pages[this.e.page];
    for (const [b, r, c] of this.cellEls) {
      const ch = p.lower[r][c];
      b.textContent = ch ?? "";
      b.classList.toggle("kb-empty", ch === null);
    }
    for (const b of this.el.kb.querySelectorAll(".kb-tab[data-page]")) b.setAttribute("aria-pressed", String(b.dataset.page === this.e.page));
    this._shownPage = this.e.page;
  }

  _buildPresets() {
    this.presetBtns = {};
    for (const name of [...Object.keys(PRESETS), "custom"]) {
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.preset = name;
      b.textContent = name === "custom" ? LABELS[name] : LABELS[name] + " (" + PRESETS[name].hold + " ms)";
      this.presetBtns[name] = b;
      this.el.presets.append(b);
    }
  }

  _wire() {
    const { ta, kb, range, num } = this.el;
    this.el.toggle.addEventListener("click", () => this.onToggle());
    kb.addEventListener("click", (ev) => {
      const b = ev.target.closest("button[data-key]");
      if (!b) return;
      this.e.syncCursor(b.dataset.key);
      if (b.dataset.page) this.e.syncPage(b.dataset.page);
      this.update();
      ta.focus();
    });
    this.el.presets.addEventListener("click", (ev) => {
      const b = ev.target.closest("button[data-preset]");
      if (!b) return;
      this.prefs.preset = b.dataset.preset;
      if (b.dataset.preset !== "custom") this.ms = PRESETS[b.dataset.preset].hold;
      this._applyTiming();
      ta.focus();
    });
    const custom = (v) => {
      const x = Number(v);
      if (!Number.isFinite(x) || v === "") return;
      this.ms = Math.min(MAX_MS, Math.max(MIN_MS, Math.round(x)));
      this.prefs.preset = "custom";
      this._applyTiming();
    };
    range.addEventListener("input", () => custom(range.value));
    num.addEventListener("change", () => custom(num.value));
    this.el.strip.addEventListener("change", () => {
      this.e.stripAccents = this.el.strip.checked;
      this.prefs.stripAccents = this.el.strip.checked;
      savePrefs(this.prefs);
    });
    this.el.reopen.addEventListener("click", () => { this.reopen(); ta.focus(); });
    this.el.test.addEventListener("click", () => { this.e.enqueue("qwertyuiop"); ta.focus(); });
    ta.addEventListener("compositionstart", () => { this.composing = true; });
    ta.addEventListener("compositionend", () => { this.composing = false; this._onInput(); });
    ta.addEventListener("input", (ev) => { if (!ev.isComposing && !this.composing) this._onInput(); });
  }

  _applyTiming() {
    const p = this.prefs.preset;
    const t = p in PRESETS ? PRESETS[p] : { hold: this.ms, gap: this.ms };
    this.e.setTiming(t.hold, t.gap);
    this.ms = this.e.holdMs;
    this.el.range.value = this.el.num.value = this.ms;
    paintRange(this.el.range);
    for (const [n, b] of Object.entries(this.presetBtns)) b.setAttribute("aria-pressed", String(n === p));
    this.prefs.ms = this.ms;
    savePrefs(this.prefs);
  }

  // Teclado reaberto na TV: cursor no 1, fila e campo limpos; a pagina continua
  reopen() {
    this.e.resetKeyboard();
    this.clearText();
    this.el.msg.textContent = "";
    this.update();
  }

  // Texto digitado/colado -> fila (diff contra o valor anterior)
  _onInput() {
    const ta = this.el.ta;
    const { backspaces, insert } = textDiff(this.prev, ta.value);
    for (let i = 0; i < backspaces; i++) this.e.backspaceRequested();
    let chars = [...insert];
    const room = Math.max(0, MAX_PENDING - this.e.pendingCount);
    if (chars.length > room) {
      chars = chars.slice(0, room);
      const keep = [...this.prev].slice(0, [...this.prev].length - backspaces).join("");
      ta.value = keep + chars.join("");
      this.el.msg.textContent = "Limite de " + MAX_PENDING + " caracteres pendentes: o excedente foi descartado.";
    }
    for (const c of chars) this.e.enqueueChar(c);
    this.prev = ta.value;
    this.update();
  }

  clearText() {
    this.el.ta.value = "";
    this.prev = "";
  }

  // Teclas especiais vindas do Capture. Retorna true se tratou.
  key(kind, dir) {
    if (kind === "submit") { this.e.enqueueSubmit(); this.clearText(); }
    else if (kind === "clear") { this.e.clearPending(); this.clearText(); this.el.msg.textContent = ""; }
    else if (kind === "reset") {
      if (this.el.ta.value !== "") return false;
      this.reopen();
    } else if (kind === "arrow") {
      if (this.el.ta.value !== "" || this.e.pendingCount > 0) return false;
      this.e.pressManual(dir);
    } else return false;
    this.update();
    return true;
  }

  // Liga/desliga o overlay e a atualizacao periodica
  setActive(on) {
    if (on === this.on) return;
    this.on = on;
    if (on) {
      this.clearText();
      this.el.msg.textContent = "";
      this.e.resetKeyboard(); // cursor salvo nao vale entre sessoes: teclado abre no 1
      this._timer = setInterval(() => this.update(), 50);
    } else {
      this.e.resetKeyboard();
      this.clearText();
      clearInterval(this._timer);
      this._timer = null;
    }
    this.applyVisibility();
    this.update();
    if (on) this.el.ta.focus();
  }

  applyVisibility() {
    const s = this.el.sec;
    s.classList.toggle("overlay", this.on);
    s.hidden = !(this.on || this.getTab() === "typing");
    this.el.toggle.textContent = this.on ? "Sair (F9)" : "Ligar (F9)";
    this.el.toggle.classList.toggle("primary", !this.on);
    document.body.classList.toggle("typing-open", this.on);
  }

  update() {
    const e = this.e;
    if (e.page !== this._shownPage) this._renderPage();
    if (e.cursor !== this._shownCursor) {
      this.keyEls.get(this._shownCursor)?.classList.remove("cur");
      this.keyEls.get(e.cursor)?.classList.add("cur");
      this._shownCursor = e.cursor;
    }
    this.el.pend.textContent = e.pendingCount;
    this.el.cps.textContent = e.charsPerSecond.toFixed(1);
    this.el.skip.textContent = e.skipped.length + (e.skipped.length ? " (" + [...new Set(e.skipped)].slice(0, 12).join(" ") + ")" : "");
  }
}
