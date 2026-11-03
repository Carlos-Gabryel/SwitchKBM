"""Motor de digitacao no teclado do Switch 2. Porte fiel de web/js/typing.js (tempo injetado em ms)."""
import math
import unicodedata

try:
    from proto import BTN
    from kb_layout import LAYOUT, PAGE_TAB, bfs, cell_id, nav, all_nodes
except ImportError:  # pragma: no cover
    from .proto import BTN
    from .kb_layout import LAYOUT, PAGE_TAB, bfs, cell_id, nav, all_nodes


def _bit(b):
    return 1 << b


# Nomes do CONSOLE -> bit enviado. O firmware troca A/B e X/Y por posicao fisica.
# Sem X (fecha o teclado), L e R: nao existem aqui para ser impossivel usa-los.
SWITCH_BTN = {
    "A": _bit(BTN["B"]), "B": _bit(BTN["A"]), "Y": _bit(BTN["X"]),
    "+": _bit(BTN["START"]),
    "L3": _bit(BTN["L3"]),
    "DPAD_UP": _bit(BTN["DPAD_UP"]), "DPAD_DOWN": _bit(BTN["DPAD_DOWN"]),
    "DPAD_LEFT": _bit(BTN["DPAD_LEFT"]), "DPAD_RIGHT": _bit(BTN["DPAD_RIGHT"]),
}
DIR_BTN = {"up": "DPAD_UP", "down": "DPAD_DOWN", "left": "DPAD_LEFT", "right": "DPAD_RIGHT"}

PRESETS = {"seguro": (50, 50), "normal": (42, 42), "rapido": (34, 34)}
DEFAULT_PRESET = "normal"
MIN_MS = 25
MAX_MS = 100
MAX_PENDING = 500
RATE_WINDOW_MS = 3000
MAX_NAV = 4


def _js_round(v):
    return int(math.floor(v + 0.5))


def migrate_prefs(p):
    """Preferencia salva (possivelmente antiga) -> valida; fora da faixa volta ao padrao."""
    d = p if isinstance(p, dict) else {}
    pr = d.get("preset")
    preset = pr if (pr in PRESETS or pr == "custom") else DEFAULT_PRESET
    try:
        ms = float(d.get("ms"))
    except (TypeError, ValueError):
        ms = float("nan")
    ok = ms == ms and MIN_MS <= ms <= MAX_MS
    if not ok:
        ms = PRESETS[DEFAULT_PRESET][0]
        if preset == "custom":
            preset = DEFAULT_PRESET
    if preset in PRESETS:
        ms = PRESETS[preset][0]
    return {"preset": preset, "ms": _js_round(ms), "stripAccents": d.get("stripAccents") is True}


def text_diff(prev, nxt):
    """Diferenca por prefixo comum: (quantos apagar, o que inserir)."""
    i = 0
    n = min(len(prev), len(nxt))
    while i < n and prev[i] == nxt[i]:
        i += 1
    return len(prev) - i, nxt[i:]


def _base_of(ch):
    return "".join(c for c in unicodedata.normalize("NFD", ch) if not "̀" <= c <= "ͯ")


class TypingEngine:
    def __init__(self, hold_ms=PRESETS[DEFAULT_PRESET][0], gap_ms=PRESETS[DEFAULT_PRESET][1],
                 strip_accents=False, layout=LAYOUT):
        self.layout = layout
        self.hold_ms = hold_ms
        self.gap_ms = gap_ms
        self.strip_accents = bool(strip_accents)
        sc = layout["shortcuts"]
        self.mask = {"space": SWITCH_BTN[sc["space"]], "backspace": SWITCH_BTN[sc["backspace"]],
                     "submit": SWITCH_BTN[sc["submit"]], "shift": SWITCH_BTN[sc["shift"]],
                     "a": SWITCH_BTN["A"]}
        # indice caractere -> ocorrencias (page, shift, node), na ordem de varredura
        self.occ = {}
        for page, p in layout["pages"].items():
            for shift, g in ((False, p["lower"]), (True, p["upper"])):
                if not g:
                    continue
                for r, row in enumerate(g):
                    for c, ch in enumerate(row):
                        if ch is None:
                            continue
                        self.occ.setdefault(ch, []).append((page, shift, cell_id(r, c)))
        self._tab_bfs = {}
        self.cursor = layout["start"]
        self.page = layout["startPage"]
        self.skipped = []
        self._items = []
        self._steps = []
        self._cur = None        # passo pressionado: dict(mask, at, last, item)
        self._active = None     # item em andamento
        self._released_at = -math.inf
        self._done = []
        self._hist = []         # "t" digitado / "s" ignorado, para o backspace
        self._last_now = 0
        self._nodes = set(all_nodes(layout))

    def set_timing(self, hold_ms, gap_ms=None):
        gap_ms = hold_ms if gap_ms is None else gap_ms

        def c(v):
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = 0
            if v != v:
                v = 0
            return min(MAX_MS, max(MIN_MS, _js_round(v)))
        self.hold_ms = c(hold_ms)
        self.gap_ms = c(gap_ms)

    # ---- fila ----
    def enqueue_char(self, ch):
        self._items.append({"type": "char", "ch": ch})

    def enqueue(self, text):
        for ch in text:
            self.enqueue_char(ch)

    def enqueue_submit(self):
        self._items.append({"type": "submit"})

    def backspace_requested(self):
        last = self._items[-1] if self._items else None
        if last and last["type"] == "char":
            self._items.pop()
        else:
            self._items.append({"type": "backspace"})

    def clear_pending(self):
        self._items = []
        self._steps = []
        if not self._cur:
            self._active = None     # o passo atual termina sozinho

    def reset_keyboard(self):
        """Teclado reaberto na TV: cursor no 1 e fila limpa; o console lembra a pagina."""
        self.clear_pending()
        self._hist = []
        self.cursor = self.layout["start"]

    def sync_cursor(self, node):
        if node in self._nodes:
            self.cursor = node

    def sync_page(self, page):
        if page in self.layout["pages"]:
            self.page = page

    def press_manual(self, direction):
        """Direcao proibida vira nada: o plano so olha o grafo permitido."""
        if direction not in DIR_BTN:
            return
        if sum(1 for i in self._items if i["type"] == "nav") >= MAX_NAV:
            return
        self._items.append({"type": "nav", "dir": direction})

    # ---- estado ----
    @property
    def pending_count(self):
        n = sum(1 for i in self._items if i["type"] != "nav")
        return n + (1 if self._active and self._active["type"] != "nav" else 0)

    @property
    def busy(self):
        return bool(self._cur) or len(self._steps) > 0 or len(self._items) > 0

    @property
    def chars_per_second(self):
        lo = self._last_now - RATE_WINDOW_MS
        self._done = [t for t in self._done if t > lo]
        return len(self._done) / (RATE_WINDOW_MS / 1000)

    # ---- planejamento (preguicoso: um item por vez) ----
    def _tab(self, tab):
        if tab not in self._tab_bfs:
            self._tab_bfs[tab] = bfs(tab, self.layout)
        return self._tab_bfs[tab]

    def _find(self, ch):
        """Melhor ocorrencia do caractere a partir do estado atual (cursor + pagina)."""
        occ = self.occ.get(ch)
        if not occ:
            return None
        from_cur = bfs(self.cursor, self.layout)
        best = None
        for o in occ:
            page, shift, node = o
            pre = None
            if page == self.page:
                dirs = from_cur.path(node)
                if dirs is None:
                    continue
                cost = len(dirs)
            else:
                tab = PAGE_TAB[page]
                pre = from_cur.path(tab)
                dirs = self._tab(tab).path(node)
                if pre is None or dirs is None:
                    continue
                cost = len(pre) + 1 + len(dirs)
            cost += (1 if shift else 0) + 1
            key = (cost, 0 if page == self.page else 1, 1 if shift else 0)
            if best is None or key < best[0]:
                best = (key, o, pre, dirs)
        return best

    def _resolve(self, ch):
        base = _base_of(ch)
        if self.strip_accents:
            return self._find(base)
        r = self._find(ch)
        if r is not None:
            return r
        if base != ch and len(base) == 1:
            return self._find(base)
        return None

    def _walk(self, steps, frm, dirs):
        cur = frm
        for d in dirs:
            cur = nav(cur, d, self.layout)
            steps.append({"mask": SWITCH_BTN[DIR_BTN[d]], "cursor": cur})
        return cur

    def _plan_item(self, item):
        steps = []
        t = item["type"]
        if t == "char":
            ch = item["ch"]
            if ch == " ":
                steps.append({"mask": self.mask["space"]})
                self._hist.append("t")
            else:
                r = self._resolve(ch)
                if r is None:
                    self.skipped.append(ch)
                    self._hist.append("s")
                else:
                    _, (page, shift, _node), pre, dirs = r
                    cur = self.cursor
                    if pre is not None:
                        cur = self._walk(steps, cur, pre)
                        steps.append({"mask": self.mask["a"], "page": page})  # A na aba troca a pagina
                    self._walk(steps, cur, dirs)
                    if shift:
                        steps.append({"mask": self.mask["shift"]})  # L3 vale so para a proxima tecla
                    steps.append({"mask": self.mask["a"]})
                    self._hist.append("t")
        elif t == "backspace":
            if self._hist and self._hist[-1] == "s":
                self._hist.pop()    # o console nunca recebeu esse caractere
            else:
                if self._hist:
                    self._hist.pop()
                steps.append({"mask": self.mask["backspace"]})
        elif t == "submit":
            steps.append({"mask": self.mask["submit"], "cursor": self.layout["start"]})
            self._hist = []
        elif t == "nav":
            to = nav(self.cursor, item["dir"], self.layout)
            if to:
                steps.append({"mask": SWITCH_BTN[DIR_BTN[item["dir"]]], "cursor": to})
        if len(self._hist) > 1000:
            del self._hist[:500]
        if steps:
            steps[-1]["last"] = True
        return steps

    def _next_step(self):
        while not self._steps:
            if not self._items:
                self._active = None
                return None
            item = self._items.pop(0)
            self._active = item
            self._steps = self._plan_item(item)
            if not self._steps:
                self._active = None
        return self._steps.pop(0)

    def tick(self, now_ms):
        """Mascara de botoes (bits do firmware) no instante now_ms."""
        self._last_now = now_ms
        if self._cur:
            if now_ms - self._cur["at"] < self.hold_ms:
                return self._cur["mask"]
            s = self._cur
            self._cur = None
            self._released_at = now_ms  # sempre solta num tick proprio, mesmo atrasado
            if s["last"] and s["item"] and s["item"]["type"] != "nav":
                self._done.append(now_ms)
            if not self._steps:
                self._active = None
            return 0
        if now_ms - self._released_at < self.gap_ms:
            return 0
        step = self._next_step()
        if not step:
            return 0
        if step.get("cursor"):
            self.cursor = step["cursor"]
        if step.get("page"):
            self.page = step["page"]
        self._cur = {"mask": step["mask"], "at": now_ms, "last": bool(step.get("last")),
                     "item": self._active}
        return step["mask"]

    def state(self):
        """Resumo para a UI (DIGITACAO_ESTADO)."""
        return {"cursor": self.cursor, "page": self.page, "pending": self.pending_count,
                "cps": round(self.chars_per_second, 1), "skipped": len(self.skipped),
                "busy": self.busy}


def plan_char_for_test(engine, ch):
    """So para testes: passos planejados de um caractere sem rodar o relogio."""
    return engine._plan_item({"type": "char", "ch": ch})
