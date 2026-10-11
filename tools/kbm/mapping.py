"""Logica pura de mapeamento teclado+mouse -> estado de gamepad (sem Win32)."""
import json
import random
from dataclasses import dataclass, field

try:
    from proto import BTN, FLAG_CONNECTED
except ImportError:  # pragma: no cover
    from .proto import BTN, FLAG_CONNECTED

VK_F7, VK_F8, VK_F10, VK_F11, VK_F12 = 0x76, 0x77, 0x79, 0x7A, 0x7B
VK_ALT = 0x12
HOTKEY_VKS = {VK_F7, VK_F8, VK_F10, VK_F11, VK_F12}
VK_W, VK_A, VK_S, VK_D = 0x57, 0x41, 0x53, 0x44

MOUSE_NAMES = ("lmb", "rmb", "mmb", "x1", "x2", "wheel_up", "wheel_down")


def _build_key_names():
    t = {}
    for i in range(26):
        t[chr(ord("a") + i)] = 0x41 + i
    for i in range(10):
        t[str(i)] = 0x30 + i
    for i in range(1, 25):
        t["f%d" % i] = 0x70 + i - 1
    for i in range(10):
        t["num%d" % i] = 0x60 + i
    t.update({
        "num_mul": 0x6A, "num_add": 0x6B, "num_sub": 0x6D, "num_dec": 0x6E, "num_div": 0x6F,
        "minus": 0xBD, "equals": 0xBB, "lbracket": 0xDB, "rbracket": 0xDD,
        "backslash": 0xDC, "semicolon": 0xBA, "quote": 0xDE, "comma": 0xBC,
        "period": 0xBE, "slash": 0xBF, "backquote": 0xC0,
        "abnt_backslash": 0xE2, "abnt_slash": 0xC1,
        "space": 0x20, "tab": 0x09, "esc": 0x1B, "enter": 0x0D, "backspace": 0x08,
        "capslock": 0x14,
        "lshift": 0xA0, "rshift": 0xA1, "lctrl": 0xA2, "rctrl": 0xA3,
        "alt": 0x12, "home": 0x24, "end": 0x23, "insert": 0x2D, "delete": 0x2E,
        "pgup": 0x21, "pgdn": 0x22,
        "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    })
    return t


KEY_NAMES = _build_key_names()
VK_TO_NAME = {v: k for k, v in KEY_NAMES.items()}
RESERVED_NAMES = ("f7", "f8", "f10", "f11", "f12")

_DISPLAY = {
    "space": "Espaço", "tab": "Tab", "esc": "Esc", "enter": "Enter", "backspace": "Backspace",
    "capslock": "Caps Lock", "lshift": "Shift Esq.", "rshift": "Shift Dir.",
    "lctrl": "Ctrl Esq.", "rctrl": "Ctrl Dir.", "alt": "Alt", "home": "Home", "end": "End",
    "insert": "Insert", "delete": "Delete", "pgup": "Page Up", "pgdn": "Page Down",
    "up": "Seta ↑", "down": "Seta ↓", "left": "Seta ←", "right": "Seta →",
    "num_mul": "Num *", "num_add": "Num +", "num_sub": "Num −", "num_dec": "Num .",
    "num_div": "Num /",
    "minus": "-", "equals": "=", "lbracket": "[", "rbracket": "]", "backslash": "\\",
    "semicolon": ";", "quote": "'", "comma": ",", "period": ".", "slash": "/",
    "backquote": "`", "abnt_backslash": "\ (ABNT)", "abnt_slash": "/ (ABNT)",
    "lmb": "Botão Esq. Mouse", "rmb": "Botão Dir. Mouse", "mmb": "Botão Meio Mouse",
    "x1": "Botão Lateral 1 Mouse", "x2": "Botão Lateral 2 Mouse",
    "wheel_up": "Roda ↑", "wheel_down": "Roda ↓",
}


def vk_to_name(vk):
    """Nome da tecla para um VK (None se desconhecido). Alt esq./dir. viram 'alt'."""
    return VK_TO_NAME.get(Mapper.norm_vk(vk))


def display_name(name):
    if not name:
        return ""
    if name in _DISPLAY:
        return _DISPLAY[name]
    if name.startswith("num") and name[3:].isdigit():
        return "Num " + name[3:]
    return name.upper()


def is_reserved(name):
    return name in RESERVED_NAMES


DEFAULT_BINDS = {
    "space": "A", "lctrl": "B", "c": "B", "r": "X", "e": "X", "f": "X",
    "q": "L1", "g": "R1", "lshift": "L3", "v": "R3", "tab": "SELECT",
    "esc": "START", "home": "SYSTEM", "p": "CAPTURE",
    "1": "DPAD_UP", "2": "DPAD_RIGHT", "3": "DPAD_DOWN", "4": "DPAD_LEFT",
    "lmb": "R2", "rmb": "L2", "mmb": "R3", "x1": "DPAD_LEFT", "x2": "DPAD_RIGHT",
    "wheel_up": "Y", "wheel_down": "Y",
}


DEFAULT_MOVE = {"up": "w", "down": "s", "left": "a", "right": "d", "walk": "alt"}


@dataclass
class Config:
    deg_per_count: float = 0.05
    gyro_sensitivity: float = 1.0
    invert_yaw: bool = True
    invert_pitch: bool = True
    aim_mode: str = "gyro"
    stick_gain: float = 0.6
    stick_deadzone_comp: float = 60.0
    walk_scale: float = 0.5
    wheel_pulse_ms: float = 80.0
    accel_noise: int = 40           # ruido no accel (1/8192 G) quando ha giro; evita o Switch aprender drift
    gyro_deadband_units: int = 0    # zera eixo de giro com |unidades| menor que isso
    move: dict = field(default_factory=lambda: dict(DEFAULT_MOVE))
    binds: dict = field(default_factory=lambda: dict(DEFAULT_BINDS))

    @classmethod
    def load(cls, path=None):
        cfg = cls()
        if path:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if k in cls.__dataclass_fields__:
                    setattr(cfg, k, v)
            m = dict(DEFAULT_MOVE)
            m.update(cfg.move or {})
            cfg.move = m
        return cfg


def _sgn(v):
    return (v > 0) - (v < 0)


class Mapper:
    def __init__(self, cfg: Config = None, notify=print):
        self.cfg = cfg or Config()
        self.notify = notify
        self.aim_mode = self.cfg.aim_mode
        self.sens = float(self.cfg.gyro_sensitivity)
        self.pressed = set()        # VKs normalizados
        self.mouse = set()          # "lmb", ...
        self.wheel_until = {}       # "wheel_up" -> instante de expiracao
        self.acc_dx = 0.0
        self.acc_dy = 0.0
        self.combo_start = None
        self.warnings = []
        self._key_binds = {}        # vk -> botao
        self._mouse_binds = {}      # nome -> botao
        self._move_vk = {}
        for d, dflt in DEFAULT_MOVE.items():
            n = str((self.cfg.move or {}).get(d, dflt)).lower()
            if n == "":
                self._move_vk[d] = -1       # sem tecla
                continue
            if n not in KEY_NAMES:
                self.warnings.append("tecla de movimento desconhecida: %s" % n)
                n = dflt
            self._move_vk[d] = KEY_NAMES[n]
        for name, btn in self.cfg.binds.items():
            n = name.lower()
            if btn not in BTN and btn not in ("L2", "R2"):
                self.warnings.append("botao desconhecido: %s" % btn)
                continue
            if n in MOUSE_NAMES:
                self._mouse_binds[n] = btn
            elif n in KEY_NAMES:
                self._key_binds[KEY_NAMES[n]] = btn
            else:
                self.warnings.append("tecla desconhecida: %s" % name)

    # ---- entradas ----
    @staticmethod
    def norm_vk(vk):
        return {0xA4: VK_ALT, 0xA5: VK_ALT}.get(vk, vk)

    def key_down(self, vk, now_s=0.0):
        """Retorna None ou o nome da acao de hotkey (toggle_capture, ...).
        Hotkeys nunca viram botao; so agem na borda de descida."""
        vk = self.norm_vk(vk)
        if vk in HOTKEY_VKS:
            if vk in self.pressed:      # auto-repeat
                return "repeat"
            self.pressed.add(vk)
            if vk == VK_F12:
                return "toggle_capture"
            if vk == VK_F11:
                self.aim_mode = "stick" if self.aim_mode == "gyro" else "gyro"
                self.notify("Modo de mira: %s" % self.aim_mode)
                return "toggle_aim"
            if vk == VK_F10:
                self.combo_start = now_s
                return "cycle_trigger"
            if vk == VK_F8:
                self.sens *= 1.1
                self.notify("Sensibilidade giro: %.3f" % self.sens)
                self.notify("SENS deg_per_count=%.4f" % (self.cfg.deg_per_count * self.sens))
                return "sens_up"
            self.sens /= 1.1
            self.notify("Sensibilidade giro: %.3f" % self.sens)
            self.notify("SENS deg_per_count=%.4f" % (self.cfg.deg_per_count * self.sens))
            return "sens_down"
        self.pressed.add(vk)
        return None

    def key_up(self, vk):
        self.pressed.discard(self.norm_vk(vk))

    def mouse_button(self, name, down):
        (self.mouse.add if down else self.mouse.discard)(name)

    def wheel(self, direction, now_s):
        name = "wheel_up" if direction > 0 else "wheel_down"
        self.wheel_until[name] = now_s + self.cfg.wheel_pulse_ms / 1000.0

    def mouse_move(self, dx, dy):
        self.acc_dx += dx
        self.acc_dy += dy

    def release_all(self):
        self.pressed.clear()
        self.mouse.clear()
        self.wheel_until.clear()
        self.acc_dx = self.acc_dy = 0.0
        self.combo_start = None

    # ---- saida ----
    def _gyro_axis(self, counts, dt):
        """Retorna (unidades, contagens residuais)."""
        dpc = self.cfg.deg_per_count * self.sens
        if counts == 0 or dpc <= 0:
            return 0, 0.0
        units = round(counts * dpc / dt * 16)
        if abs(units) <= 32000:
            return units, 0.0
        units = 32000 * _sgn(units)
        emitted = units * dt / (16 * dpc)
        return units, counts - emitted

    def _stick_axis(self, counts, dt):
        v = counts / dt * self.cfg.stick_gain
        if v:
            v += _sgn(v) * self.cfg.stick_deadzone_comp
        return int(max(-512, min(511, round(v))))

    def build_state(self, now_s, dt_s, captured):
        st = {"flags": 0, "battery": 200, "buttons": 0, "lx": 0, "ly": 0, "rx": 0, "ry": 0,
              "l2": 0, "r2": 0, "gyro": (0, 0, 0), "accel": (0, 8192, 0)}
        if not captured:
            self.acc_dx = self.acc_dy = 0.0
            return st
        st["flags"] = FLAG_CONNECTED
        dt = max(dt_s, 1e-3)
        buttons = 0
        l2 = r2 = 0

        def apply(btn):
            nonlocal buttons, l2, r2
            if btn == "L2":
                l2 = 1023
                buttons |= 1 << BTN["L2_DIGITAL"]
            elif btn == "R2":
                r2 = 1023
                buttons |= 1 << BTN["R2_DIGITAL"]
            else:
                buttons |= 1 << BTN[btn]

        for vk, btn in self._key_binds.items():
            if vk in self.pressed and vk not in HOTKEY_VKS:
                apply(btn)
        for name, btn in self._mouse_binds.items():
            if name in self.mouse or self.wheel_until.get(name, -1.0) > now_s:
                apply(btn)

        # combo F10: SYSTEM 0..60 ms, R2 15..45 ms
        if self.combo_start is not None:
            t = now_s - self.combo_start
            if t > 0.060:
                self.combo_start = None
            else:
                if t >= 0:
                    buttons |= 1 << BTN["SYSTEM"]
                if 0.015 <= t < 0.045:
                    r2 = 1023
                    buttons |= 1 << BTN["R2_DIGITAL"]

        # stick esquerdo (Y positivo = baixo)
        p = self.pressed
        mv = self._move_vk
        x = (mv["right"] in p) - (mv["left"] in p)
        y = (mv["down"] in p) - (mv["up"] in p)
        if x or y:
            mag = 0.7071 if (x and y) else 1.0
            if mv["walk"] in p:
                mag *= self.cfg.walk_scale
            st["lx"] = round((511 if x > 0 else -512) * mag) if x else 0
            st["ly"] = round((511 if y > 0 else -512) * mag) if y else 0

        # mira
        if self.aim_mode == "stick":
            st["rx"] = self._stick_axis(self.acc_dx, dt)
            st["ry"] = self._stick_axis(self.acc_dy, dt)
            self.acc_dx = self.acc_dy = 0.0
        else:
            uy, self.acc_dx = self._gyro_axis(self.acc_dx, dt)
            up, self.acc_dy = self._gyro_axis(self.acc_dy, dt)
            yaw = -uy if self.cfg.invert_yaw else uy
            pitch = -up if self.cfg.invert_pitch else up
            db = self.cfg.gyro_deadband_units
            if db and abs(pitch) < db:
                pitch = 0
            if db and abs(yaw) < db:
                yaw = 0
            st["gyro"] = (pitch, yaw, 0)
            n = int(self.cfg.accel_noise)
            if n > 0 and (pitch or yaw):
                # giro constante + accel perfeito => Switch trata como bias (drift); ruido evita
                st["accel"] = (random.randint(-n, n), 8192 + random.randint(-n, n),
                               random.randint(-n, n))

        st["buttons"] = buttons
        st["l2"] = l2
        st["r2"] = r2
        return st
