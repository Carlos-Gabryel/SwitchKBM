// UI do Switch KBM no navegador: sidebar (conectar/capturar) e paginas Controles, Digitacao, Ajustes e Placa.
import { Board } from "./serial.js";
import { Sender } from "./sender.js";
import { Capture } from "./capture.js";
import { Config, Mapper } from "./mapping.js";
import { ProfileStore, DEFAULT_NAME, defaultProfile } from "./profiles.js";
import { BUTTON_ROWS, MOVE_ROWS, ROW_LABELS, SLOTS, profileToRows, rowsToProfile, assignKey, clearRow, checkKey, extras } from "./bindings.js";
import { codeToName, mouseButtonName, displayName } from "./keymap.js";
import { FIRMWARE_VERSION, FIRMWARE_OLD_MSG } from "./version.js";
import { flashFirmware, FirmwareMissing } from "./flash.js";
import { FLAG_CONNECTED } from "./proto.js";
import { TypingEngine } from "./typing.js";
import { TypingUI, paintRange } from "./typing-ui.js";

const WEB_VERSION = "web";

const $ = (id) => document.getElementById(id);
function h(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) e.append(c);
  return e;
}

const store = new ProfileStore();
const board = new Board();
let mapper = null;
let flashing = false;
let listening = null; // captura de tecla na aba Controles
let notice = "";
let currentTab = "controls";
let noticeTimer = null;

const WAIT_TEXT = "Pressione uma tecla…";
const CAPTURE_HINT = "Pressione a tecla (ou clique/roda do mouse). Clique de novo na célula cancela.";
let bindMsg = ""; // mensagem da tabela de teclas (aviso, conflito, dica)

function buildMapper() {
  mapper = new Mapper(new Config(store.load(store.current)), () => {});
}
buildMapper();

const sender = new Sender(board, () => mapper, () => capture.active);
const capture = new Capture({
  getMapper: () => mapper,
  canStart: () => (!board.connected ? "Conecte a placa antes de capturar." : flashing ? "Gravação em andamento." : ""),
  isListening: () => listening !== null,
  onToggleTyping: () => toggleTyping(),
  onTypingChange: (on, reason) => {
    typingUi.setActive(on);
    if (reason) { notice = reason; renderAll(); } else render();
  },
  onTypingKey: (kind, dir) => typingUi.key(kind, dir),
  onChange: (active, reason) => { notice = reason || ""; renderAll(); },
  onAction: (act) => {
    if (act === "sens_up" || act === "sens_down") persistSens();
    render();
  },
});

// ---------- Digitacao ----------
const typingEngine = new TypingEngine();
const typingUi = new TypingUI({ engine: typingEngine, onToggle: () => toggleTyping(), getTab: () => currentTab });
const NEUTRAL = { flags: FLAG_CONNECTED, battery: 200, lx: 0, ly: 0, rx: 0, ry: 0, l2: 0, r2: 0, gyro: [0, 0, 0], accel: [0, 8192, 0] };
// Com a digitacao ativa nada do jogo vaza: so os botoes do motor, resto neutro
sender.stateOverride = (st, now) => (capture.typing ? { ...NEUTRAL, buttons: typingEngine.tick(now) } : null);

function toggleTyping() {
  if (capture.typing) { capture.setTyping(false); return; }
  const why = !board.connected ? "Conecte a placa para usar o modo digitação." : flashing ? "Gravação em andamento." : "";
  if (why) {
    notice = why;
    render();
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => { if (notice === why) { notice = ""; render(); } }, 4000);
    return;
  }
  notice = "";
  capture.setTyping(true);
  render();
}

// Sensibilidade ajustada por F7/F8 fica salva no perfil
function persistSens() {
  const p = store.load(store.current);
  if (mapper.aim_mode === "stick") p.stick_sens = mapper.stick_sens;
  else p.gyro_sensitivity = mapper.sens;
  store.save(store.current, p);
  renderSettings();
}

function saveProfile(p) {
  store.save(store.current, p);
  buildMapper();
  render();
}

// ---------- abas ----------
function showTab(name) {
  currentTab = name;
  for (const b of document.querySelectorAll("#tabs button")) b.setAttribute("aria-selected", String(b.dataset.tab === name));
  for (const s of document.querySelectorAll("main > section")) s.hidden = s.id !== "tab-" + name;
  typingUi.applyVisibility();
}
$("tabs").addEventListener("click", (e) => { const b = e.target.closest("button[data-tab]"); if (b) showTab(b.dataset.tab); });

// ---------- Sidebar: conectar e capturar ----------
$("btn-connect").addEventListener("click", async () => {
  if (board.connected) { capture.stop(""); await board.disconnect(); return; }
  notice = "";
  try {
    await board.connect();
  } catch (e) {
    if (!(e && e.name === "NotFoundError")) notice = board.error || "Falha ao conectar: " + (e && e.message ? e.message : e);
  }
  render();
});
$("btn-capture").addEventListener("click", () => capture.toggle());
$("aim-mode").addEventListener("change", (e) => {
  // o modo de mira e do perfil (como no programa): salva e mantem a mira escolhida
  const q = store.load(store.current);
  q.aim_mode = e.target.value;
  store.save(store.current, q);
  buildMapper();
  mapper._stick_reset();
  renderAll();
});

board.onChange = () => {
  if (board.connected) sender.start();
  else { sender.stop(); capture.stop(board.error); }
  render();
};
sender.onStats = (s) => {
  $("stat-tx").textContent = s.tx + " quadros/s";
  $("stat-gap").textContent = s.gapMax.toFixed(1) + " ms";
  $("stat-drop").textContent = s.dropped + " no último segundo (" + board.dropped + " no total)";
};

function render() {
  const on = board.connected;
  const pill = $("pill");
  const state = flashing ? "rec" : on ? "ok" : "bad";
  pill.className = "status " + state;
  $("pill-title").textContent = flashing ? "Gravando firmware" : on ? "Conectada" : "Desconectada";
  $("pill-detail").textContent = flashing ? "Não feche a página nem desconecte a placa"
    : !on ? "Conecte a placa para jogar"
    : capture.typing ? "Modo digitação · F9 sai"
    : capture.active ? "Capturando · F12 solta" : "F12 captura o mouse";
  $("btn-connect").textContent = on ? "Desconectar" : "Conectar placa";
  $("btn-connect").dataset.icon = on ? "square" : "play";
  $("btn-connect").disabled = !Board.supported() || flashing || capture.active;
  $("btn-capture").disabled = !on || flashing;
  $("btn-capture").textContent = capture.active ? "Liberar" : "Capturar mouse e teclado";
  $("st-board").textContent = on ? "conectada" : "desconectada";
  const fwOld = on && board.fwVersion !== null && board.fwVersion < FIRMWARE_VERSION;
  $("st-fw").textContent = !on ? "—" : board.fwVersion === null ? "aguardando a placa…" : "v" + board.fwVersion;
  $("fw-old").hidden = !fwOld;
  $("fw-old").textContent = FIRMWARE_OLD_MSG;
  $("st-capture").textContent = capture.active ? "ativa" : "liberada";
  $("st-profile").textContent = store.current;
  $("aim-mode").value = mapper.aim_mode;
  const stickMode = mapper.aim_mode === "stick";
  $("card-gyro").hidden = stickMode;
  $("card-stick").hidden = !stickMode;
  syncSens();
  $("cap-accel").hidden = !(capture.raw === false && !accelAck());
  const escBound = !(navigator.keyboard && navigator.keyboard.lock) && "esc" in (store.load(store.current).binds || {});
  $("cap-esc").hidden = !escBound;
  $("cap-esc-fix").disabled = capture.active;
  const err = board.error || notice;
  $("err").hidden = !err;
  $("err").textContent = err;
  $("no-serial").hidden = Board.supported();
  $("btn-flash").disabled = !Board.supported() || flashing || capture.active;
  renderProfileBar();
}

// ---------- Diagnostico da captura ----------
const diag = $("diag");
let diagTimer = null;
function renderDiag() {
  $("diag-stats").textContent = "Mouse: " + capture.mouseEvents + " · Teclas: " + capture.keyEvents + " · Botões: " + capture.buttonEvents +
    " · Fonte: " + capture.moveSource + " · Movimento bruto: " + (capture.raw === null ? "—" : capture.raw ? "sim" : "não") +
    " · Último encerramento: " + (capture.lastEnd || "—");
  $("diag-log").textContent = capture.log.length ? capture.log.join("\n") : "—";
}
diag.addEventListener("toggle", () => {
  clearInterval(diagTimer);
  diagTimer = null;
  if (diag.open) { renderDiag(); diagTimer = setInterval(renderDiag, 500); }
});
$("diag-copy").addEventListener("click", async () => {
  renderDiag();
  const txt = $("diag-stats").textContent + "\n" + $("diag-log").textContent;
  try { await navigator.clipboard.writeText(txt); $("diag-copy").textContent = "Copiado"; }
  catch { $("diag-copy").textContent = "Não foi possível copiar"; }
  setTimeout(() => { $("diag-copy").textContent = "Copiar"; }, 2000);
});

// ---------- Controles ----------
const profileSel = $("profile-select");

function renderProfileBar() {
  const locked = capture.active || flashing;
  profileSel.replaceChildren(...store.names().map((n) => h("option", { value: n, selected: n === store.current }, n)));
  profileSel.disabled = locked;
  for (const id of ["p-new", "p-dup", "p-rename", "p-delete", "p-restore", "p-import", "p-export"]) $(id).disabled = locked;
  $("p-rename").disabled = locked || store.current === DEFAULT_NAME;
  $("p-delete").disabled = locked || store.current === DEFAULT_NAME;
  $("p-note").textContent = store.persistent ? "" : "Aviso: o armazenamento do navegador está indisponível; os perfis valem só até fechar a página (use Exportar).";
}

function resetBinds() { stopListening(); bindMsg = ""; }
function fail(e) { notice = e && e.message ? e.message : String(e); render(); }

profileSel.addEventListener("change", () => {
  resetBinds();
  try { store.switchTo(profileSel.value); buildMapper(); renderAll(); } catch (e) { fail(e); }
});
$("p-new").addEventListener("click", () => {
  const n = prompt("Nome do novo perfil:");
  if (n === null) return;
  resetBinds();
  try { store.create(n); buildMapper(); renderAll(); } catch (e) { fail(e); }
});
$("p-dup").addEventListener("click", () => {
  const n = prompt("Nome da cópia:", store.current + " (cópia)");
  if (n === null) return;
  resetBinds();
  try { store.create(n, store.load(store.current)); buildMapper(); renderAll(); } catch (e) { fail(e); }
});
$("p-restore").addEventListener("click", () => {
  if (!confirm("Restaurar os valores padrão neste perfil?")) return;
  resetBinds();
  saveProfile(defaultProfile()); // mantem o nome do perfil
  renderAll();
});
$("p-rename").addEventListener("click", () => {
  const n = prompt("Novo nome do perfil:", store.current);
  if (n === null) return;
  try { store.rename(store.current, n); renderAll(); } catch (e) { fail(e); }
});
$("p-delete").addEventListener("click", () => {
  if (!confirm('Excluir o perfil "' + store.current + '"?')) return;
  resetBinds();
  try { store.delete(store.current); buildMapper(); renderAll(); } catch (e) { fail(e); }
});
$("p-import").addEventListener("click", () => $("p-file").click());
$("p-file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  resetBinds();
  try { store.importText(await f.text(), f.name); buildMapper(); renderAll(); } catch (err) { fail(err); }
});
$("p-export").addEventListener("click", () => {
  const blob = new Blob([store.exportText(store.current)], { type: "application/json" });
  const a = h("a", { href: URL.createObjectURL(blob), download: store.current + ".json" });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});

// Captura da proxima tecla/botao/roda. accept: {mouse, wheel}; done(nome)
function stopListening() {
  if (!listening) return;
  for (const [t, fn] of listening.fns) window.removeEventListener(t, fn, true);
  listening.btn.classList.remove("listening");
  listening.btn.textContent = listening.label;
  listening = null;
}

function listen(btn, accept, done, id) {
  if (listening && listening.btn === btn) { stopListening(); bindMsg = ""; renderControls(); return; }
  stopListening();
  bindMsg = CAPTURE_HINT;
  const finish = (name) => {
    const err = checkKey(name);
    stopListening();
    if (err) { bindMsg = "Aviso: " + err; renderControls(); return; }
    done(name);
  };
  const fns = [
    ["keydown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.repeat) return;
      const n = codeToName(e.code);
      if (n) finish(n);
      else { bindMsg = "Tecla não suportada (" + (e.code || e.key) + "): o navegador não a entrega ou ela não tem nome no programa. Tente outra."; $("bind-msg").textContent = bindMsg; }
    }],
    ["keyup", (e) => e.preventDefault()],
    ["contextmenu", (e) => e.preventDefault()],
    ["mousedown", (e) => {
      if (listening && listening.btn.contains(e.target)) return; // o clique na celula cancela (tratado no click)
      e.preventDefault();
      const n = mouseButtonName(e.button);
      if (accept.mouse && n) finish(n);
      else { stopListening(); bindMsg = ""; renderControls(); }
    }],
  ];
  if (accept.wheel) {
    fns.push(["wheel", (e) => {
      if (!e.deltaY) return;
      e.preventDefault();
      finish(e.deltaY < 0 ? "wheel_up" : "wheel_down");
    }]);
  }
  for (const [t, fn] of fns) window.addEventListener(t, fn, { capture: true, passive: false });
  listening = { btn, fns, label: btn.textContent, id };
  btn.classList.add("listening");
  btn.textContent = WAIT_TEXT;
  $("bind-msg").textContent = bindMsg;
}

// Salva as linhas editadas no perfil atual (mesmo formato do desktop)
function saveRows(rows) {
  const p = store.load(store.current);
  saveProfile(rowsToProfile(rows, {}, p));
  renderControls();
  renderSettings();
}

function assign(rid, slot, name) {
  const p = store.load(store.current);
  let r;
  try { r = assignKey(profileToRows(p), rid, slot, name); } catch (e) { bindMsg = "Aviso: " + e.message; renderControls(); return; }
  bindMsg = r.moved ? displayName(name) + " saiu de " + ROW_LABELS[r.moved] : "";
  saveRows(r.rows);
}

function renderControls() {
  const p = store.load(store.current);
  const rows = profileToRows(p);
  const locked = capture.active;
  const wasListening = listening ? listening.id : null;
  if (listening) { // a tabela sera refeita: solta os ganchos e recoloca a espera na celula nova
    for (const [t, fn] of listening.fns) window.removeEventListener(t, fn, true);
    listening = null;
  }
  const mkRow = (rid, label, nslots) => {
    const cells = [];
    for (let slot = 0; slot < 2; slot++) {
      if (slot >= nslots) { cells.push(h("span", { class: "cell-gap" })); continue; }
      const k = rows[rid][slot] || "";
      const id = rid + "#" + slot;
      const btn = h("button", { class: "key-btn" + (k ? "" : " empty"), type: "button", disabled: locked, "data-row": rid, "data-slot": slot,
        "aria-label": label + ", tecla " + (slot + 1) + (k ? ": " + displayName(k) : ": vazia") }, k ? displayName(k) : "+");
      btn.addEventListener("click", () => listen(btn, rid.startsWith("move:") ? { mouse: false, wheel: false } : { mouse: true, wheel: true },
        (name) => assign(rid, slot, name), id));
      cells.push(btn);
    }
    const more = extras(rows, rid, displayName);
    const name = h("span", { class: "name" }, h("span", { class: "lbl" }, label), more ? h("small", {}, more) : "");
    const clr = h("button", { class: "icon-btn", type: "button", "data-icon": "x", title: "Limpar a linha", "aria-label": "Limpar a linha " + label, disabled: locked, onclick: () => {
      bindMsg = "";
      saveRows(clearRow(rows, rid));
    } });
    return h("div", { class: "trow" }, name, ...cells, clr);
  };
  $("bind-list").replaceChildren(...BUTTON_ROWS.map(([rid, label]) => mkRow(rid, label, SLOTS)));
  $("move-list").replaceChildren(...MOVE_ROWS.map(([rid, label]) => mkRow(rid, label, 1)));
  if (wasListening) {
    const [rid, slot] = wasListening.split("#");
    const btn = document.querySelector('.key-btn[data-row="' + rid + '"][data-slot="' + slot + '"]');
    if (btn && !btn.disabled) {
      listen(btn, rid.startsWith("move:") ? { mouse: false, wheel: false } : { mouse: true, wheel: true }, (name) => assign(rid, Number(slot), name), wasListening);
      return;
    }
  }
  $("bind-msg").textContent = bindMsg || (mapper.warnings.length ? mapper.warnings.join("; ") : "");
}

// ---------- Sensibilidade (Controles) ----------
// Mesma leitura do programa: giroscopio = deg_per_count * gyro_sensitivity; ao salvar vira deg_per_count com gyro_sensitivity 1.
const SENS = {
  gyro: { range: "sens-range", num: "sens-num", digits: 4, min: 0.005, max: 0.3,
    get: (p) => Math.round(Number(p.deg_per_count) * Number(p.gyro_sensitivity) * 1e4) / 1e4,
    clamp: (x) => Math.max(0.001, x), apply: (q, v) => { q.deg_per_count = Math.round(v * 1e4) / 1e4; q.gyro_sensitivity = 1.0; } },
  stick: { range: "ssens-range", num: "ssens-num", digits: 3, min: 0.1, max: 3,
    get: (p) => Math.round(Number(p.stick_sens) * 1e3) / 1e3,
    clamp: (x) => Math.min(3, Math.max(0.1, x)), apply: (q, v) => { q.stick_sens = Math.round(v * 1e3) / 1e3; } },
  sdz: { range: "sdz-range", num: "sdz-num", digits: 0, min: 0, max: 200,
    get: (p) => Math.round(Number(p.stick_deadzone_comp)),
    clamp: (x) => Math.round(Math.min(200, Math.max(0, x))), apply: (q, v) => { q.stick_deadzone_comp = v; } },
};

function syncSens() {
  const p = store.load(store.current);
  const locked = capture.active || flashing;
  for (const f of Object.values(SENS)) {
    const range = $(f.range), num = $(f.num);
    const v = f.get(p);
    if (document.activeElement !== num) num.value = v.toFixed(f.digits);
    if (document.activeElement !== range) range.value = Math.min(f.max, Math.max(f.min, v));
    range.disabled = num.disabled = locked;
    paintRange(range);
  }
}

for (const f of Object.values(SENS)) {
  const range = $(f.range), num = $(f.num);
  const commit = (raw) => {
    const x = Number(String(raw).replace(",", "."));
    if (!Number.isFinite(x) || raw === "") return;
    const q = store.load(store.current);
    f.apply(q, f.clamp(x));
    const aim = mapper.aim_mode; // F11 pode ter trocado a mira; a edicao nao a desfaz
    store.save(store.current, q);
    buildMapper();
    mapper.aim_mode = aim;
    render();
    renderControls();
    renderSettings();
  };
  range.addEventListener("input", () => { num.value = Number(range.value).toFixed(f.digits); });
  range.addEventListener("change", () => commit(range.value));
  num.addEventListener("change", () => commit(num.value));
}

// ---------- Ajustes ----------
const FIELDS = [
  { k: "gyro_sensitivity", t: "Sensibilidade do giro", hint: "Multiplicador do mouse no modo giro (F7/F8 ajustam).", min: 0.1, max: 5, step: 0.01 },
  { k: "stick_sens", t: "Sensibilidade do analógico", hint: "Multiplicador do mouse no modo analógico.", min: 0.1, max: 5, step: 0.01 },
  { k: "deg_per_count", t: "Graus por contagem do mouse", hint: "Base do giro; ajuste fino.", min: 0.005, max: 0.3, step: 0.005 },
  { k: "stick_deadzone_comp", t: "Compensação da zona morta", hint: "Deflexão mínima do analógico direito (0 a 200).", min: 0, max: 200, step: 1 },
  { k: "walk_scale", t: "Andar devagar", hint: "Escala do analógico esquerdo com a tecla de andar.", min: 0.2, max: 0.9, step: 0.01 },
  { k: "wheel_pulse_ms", t: "Roda: pulso (ms)", hint: "Quanto tempo o botão fica apertado a cada giro da roda.", min: 10, max: 300, step: 5 },
  { k: "arrow_gyro_dps", t: "Setas no modo analógico (graus/s)", hint: "Velocidade do giro pelas setas.", min: 10, max: 360, step: 5 },
  { k: "arrow_stick_scale", t: "Setas no modo giro", hint: "Deflexão do analógico direito pelas setas.", min: 0.1, max: 1, step: 0.01 },
];

function renderSettings() {
  const p = store.load(store.current);
  const locked = capture.active;
  const rows = [];
  const set = (k, v) => { const q = store.load(store.current); q[k] = v; saveProfile(q); };
  for (const [k, t] of [["invert_yaw", "Inverter horizontal"], ["invert_pitch", "Inverter vertical"]]) {
    const cb = h("input", { type: "checkbox", id: "s-" + k, checked: !!p[k], disabled: locked });
    cb.addEventListener("change", () => set(k, cb.checked));
    rows.push(h("div", { class: "setting toggle" }, h("label", { class: "lbl", for: "s-" + k }, t), h("div", { class: "ctl" }, cb)));
  }
  const aim = h("select", { id: "s-aim_mode", disabled: locked },
    h("option", { value: "gyro", selected: p.aim_mode !== "stick" }, "Giroscópio"),
    h("option", { value: "stick", selected: p.aim_mode === "stick" }, "Analógico direito"));
  aim.addEventListener("change", () => set("aim_mode", aim.value));
  rows.push(h("div", { class: "setting" }, h("label", { class: "lbl", for: "s-aim_mode" }, "Modo de mira inicial"), h("div", { class: "ctl" }, aim)));
  for (const f of FIELDS) {
    const v = Number(p[f.k]);
    const range = h("input", { type: "range", min: f.min, max: f.max, step: f.step, value: v, "aria-label": f.t, disabled: locked });
    const num = h("input", { type: "number", min: f.min, max: f.max, step: f.step, value: v, "aria-label": f.t + " (valor)", disabled: locked });
    const apply = (raw) => {
      const x = Number(raw);
      if (!Number.isFinite(x) || raw === "") return;
      set(f.k, Math.min(f.max, Math.max(f.min, x)));
    };
    range.addEventListener("change", () => apply(range.value));
    num.addEventListener("change", () => apply(num.value));
    paintRange(range);
    rows.push(h("div", { class: "setting" }, h("div", { class: "lbl" }, f.t, h("small", {}, f.hint)), h("div", { class: "ctl" }, range, num)));
  }
  $("settings-form").replaceChildren(h("p", { class: "muted" }, "Ajustes do perfil “" + store.current + "”"), ...rows);
}
document.addEventListener("input", (e) => { if (e.target.type === "range") paintRange(e.target); });

// ---------- Placa ----------
$("fw-site").textContent = "v" + FIRMWARE_VERSION;
$("credit-ver").textContent = WEB_VERSION;
const flashLog = [];
function flashLine(s) {
  flashLog.push(s);
  if (flashLog.length > 300) flashLog.splice(0, flashLog.length - 300);
  const pre = $("flash-log");
  pre.hidden = false;
  pre.textContent = flashLog.join("\n");
  pre.scrollTop = pre.scrollHeight;
}

$("btn-flash").addEventListener("click", async () => {
  if (flashing || capture.active) return;
  flashing = true;
  flashLog.length = 0;
  $("flash-log").textContent = "";
  $("flash-progress").replaceChildren();
  const bars = [];
  render();
  const cb = {
    log: flashLine,
    step: (s) => { $("flash-step").textContent = s; },
    progress: (i, n, name, written, total) => {
      if (!bars[i]) {
        const pr = h("progress", { max: 100, value: 0 });
        const lb = h("div", { class: "prog" });
        bars[i] = { pr, lb };
        $("flash-progress").append(lb, pr);
      }
      const pct = total ? Math.floor((100 * written) / total) : 0;
      bars[i].pr.value = pct;
      bars[i].lb.textContent = "Arquivo " + (i + 1) + "/" + n + " — " + name + ": " + pct + "%";
    },
  };
  try {
    await flashFirmware(board, cb);
  } catch (e) {
    if (e instanceof FirmwareMissing) cb.step(e.message);
    else if (e && e.name === "NotFoundError") cb.step("Nenhuma porta escolhida.");
    else {
      cb.step("Falha na gravação: " + (e && e.message ? e.message : e) +
        ". Confira se outra aba ou programa usa a porta e, se preciso, segure BOOT ao conectar.");
      flashLine(String(e && e.stack ? e.stack : e));
    }
  } finally {
    flashing = false;
    render();
  }
});

setInterval(() => {
  if (!board.log.length) return;
  const pre = $("board-log");
  const txt = board.log.join("\n");
  if (pre.textContent !== txt) { pre.textContent = txt; pre.scrollTop = pre.scrollHeight; }
}, 1000);

function renderAll() {
  render();
  renderControls();
  renderSettings();
}
window.addEventListener("pagehide", () => capture.stop(""));
// ganchos para a aba Digitacao
// Avisos da captura: Esc sem trava de teclado e mouse sem movimento bruto
function accelAck() { try { return localStorage.getItem("switchkbm.accelAck") === "1"; } catch { return false; } }
$("cap-accel-ok").addEventListener("click", () => {
  try { localStorage.setItem("switchkbm.accelAck", "1"); } catch { /* so nao lembra */ }
  $("cap-accel").hidden = true;
});
$("cap-esc-fix").addEventListener("click", () => {
  const p = store.load(store.current);
  const free = ["enter", "backspace", "f6"].find((k) => !(k in p.binds) && !Object.values(p.move || {}).includes(k));
  if (!free) { notice = "Sem tecla livre: mude o Esc na página Controles."; renderAll(); return; }
  p.binds[free] = p.binds.esc;
  delete p.binds.esc;
  saveProfile(p);
  notice = "Botão movido do Esc para " + displayName(free) + ".";
  renderAll();
});

window.switchKbm = { board, sender, capture, getMapper: () => mapper, store };

renderAll();
