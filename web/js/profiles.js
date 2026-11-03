// Perfis em localStorage, no mesmo formato JSON dos perfis do desktop (tools/kbm/profiles.py).
import { DEFAULT_BINDS, DEFAULT_MOVE } from "./mapping.js";

export const DEFAULT_NAME = "Padrão";
const STORE_KEY = "switchkbm.profiles.v1";
const BAD = /[<>:"/\\|?*\x00-\x1f]/g;

export function defaultProfile() {
  return {
    deg_per_count: 0.05, gyro_sensitivity: 1.0, invert_yaw: true, invert_pitch: true,
    aim_mode: "gyro", stick_sens: 1.0, stick_deadzone_comp: 60, walk_scale: 0.5,
    wheel_pulse_ms: 80, move: { ...DEFAULT_MOVE }, binds: { ...DEFAULT_BINDS },
  };
}

export function cleanName(name) {
  return (name || "").trim().replace(BAD, "").replace(/[. ]+$/, "");
}

// Completa um perfil lido (de arquivo ou storage) com os padroes
function normalize(data) {
  const d = { ...defaultProfile(), ...data };
  d.move = { ...DEFAULT_MOVE, ...((data && data.move) || {}) };
  d.binds = data && data.binds && typeof data.binds === "object" ? { ...data.binds } : { ...DEFAULT_BINDS };
  return d;
}

export class ProfileStore {
  constructor(storage) {
    if (storage === undefined) {
      try { storage = globalThis.localStorage ?? null; } catch { storage = null; }
    }
    this.storage = storage;
    this.persistent = false;
    this.data = { current: DEFAULT_NAME, profiles: {} };
    this._load();
    this._ensureDefault();
  }

  _load() {
    try {
      const raw = this.storage && this.storage.getItem(STORE_KEY);
      if (raw) {
        const d = JSON.parse(raw);
        if (d && typeof d.profiles === "object" && d.profiles) {
          for (const [n, p] of Object.entries(d.profiles)) this.data.profiles[n] = normalize(p);
          if (typeof d.current === "string") this.data.current = d.current;
        }
      }
      this.persistent = !!this.storage;
    } catch {
      this.persistent = false;
    }
  }

  _ensureDefault() {
    if (!this.data.profiles[DEFAULT_NAME]) this.data.profiles[DEFAULT_NAME] = defaultProfile();
    if (!this.data.profiles[this.data.current]) this.data.current = DEFAULT_NAME;
    this._save();
  }

  _save() {
    try {
      if (this.storage) this.storage.setItem(STORE_KEY, JSON.stringify(this.data));
    } catch {
      this.persistent = false;
    }
  }

  names() {
    return Object.keys(this.data.profiles).sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));
  }
  get current() { return this.data.current; }
  exists(name) { return name in this.data.profiles; }
  load(name) { return normalize(this.data.profiles[name]); }

  save(name, data) {
    this.data.profiles[name] = normalize(data);
    this._save();
  }

  switchTo(name) {
    if (!this.exists(name)) throw new Error("perfil não existe");
    this.data.current = name;
    this._save();
  }

  create(name, data = null) {
    name = cleanName(name);
    if (!name) throw new Error("nome inválido");
    if (this.exists(name)) throw new Error("já existe um perfil com esse nome");
    this.data.profiles[name] = data ? normalize(data) : defaultProfile();
    this.data.current = name;
    this._save();
    return name;
  }

  rename(old, name) {
    name = cleanName(name);
    if (old === DEFAULT_NAME) throw new Error('o perfil "' + DEFAULT_NAME + '" não pode ser renomeado');
    if (!name) throw new Error("nome inválido");
    if (name !== old && this.exists(name)) throw new Error("já existe um perfil com esse nome");
    if (name !== old) {
      this.data.profiles[name] = this.data.profiles[old];
      delete this.data.profiles[old];
      if (this.data.current === old) this.data.current = name;
      this._save();
    }
    return name;
  }

  delete(name) {
    if (name === DEFAULT_NAME) throw new Error('o perfil "' + DEFAULT_NAME + '" não pode ser excluído');
    delete this.data.profiles[name];
    if (this.data.current === name) this.data.current = DEFAULT_NAME;
    this._save();
  }

  // Importa o texto de um .json; devolve o nome criado (sufixo se ja existir)
  importText(text, fileName) {
    let d;
    try { d = JSON.parse(text); } catch { throw new Error("arquivo JSON inválido"); }
    if (!d || typeof d !== "object" || Array.isArray(d)) throw new Error("o arquivo não é um perfil");
    const base = cleanName((fileName || "").replace(/\.json$/i, "")) || "Importado";
    let name = base;
    for (let i = 2; this.exists(name); i++) name = base + " (" + i + ")";
    return this.create(name, d);
  }

  exportText(name) {
    return JSON.stringify(this.load(name), null, 2) + "\n";
  }
}
