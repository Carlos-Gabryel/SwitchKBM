// Logica pura de mapeamento teclado+mouse -> estado de gamepad (porta de tools/kbm/mapping.py).
// Teclas sao NOMES (os de KEY_NAMES), nao VKs. Metodos e campos mantem os nomes do Python.
import { BTN, FLAG_CONNECTED } from "./proto.js";

// round() do Python: metade vai para o par; sempre devolve inteiro (sem -0)
export function pyRound(x) {
  if (!Number.isFinite(x)) return x;
  let r = Math.round(x);
  if (Math.abs(x % 1) === 0.5) r = 2 * Math.round(x / 2);
  return r + 0;
}

export const MOUSE_NAMES = ["lmb", "rmb", "mmb", "x1", "x2", "wheel_up", "wheel_down"];

function buildKeyNames() {
  const n = [];
  for (let i = 0; i < 26; i++) n.push(String.fromCharCode(97 + i));
  for (let i = 0; i < 10; i++) n.push(String(i));
  for (let i = 1; i <= 24; i++) n.push("f" + i);
  for (let i = 0; i < 10; i++) n.push("num" + i);
  n.push("num_mul", "num_add", "num_sub", "num_dec", "num_div",
    "minus", "equals", "lbracket", "rbracket", "backslash", "semicolon", "quote", "comma",
    "period", "slash", "backquote", "abnt_backslash", "abnt_slash",
    "space", "tab", "esc", "enter", "backspace", "capslock",
    "lshift", "rshift", "lctrl", "rctrl", "alt", "home", "end", "insert", "delete", "pgup", "pgdn",
    "left", "up", "right", "down");
  return n;
}
export const KEY_NAMES = buildKeyNames();
const KEY_SET = new Set(KEY_NAMES);

// f9 e reservada aqui para o modo digitacao
export const HOTKEYS = new Set(["f7", "f8", "f9", "f11", "f12"]);
export const RESERVED_NAMES = ["f7", "f8", "f9", "f11", "f12"];
export const isReserved = (name) => HOTKEYS.has(name);

const ARROWS = ["left", "up", "right", "down"];

export const DEFAULT_BINDS = {
  space: "A", lctrl: "B", c: "B", r: "X", e: "X", f: "X",
  q: "L1", g: "R1", lshift: "L3", v: "R3", tab: "SELECT",
  esc: "START", home: "SYSTEM", p: "CAPTURE",
  1: "DPAD_UP", 2: "DPAD_RIGHT", 3: "DPAD_DOWN", 4: "DPAD_LEFT",
  lmb: "R2", rmb: "L2", mmb: "R3", x1: "DPAD_LEFT", x2: "DPAD_RIGHT",
  wheel_up: "Y", wheel_down: "Y",
};
export const DEFAULT_MOVE = { up: "w", down: "s", left: "a", right: "d", walk: "alt" };

const CONFIG_DEFAULTS = {
  deg_per_count: 0.05,
  gyro_sensitivity: 1.0,
  invert_yaw: true,
  invert_pitch: true,
  aim_mode: "gyro",
  max_pitch_deg: 80.0,
  virtual_tilt: false,
  stick_sens: 1.0,
  stick_full_speed: 5000.0,
  stick_max: 0.92,
  stick_curve: 1.0,
  stick_deadzone_comp: 60.0,
  stick_drain_ms: 30.0,
  stick_stop_counts: 0.5,
  walk_scale: 0.5,
  wheel_pulse_ms: 80.0,
  accel_noise: 40,
  gyro_deadband_units: 0,
  arrow_gyro_dps: 90.0,
  arrow_stick_scale: 1.0,
};

export class Config {
  // data: objeto de perfil (so chaves conhecidas sao copiadas, como Config.load)
  constructor(data = null) {
    Object.assign(this, CONFIG_DEFAULTS);
    this.move = { ...DEFAULT_MOVE };
    this.binds = { ...DEFAULT_BINDS };
    if (data) {
      for (const [k, v] of Object.entries(data)) {
        if (k in CONFIG_DEFAULTS) this[k] = v;
        else if (k === "binds" && v) this.binds = { ...v };
      }
      this.move = { ...DEFAULT_MOVE, ...(data.move || {}) };
    }
  }
}

const sgn = (v) => (v > 0) - (v < 0);
const f3 = (v) => v.toFixed(3);

export class Mapper {
  // rng: () => [0,1), injetavel para testes (padrao Math.random)
  constructor(cfg = null, notify = () => {}, rng = Math.random) {
    this.cfg = cfg || new Config();
    this.notify = notify;
    this.rng = rng;
    this.aim_mode = this.cfg.aim_mode;
    this.sens = Number(this.cfg.gyro_sensitivity);
    this.stick_sens = Number(this.cfg.stick_sens);
    this.sbx = 0.0; // saldo de contagens do mouse ainda nao entregues ao analogico
    this.sby = 0.0;
    this.pressed = new Set();
    this.mouse = new Set();
    this.wheel_until = {};
    this.acc_dx = 0.0;
    this.acc_dy = 0.0;
    this.theta = 0.0; // pitch do controle virtual (graus)
    this.warnings = [];
    this._key_binds = new Map(); // tecla -> botao
    this._mouse_binds = new Map();
    this._move_key = {};
    for (const [d, dflt] of Object.entries(DEFAULT_MOVE)) {
      let n = String((this.cfg.move || {})[d] ?? dflt).toLowerCase();
      if (n === "") {
        this._move_key[d] = null; // sem tecla
        continue;
      }
      if (!KEY_SET.has(n)) {
        this.warnings.push("tecla de movimento desconhecida: " + n);
        n = dflt;
      }
      this._move_key[d] = n;
    }
    for (const [name, btn] of Object.entries(this.cfg.binds)) {
      const n = name.toLowerCase();
      if (!(btn in BTN) && btn !== "L2" && btn !== "R2") {
        this.warnings.push("botao desconhecido: " + btn);
        continue;
      }
      if (MOUSE_NAMES.includes(n)) this._mouse_binds.set(n, btn);
      else if (KEY_SET.has(n)) this._key_binds.set(n, btn);
      else this.warnings.push("tecla desconhecida: " + name);
    }
    // setas so miram se nao forem usadas como botao nem como movimento
    const moves = new Set(Object.values(this._move_key));
    this._aim_key = ARROWS.filter((k) => !this._key_binds.has(k) && !moves.has(k));
  }

  // ---- entradas ----
  // Retorna null ou o nome da acao de hotkey. Hotkeys nunca viram botao; so agem na borda de descida.
  key_down(name, now_s = 0.0) {
    if (HOTKEYS.has(name)) {
      if (this.pressed.has(name)) return "repeat"; // auto-repeat
      this.pressed.add(name);
      if (name === "f12") return "toggle_capture";
      if (name === "f9") return "toggle_typing";
      if (name === "f11") {
        this.aim_mode = this.aim_mode === "gyro" ? "stick" : "gyro";
        this._stick_reset();
        this.notify("Modo de mira: " + this.aim_mode);
        return "toggle_aim";
      }
      if (this.aim_mode === "stick") {
        this.stick_sens = name === "f8" ? this.stick_sens * 1.1 : this.stick_sens / 1.1;
        this.notify("Sensibilidade analogico: " + f3(this.stick_sens));
        this.notify("STICKSENS stick_sens=" + f3(this.stick_sens));
        return name === "f8" ? "sens_up" : "sens_down";
      }
      this.sens = name === "f8" ? this.sens * 1.1 : this.sens / 1.1;
      this.notify("Sensibilidade giro: " + f3(this.sens));
      this.notify("SENS deg_per_count=" + (this.cfg.deg_per_count * this.sens).toFixed(4));
      return name === "f8" ? "sens_up" : "sens_down";
    }
    this.pressed.add(name);
    return null;
  }

  key_up(name) {
    this.pressed.delete(name);
  }

  mouse_button(name, down) {
    if (down) this.mouse.add(name);
    else this.mouse.delete(name);
  }

  wheel(direction, now_s) {
    const name = direction > 0 ? "wheel_up" : "wheel_down";
    this.wheel_until[name] = now_s + this.cfg.wheel_pulse_ms / 1000.0;
  }

  mouse_move(dx, dy) {
    this.acc_dx += dx;
    this.acc_dy += dy;
  }

  release_all() {
    this.pressed.clear();
    this.mouse.clear();
    this.wheel_until = {};
    this.acc_dx = this.acc_dy = 0.0;
    this._stick_reset();
    this.theta = 0.0;
  }

  // ---- saida ----
  // Retorna [unidades, contagens residuais]
  _gyro_axis(counts, dt) {
    const dpc = this.cfg.deg_per_count * this.sens;
    if (counts === 0 || dpc <= 0) return [0, 0.0];
    let units = pyRound(((counts * dpc) / dt) * 16);
    if (Math.abs(units) <= 32000) return [units, 0.0];
    units = 32000 * sgn(units);
    const emitted = (units * dt) / (16 * dpc);
    return [units, counts - emitted];
  }

  _stick_reset() {
    this.sbx = this.sby = 0.0;
  }

  // Saldo de contagens do mouse -> analogico direito [rx, ry]; preserva a distancia
  _stick_vec(dx, dy, dt) {
    const cfg = this.cfg;
    this.sbx += dx;
    this.sby += dy;
    const b = Math.hypot(this.sbx, this.sby);
    if (b < cfg.stick_stop_counts) {
      this.sbx = this.sby = 0.0;
      return [0, 0];
    }
    const full = cfg.stick_full_speed / Math.max(this.stick_sens, 0.01);
    const s = Math.min(1.0, b / (cfg.stick_drain_ms / 1000) / full) ** cfg.stick_curve;
    const emit = Math.min(b, s * full * dt); // contagens entregues neste tick
    const ux = this.sbx / b;
    const uy = this.sby / b;
    this.sbx -= ux * emit;
    this.sby -= uy * emit;
    const dz = cfg.stick_deadzone_comp / 512;
    const mag = dz + (cfg.stick_max - dz) * s;
    const rx = pyRound(ux * mag * 512);
    const ry = pyRound(uy * mag * 512);
    return [Math.max(-512, Math.min(511, rx)), Math.max(-512, Math.min(511, ry))];
  }

  // Direcao das setas livres: [x, y], Y positivo = baixo
  _arrow_dir() {
    const v = (k) => (this._aim_key.includes(k) && this.pressed.has(k) ? 1 : 0);
    return [v("right") - v("left"), v("down") - v("up")];
  }

  build_state(now_s, dt_s, captured) {
    const st = {
      flags: 0, battery: 200, buttons: 0, lx: 0, ly: 0, rx: 0, ry: 0,
      l2: 0, r2: 0, gyro: [0, 0, 0], accel: [0, 8192, 0],
    };
    if (!captured) {
      this.acc_dx = this.acc_dy = 0.0;
      this._stick_reset();
      return st;
    }
    st.flags = FLAG_CONNECTED;
    const dt = Math.max(dt_s, 1e-3);
    let buttons = 0;
    let l2 = 0;
    let r2 = 0;
    const apply = (btn) => {
      if (btn === "L2") {
        l2 = 1023;
        buttons |= 1 << BTN.L2_DIGITAL;
      } else if (btn === "R2") {
        r2 = 1023;
        buttons |= 1 << BTN.R2_DIGITAL;
      } else {
        buttons |= 1 << BTN[btn];
      }
    };

    for (const [k, btn] of this._key_binds) {
      if (this.pressed.has(k) && !HOTKEYS.has(k)) apply(btn);
    }
    for (const [name, btn] of this._mouse_binds) {
      if (this.mouse.has(name) || (this.wheel_until[name] ?? -1.0) > now_s) apply(btn);
    }

    // stick esquerdo (Y positivo = baixo)
    const p = this.pressed;
    const mv = this._move_key;
    const has = (k) => k !== null && p.has(k);
    const x = has(mv.right) - has(mv.left);
    const y = has(mv.down) - has(mv.up);
    if (x || y) {
      let mag = x && y ? 0.7071 : 1.0;
      if (has(mv.walk)) mag *= this.cfg.walk_scale;
      st.lx = x ? pyRound((x > 0 ? 511 : -512) * mag) : 0;
      st.ly = y ? pyRound((y > 0 ? 511 : -512) * mag) : 0;
    }

    // mira: mouse e setas dividem giro e analogico direito conforme aim_mode
    const [adx, ady] = this._arrow_dir();
    const stick_mode = this.aim_mode === "stick";
    let uy;
    let up;
    if (stick_mode) {
      [st.rx, st.ry] = this._stick_vec(this.acc_dx, this.acc_dy, dt);
      this.acc_dx = this.acc_dy = 0.0;
      uy = up = 0;
    } else {
      if (adx || ady) {
        const mag = (adx && ady ? 0.7071 : 1.0) * this.cfg.arrow_stick_scale;
        st.rx = adx ? pyRound((adx > 0 ? 511 : -512) * mag) : 0;
        st.ry = ady ? pyRound((ady > 0 ? 511 : -512) * mag) : 0;
      }
      [uy, this.acc_dx] = this._gyro_axis(this.acc_dx, dt);
      [up, this.acc_dy] = this._gyro_axis(this.acc_dy, dt);
    }
    if (stick_mode && (adx || ady)) {
      // mesma convencao do mouse: direita = dx positivo, cima = dy negativo
      const r = this.cfg.arrow_gyro_dps * 16;
      const f = adx && ady ? 0.7071 : 1.0;
      uy += pyRound(adx * r * f);
      up += pyRound(ady * r * f);
    }
    uy = Math.max(-32000, Math.min(32000, uy));
    up = Math.max(-32000, Math.min(32000, up));
    let yaw = this.cfg.invert_yaw ? -uy : uy;
    let pitch = this.cfg.invert_pitch ? -up : up;
    const db = this.cfg.gyro_deadband_units;
    if (db && Math.abs(pitch) < db) pitch = 0;
    if (db && Math.abs(yaw) < db) yaw = 0;
    // Controle virtual coerente: integra o pitch (theta) e manda a gravidade inclinada no accel.
    // Sem virtual_tilt o controle fica deitado (theta so acumula, sem limite).
    const lim = this.cfg.virtual_tilt ? this.cfg.max_pitch_deg : Infinity;
    const new_theta = Math.max(-lim, Math.min(lim, this.theta + (pitch / 16.0) * dt));
    pitch = dt > 0 ? pyRound(((new_theta - this.theta) / dt) * 16) : 0;
    this.theta = new_theta;
    const tilt = this.cfg.virtual_tilt ? this.theta * (Math.PI / 180) : 0.0;
    const c = Math.cos(tilt);
    const sn = Math.sin(tilt);
    st.gyro = [pitch, pyRound(yaw * c), pyRound(-yaw * sn)];
    let gx = 0.0;
    let gy = 8192 * c;
    let gz = -8192 * sn;
    const n = Math.trunc(this.cfg.accel_noise);
    if (n > 0 && (pitch || yaw)) {
      // giro constante + accel perfeito => Switch trata como bias (drift); ruido evita
      const ri = () => -n + Math.floor(this.rng() * (2 * n + 1));
      gx += ri();
      gy += ri();
      gz += ri();
    }
    st.accel = [pyRound(gx), pyRound(gy), pyRound(gz)];

    st.buttons = buttons >>> 0;
    st.l2 = l2;
    st.r2 = r2;
    return st;
  }
}
