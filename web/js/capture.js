// Captura de teclado e mouse: tela cheia + trava de teclado + pointer lock.
import { codeToName, mouseButtonName } from "./keymap.js";

export class Capture {
  // opts: getMapper(), canStart() -> string vazia se ok ou motivo, onChange(active, reason), onAction(act)
  // digitacao: onToggleTyping(), onTypingChange(on, reason), onTypingKey(kind, dir) -> true se tratou
  constructor(opts) {
    this.o = opts;
    this.active = false;
    this._starting = false;
    this.typing = false; // modo digitacao: teclas vao para a textarea, mouse do jogo desligado
    this._relocking = false;
    // diagnostico: registro circular, contadores e motivo do ultimo encerramento
    this.log = [];
    this.mouseEvents = 0; this.keyEvents = 0; this.buttonEvents = 0;
    this.moveSource = ""; // "pointerrawupdate" ou "mousemove"
    this.raw = null; // true/false: pointer lock com movimento bruto; null antes de travar
    this.lastEnd = "";
    this._t0 = performance.now();
    this._startAt = 0;
    this._fs = false; // tela cheia obtida nesta captura
    this._blurTimer = null;
    this._retried = false;
    this._h = {
      keydown: (e) => this._key(e, true),
      keyup: (e) => this._key(e, false),
      mousedown: (e) => this._btn(e, true),
      mouseup: (e) => this._btn(e, false),
      mousemove: (e) => this._move(e),
      pointerrawupdate: (e) => this._move(e),
      wheel: (e) => this._wheel(e),
      contextmenu: (e) => e.preventDefault(),
      pointerlockchange: () => this._lockChange(),
      pointerlockerror: () => this._note("pointerlockerror" + (this.active ? " (ignorado, captura ativa)" : "")),
      fullscreenchange: () => {
        const fs = !!document.fullscreenElement;
        this._note("fullscreenchange fs=" + fs);
        if (this.active && this._fs && !fs) this.stop("Saiu da tela cheia.");
      },
      visibilitychange: () => { if ((this.active || this.typing) && document.hidden) this.stop("A aba ficou em segundo plano."); },
      blur: () => this._blur(),
      focus: () => this._focus(),
    };
    const w = window;
    w.addEventListener("keydown", this._h.keydown, true);
    w.addEventListener("keyup", this._h.keyup, true);
    w.addEventListener("blur", this._h.blur);
    w.addEventListener("focus", this._h.focus);
    document.addEventListener("visibilitychange", this._h.visibilitychange);
    document.addEventListener("pointerlockchange", this._h.pointerlockchange);
    document.addEventListener("pointerlockerror", this._h.pointerlockerror);
    document.addEventListener("fullscreenchange", this._h.fullscreenchange);
    // eventos de mouse so enquanto captura (evita custo e preventDefault fora dela)
    // pointerrawupdate nao espera o quadro da tela (menor atraso); mousemove so como alternativa, nunca os dois
    this.moveSource = "onpointerrawupdate" in window ? "pointerrawupdate" : "mousemove";
    this._mouseEvents = ["mousedown", "mouseup", this.moveSource, "wheel", "contextmenu"];
  }

  // Registro circular de 30 linhas com tempo relativo ao inicio da captura.
  _note(msg) {
    this.log.push(((performance.now() - this._t0) / 1000).toFixed(2) + "s " + msg);
    if (this.log.length > 30) this.log.shift();
  }

  _blur() {
    this._note("blur");
    if (!(this.active || this.typing) || this._blurTimer) return;
    this._blurTimer = setTimeout(() => {
      this._blurTimer = null;
      if (!(this.active || this.typing)) return;
      if (document.hasFocus()) { this._note("foco confirmado, ignorando blur"); return; }
      this.stop("A janela perdeu o foco.");
    }, 600);
  }

  _focus() {
    this._note("focus");
    if (this._blurTimer) { clearTimeout(this._blurTimer); this._blurTimer = null; }
  }

  _lockChange() {
    const locked = !!document.pointerLockElement;
    this._note("pointerlockchange lock=" + locked);
    if (!this.active || this.typing || this._relocking || locked) return;
    if (!this._retried && performance.now() - this._startAt < 600) {
      // soltou logo apos iniciar: tenta travar de novo uma unica vez
      this._retried = true;
      this._relocking = true;
      this._note("lock solto no inicio, tentando de novo");
      this._lock().then(() => {
        this._relocking = false;
        if (!this.active) return;
        if (!document.pointerLockElement) this.stop("Perdeu o bloqueio do mouse.");
      }, () => {
        this._relocking = false;
        if (this.active) this.stop("Perdeu o bloqueio do mouse.");
      });
      return;
    }
    this.stop("Perdeu o bloqueio do mouse.");
  }

  _listen(on) {
    for (const t of this._mouseEvents) {
      if (on) window.addEventListener(t, this._h[t], { capture: true, passive: false });
      else window.removeEventListener(t, this._h[t], true);
    }
  }

  toggle() {
    if (this.typing && !this.active) return; // F12 nao captura durante a digitacao sem captura
    return this.active ? this.stop("") : this.start();
  }

  async _lock() {
    const el = document.documentElement;
    try {
      await el.requestPointerLock({ unadjustedMovement: true });
      this.raw = true;
      this._note("pointer lock com movimento bruto");
    } catch (e) {
      this._note("sem movimento bruto: " + (e && e.name ? e.name : e));
      await el.requestPointerLock();
      this.raw = false;
      this._note("pointer lock com aceleracao do sistema");
    }
  }

  // Liga/desliga o modo digitacao. Sincrono ate o pedido de pointer lock (aproveita o gesto do F9).
  async setTyping(on) {
    if (on === this.typing || this._starting) return;
    try { this.o.getMapper().release_all(); } catch { /* ignora */ }
    if (on) {
      this.typing = true;
      this._listen(false);
      try { if (document.pointerLockElement) document.exitPointerLock(); } catch { /* ignora */ }
      this.o.onTypingChange(true, "");
      return;
    }
    if (!this.active) {
      this.typing = false;
      this.o.onTypingChange(false, "");
      return;
    }
    this._relocking = true;
    try {
      await this._lock();
      if (!document.pointerLockElement) throw new Error("sem pointer lock");
      this._relocking = false;
      if (!this.typing) return; // saiu por outro caminho durante a espera
      this.typing = false;
      this._listen(true);
      this.o.onTypingChange(false, "");
    } catch (e) {
      this._relocking = false;
      this.stop("Não foi possível voltar a travar o mouse: " + (e && e.message ? e.message : e));
    }
  }

  async start() {
    if (this.active || this._starting) return;
    const why = this.o.canStart();
    if (why) { this.o.onChange(false, why); return; }
    this._starting = true;
    const el = document.documentElement;
    this.log = [];
    this._t0 = performance.now();
    this.mouseEvents = this.keyEvents = this.buttonEvents = 0;
    this.raw = null;
    this.lastEnd = "";
    this._fs = false;
    this._retried = false;
    this._note("inicio (movimento: " + this.moveSource + ")");
    try {
      // Mouse primeiro: no Brave a tela cheia gasta o gesto do usuario e o lock seria recusado
      await this._lock();
      if (!document.pointerLockElement) throw new Error("sem pointer lock");
      this.noKeyboardLock = !(navigator.keyboard && navigator.keyboard.lock);
      if (this.noKeyboardLock) {
        this._note("keyboard.lock indisponivel: sem tela cheia (Esc solta a captura)");
      } else {
        // Tela cheia so serve para a trava de teclado (Esc, Tab, Alt)
        try {
          await el.requestFullscreen({ navigationUI: "hide" });
          this._fs = !!document.fullscreenElement;
          this._note("tela cheia ok");
          await navigator.keyboard.lock();
          this._note("keyboard.lock ok");
        } catch (e) { this._note("tela cheia/keyboard.lock falhou: " + (e && e.name ? e.name : e) + " (segue sem)"); }
        await new Promise((r) => setTimeout(r, 100));
        if (!document.pointerLockElement) {
          this._note("tela cheia soltou o lock: tentando de novo");
          await this._lock();
          if (!document.pointerLockElement) throw new Error("a tela cheia soltou o mouse; clique em Capturar de novo");
        }
      }
      this.o.getMapper().release_all();
      this.active = true;
      this._startAt = performance.now();
      this._listen(true);
      this.o.onChange(true, "");
    } catch (e) {
      this._unlock();
      this.lastEnd = "Não foi possível capturar o mouse: " + (e && e.message ? e.message : e);
      this._note("falha ao iniciar: " + this.lastEnd);
      this.o.onChange(false, this.lastEnd);
    } finally {
      this._starting = false;
    }
  }

  stop(reason = "") {
    const was = this.active;
    const wasTyping = this.typing;
    this.active = false;
    this.typing = false;
    this._relocking = false;
    this._fs = false;
    if (this._blurTimer) { clearTimeout(this._blurTimer); this._blurTimer = null; }
    if (was || wasTyping) { this.lastEnd = reason || "Liberado pelo usuário."; this._note("encerrou: " + this.lastEnd); }
    this._listen(false);
    try { this.o.getMapper().release_all(); } catch { /* ignora */ }
    this._unlock();
    if (wasTyping) this.o.onTypingChange(false, was ? "" : reason);
    if (was) this.o.onChange(false, reason);
  }

  _unlock() {
    try { if (document.pointerLockElement) document.exitPointerLock(); } catch { /* ignora */ }
    try { if (navigator.keyboard && navigator.keyboard.unlock) navigator.keyboard.unlock(); } catch { /* ignora */ }
    try { if (document.fullscreenElement) document.exitFullscreen().catch(() => {}); } catch { /* ignora */ }
  }

  _key(e, down) {
    const name = codeToName(e.code);
    if (e.code === "F12") {
      // F12 sempre tratado (nao abre DevTools), capturado ou nao
      e.preventDefault();
      if (down && !e.repeat && !(this.o.isListening && this.o.isListening())) this.toggle();
      return;
    }
    if (this.o.isListening && this.o.isListening()) return; // tela Controles esta capturando uma tecla
    if (e.code === "F9") {
      // F9 como o F12: sempre tratado, capturado ou nao
      e.preventDefault();
      if (down && !e.repeat) this.o.onToggleTyping();
      return;
    }
    if (this.typing) {
      // o navegador digita na textarea; so Enter, Esc, Home e setas sao nossos
      if (!down || e.isComposing) return;
      const arrow = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" }[e.code];
      const kind = e.code === "Enter" || e.code === "NumpadEnter" ? "submit" : e.code === "Escape" ? "clear" : e.code === "Home" ? "reset" : arrow ? "arrow" : "";
      if (kind && this.o.onTypingKey(kind, arrow)) e.preventDefault();
      return;
    }
    if (!this.active) return;
    e.preventDefault();
    if (e.repeat) return;
    this.keyEvents++;
    const m = this.o.getMapper();
    if (!name) return;
    if (down) {
      const act = m.key_down(name, performance.now() / 1000);
      if (act) this.o.onAction(act);
    } else {
      m.key_up(name);
    }
  }

  _btn(e, down) {
    e.preventDefault();
    this.buttonEvents++;
    const name = mouseButtonName(e.button);
    if (name) this.o.getMapper().mouse_button(name, down);
  }

  _move(e) {
    if (e.pointerType && e.pointerType !== "mouse") return;
    this.mouseEvents++;
    this.o.getMapper().mouse_move(e.movementX, e.movementY);
  }

  _wheel(e) {
    e.preventDefault();
    if (!e.deltaY) return;
    this.o.getMapper().wheel(e.deltaY < 0 ? 1 : -1, performance.now() / 1000);
  }
}
