"""Gerencia perfis (json) e settings.json.

No exe ficam em %LOCALAPPDATA%\SwitchKBM (fora da pasta do exe, que o build recria); no Linux em
$XDG_DATA_HOME/SwitchKBM (~/.local/share/SwitchKBM; se ~/SwitchKBM ja existir, continua nela); em
modo fonte, ao lado deste arquivo."""
import json
import os
import re
import shutil
import sys

try:
    from mapping import DEFAULT_BINDS, DEFAULT_MOVE
except ImportError:  # pragma: no cover
    from .mapping import DEFAULT_BINDS, DEFAULT_MOVE

DEFAULT_NAME = "Padrão"
_BAD = re.compile(r'[<>:"/\|?*\x00-\x1f]')


def data_base():
    """Pasta de dados do programa empacotado."""
    if os.name == "nt":
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "SwitchKBM")
    legacy = os.path.join(os.path.expanduser("~"), "SwitchKBM")
    if os.path.isdir(legacy):
        return legacy
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(xdg, "SwitchKBM")


def app_dir():
    if getattr(sys, "frozen", False):
        base = data_base()
        migrate_data(os.path.dirname(os.path.abspath(sys.executable)), base)
        return base
    return os.path.dirname(os.path.abspath(__file__))


def migrate_data(old, new):
    """Copia perfis/settings de versoes antigas (salvos ao lado do exe) se new ainda nao tem perfis.
    So copia: nunca apaga nada em old."""
    src = os.path.join(old, "profiles")
    dst = os.path.join(new, "profiles")
    if os.path.isdir(dst) and any(f.lower().endswith(".json") for f in os.listdir(dst)):
        return False
    if not os.path.isdir(src) or not any(f.lower().endswith(".json") for f in os.listdir(src)):
        return False
    os.makedirs(dst, exist_ok=True)
    for f in os.listdir(src):
        if f.lower().endswith(".json"):
            shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
    st = os.path.join(old, "settings.json")
    if os.path.isfile(st) and not os.path.exists(os.path.join(new, "settings.json")):
        shutil.copy2(st, os.path.join(new, "settings.json"))
    return True


def default_profile():
    return {
        "deg_per_count": 0.05, "gyro_sensitivity": 1.0, "invert_yaw": True,
        "invert_pitch": True, "aim_mode": "gyro", "stick_sens": 1.0,
        "stick_deadzone_comp": 60, "walk_scale": 0.5, "wheel_pulse_ms": 80,
        "move": dict(DEFAULT_MOVE), "binds": dict(DEFAULT_BINDS),
    }


def clean_name(name):
    name = _BAD.sub("", (name or "").strip()).rstrip(". ")
    return name


class ProfileStore:
    def __init__(self, base=None, legacy_config=None):
        self.base = base or app_dir()
        self.dir = os.path.join(self.base, "profiles")
        self.settings_path = os.path.join(self.base, "settings.json")
        self.legacy_config = legacy_config
        os.makedirs(self.dir, exist_ok=True)
        self.ensure_default()

    def path(self, name):
        return os.path.join(self.dir, name + ".json")

    def names(self):
        return sorted((f[:-5] for f in os.listdir(self.dir) if f.lower().endswith(".json")),
                      key=str.lower)

    def ensure_default(self):
        if self.names():
            return
        data = default_profile()
        if self.legacy_config is None and not getattr(sys, "frozen", False):
            self.legacy_config = os.path.join(self.base, "config.json")
        if self.legacy_config and os.path.exists(self.legacy_config):
            try:
                with open(self.legacy_config, encoding="utf-8") as f:
                    old = json.load(f)
                data.update(old)
                m = dict(DEFAULT_MOVE)
                m.update(old.get("move") or {})
                data["move"] = m
            except (OSError, ValueError):
                pass
        self.save(DEFAULT_NAME, data)

    def load(self, name):
        with open(self.path(name), encoding="utf-8") as f:
            data = json.load(f)
        m = dict(DEFAULT_MOVE)
        m.update(data.get("move") or {})
        data["move"] = m
        return data

    def save(self, name, data):
        tmp = self.path(name) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path(name))

    def exists(self, name):
        return os.path.exists(self.path(name))

    def create(self, name, data=None):
        name = clean_name(name)
        if not name:
            raise ValueError("nome inválido")
        if self.exists(name):
            raise ValueError("já existe um perfil com esse nome")
        self.save(name, data if data is not None else default_profile())
        return name

    def duplicate(self, src, new):
        return self.create(new, self.load(src))

    def rename(self, old, new):
        new = clean_name(new)
        if not new:
            raise ValueError("nome inválido")
        if new != old and self.exists(new):
            raise ValueError("já existe um perfil com esse nome")
        if new != old:
            os.replace(self.path(old), self.path(new))
        return new

    def delete(self, name):
        if len(self.names()) <= 1:
            raise ValueError("não é possível excluir o último perfil")
        os.remove(self.path(name))

    # ---- settings.json ----
    def load_settings(self):
        try:
            with open(self.settings_path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_settings(self, **kw):
        d = self.load_settings()
        d.update(kw)
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
