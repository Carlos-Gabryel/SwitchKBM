"""Logica pura de edicao de teclas (sem UI): linhas do menu, conversao perfil<->linhas, conflitos."""
import copy

try:
    from mapping import (KEY_NAMES, MOUSE_NAMES, DEFAULT_BINDS, DEFAULT_MOVE, RESERVED_NAMES,
                         is_reserved)
except ImportError:  # pragma: no cover
    from .mapping import (KEY_NAMES, MOUSE_NAMES, DEFAULT_BINDS, DEFAULT_MOVE, RESERVED_NAMES,
                          is_reserved)

# (id da linha, rotulo Switch). O id e o nome do botao do bridge (posicao estilo PlayStation).
BUTTON_ROWS = [
    ("B", "A"), ("A", "B"), ("Y", "X"), ("X", "Y"),
    ("L1", "L"), ("R1", "R"), ("L2", "ZL"), ("R2", "ZR"),
    ("L3", "Clique analógico esq."), ("R3", "Clique analógico dir."),
    ("SELECT", "−"), ("START", "+"), ("SYSTEM", "Home"), ("CAPTURE", "Captura"),
    ("DPAD_UP", "Direcional ↑"), ("DPAD_DOWN", "Direcional ↓"),
    ("DPAD_LEFT", "Direcional ←"), ("DPAD_RIGHT", "Direcional →"),
]
MOVE_ROWS = [
    ("move:up", "Frente"), ("move:down", "Trás"), ("move:left", "Esquerda"),
    ("move:right", "Direita"), ("move:walk", "Andar devagar"),
]
ROW_LABELS = dict(BUTTON_ROWS + MOVE_ROWS)
BUTTON_IDS = [r for r, _ in BUTTON_ROWS]
MOVE_IDS = [r for r, _ in MOVE_ROWS]
SLOTS = 2

SETTING_KEYS = ("aim_mode", "deg_per_count", "invert_yaw", "invert_pitch", "walk_scale",
                "wheel_pulse_ms", "stick_sens", "stick_deadzone_comp")
SETTING_DEFAULTS = {"aim_mode": "gyro", "deg_per_count": 0.05, "invert_yaw": True,
                    "invert_pitch": True, "walk_scale": 0.5, "wheel_pulse_ms": 80.0,
                    "stick_sens": 1.0, "stick_deadzone_comp": 60}


def valid_key(name):
    return name in KEY_NAMES or name in MOUSE_NAMES


def check_key(name):
    """Retorna None se a tecla pode ser atribuida, senao mensagem de erro."""
    if is_reserved(name):
        return "%s é reservada (hotkey do programa)" % name.upper()
    if not valid_key(name):
        return "tecla desconhecida: %s" % name
    return None


def empty_rows():
    rows = {r: ["", ""] for r in BUTTON_IDS}
    for r in MOVE_IDS:
        rows[r] = [""]
    return rows


def profile_to_rows(data):
    """data: dict de perfil (como config.json). Retorna {row_id: [teclas...]}."""
    rows = empty_rows()
    binds = data.get("binds", DEFAULT_BINDS)
    for key, btn in binds.items():
        k = key.lower()
        if btn in rows and valid_key(k) and not is_reserved(k):
            rows[btn] = [x for x in rows[btn] if x] + [k]
            while len(rows[btn]) < SLOTS:
                rows[btn].append("")
    move = dict(DEFAULT_MOVE)
    move.update(data.get("move") or {})
    for d in DEFAULT_MOVE:
        rows["move:" + d] = [str(move.get(d, "")).lower()]
    return rows


def rows_to_profile(rows, settings=None, base=None):
    """Monta o dict do perfil. base: dict original (preserva chaves desconhecidas)."""
    data = copy.deepcopy(base) if base else {}
    for k, v in SETTING_DEFAULTS.items():
        data.setdefault(k, v)
    data.update(settings or {})
    binds = {}
    for rid in BUTTON_IDS:
        for k in rows.get(rid, []):
            if k:
                binds[k] = rid
    data["binds"] = binds
    data["move"] = {d: (rows.get("move:" + d) or [""])[0] for d in DEFAULT_MOVE}
    return data


def find_key(rows, key):
    """Retorna (row_id, slot) onde a tecla esta, ou None."""
    for rid, keys in rows.items():
        for i, k in enumerate(keys):
            if k == key:
                return rid, i
    return None


def assign_key(rows, row_id, slot, key):
    """Atribui key ao slot. Retorna (novas_linhas, moved_from_row_id ou None).
    Levanta ValueError se a tecla for reservada/desconhecida. Move a tecla de onde estava."""
    err = check_key(key)
    if err:
        raise ValueError(err)
    new = copy.deepcopy(rows)
    if row_id not in new:
        raise KeyError(row_id)
    slots = new[row_id]
    while len(slots) <= slot:
        slots.append("")
    if slots[slot] == key:
        return new, None
    moved = None
    where = find_key(new, key)
    if where:
        orow, oslot = where
        new[orow][oslot] = ""
        moved = orow
    new[row_id][slot] = key
    return new, moved


def clear_slot(rows, row_id, slot):
    new = copy.deepcopy(rows)
    if slot < len(new[row_id]):
        new[row_id][slot] = ""
    return new


def clear_row(rows, row_id):
    new = copy.deepcopy(rows)
    new[row_id] = ["" for _ in new[row_id]]
    return new


def parse_sens_line(line):
    """Linha 'SENS deg_per_count=0.0550' do bridge -> float (ou None)."""
    import re
    m = re.search(r"SENS deg_per_count=([0-9.]+)", line)
    return float(m.group(1)) if m else None


def parse_stick_sens_line(line):
    """Linha 'STICKSENS stick_sens=1.210' do bridge -> float (ou None)."""
    import re
    m = re.search(r"STICKSENS stick_sens=([0-9.]+)", line)
    return float(m.group(1)) if m else None
