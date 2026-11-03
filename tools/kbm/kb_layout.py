"""Teclado da tela do Switch 2, MEDIDO no console real: paginas, grade e regras de navegacao.
Porte fiel de web/js/kb-layout.js. "·" = celula sem caractere (navegavel, mas A nao faz nada)."""
import re

try:
    from i18n import N_
except ImportError:  # pragma: no cover
    from .i18n import N_


def _grid(*rows):
    return [[None if t == "·" else t for t in r.split(" ")] for r in rows]


LAYOUT = {
    "name": N_("Teclado do Switch 2"),
    "verified": True,
    "rows": 4,
    "cols": 11,
    "start": "r0c0",
    "startPage": "abc",
    # lower = sem Shift; upper = com L3 (None: Shift nao muda nada)
    "pages": {
        "abc": {
            "label": "ABC",
            "lower": _grid("1 2 3 4 5 6 7 8 9 0 =", "q w e r t y u i o p °", "a s d f g h j k l ç ª", "z x c v b n m , . - +"),
            "upper": _grid('! " # € % & ( ) ? [ ]', "Q W E R T Y U I O P @", "A S D F G H J K L Ç *", "Z X C V B N M ; : _ £"),
        },
        "acc1": {
            "label": "ÀÁÂ",
            "lower": _grid("à á â ã ä å æ ā ă ą ç", "ć ċ č ð ď · · è é ê ë", "ē ę ě ğ ġ ģ ħ ì í î ï", "ī į ı · ķ ĺ ļ ľ ł · ·"),
            "upper": _grid("À Á Â Ã Ä Å Æ Ā Ă Ą Ç", "Ć Ċ Č Ð Ď · · È É Ê Ë", "Ē Ę Ě Ğ Ġ Ģ Ħ Ì Í Î Ï", "Ī Į İ · Ķ Ĺ Ļ Ľ Ł · ·"),
        },
        "acc2": {
            "label": "ÑŃŅ",
            "lower": _grid("ñ ń ņ ň ò ó ô õ ö ø œ", "ő ō ŕ ř š ß ś ş þ ť ț", "ù ú û ü ū ů ű ų ý ÿ ź", "ż ž · · · · · · · · ·"),
            "upper": _grid("Ñ Ń Ņ Ň Ò Ó Ô Õ Ö Ø Œ", "Ő Ō Ŕ Ř Š · Ś Ş Þ Ť Ț", "Ù Ú Û Ü Ū Ů Ű Ų Ý Ÿ Ź", "Ż Ž · · · · · · · · ·"),
        },
        "sym": {
            "label": "#+=",
            "lower": _grid("1 2 3 4 5 6 7 8 9 0 -", "! @ # $ % ^ & * ( ) _", "~ ` = \\ + { } | [ ] ·", "< > ; : \" ' , . ? / ·"),
            "upper": None,
        },
    },
    # abas, na ordem da linha; a coluna da grade logo acima e o indice. page: aba que troca de pagina
    "tabs": [
        {"id": "globe", "label": "🌐", "name": "Idioma"},
        {"id": "shift", "label": "⇧", "name": "Shift"},
        {"id": "abc", "label": "ABC", "name": "ABC", "page": "abc"},
        {"id": "sym", "label": "#+=", "name": "#+=", "page": "sym"},
        {"id": "acc1", "label": "ÀÁÂ", "name": "ÀÁÂ", "page": "acc1"},
        {"id": "acc2", "label": "ÑŃŅ", "name": "ÑŃŅ", "page": "acc2"},
    ],
    # coluna direita, por linha da grade
    "right": [
        {"id": "bksp", "label": "⌫", "name": "Apagar"},
        {"id": "enter1", "label": "↵", "name": "Enter"},
        {"id": "enter2", "label": "↵", "name": "Enter"},
        {"id": "submit3", "label": "🔍", "name": "Buscar"},
    ],
    # arestas PROIBIDAS: saem do teclado ou vao para o Espaco
    "rules": {"noUpFromRow": 0, "downFromLastRowOnlyCols": 6},
    # botoes do CONSOLE (nomes de SWITCH_BTN em typing_engine.py)
    "shortcuts": {"space": "Y", "backspace": "B", "submit": "+", "shift": "L3"},
}

DIRS = ("up", "down", "left", "right")
_CELL = re.compile(r"^r(\d)c(\d+)$")
PAGE_TAB = {t["page"]: t["id"] for t in LAYOUT["tabs"] if t.get("page")}


def cell_id(r, c):
    return "r%dc%d" % (r, c)


def parse_cell(node):
    m = _CELL.match(node)
    return (int(m.group(1)), int(m.group(2))) if m else None


def all_nodes(L=LAYOUT):
    out = [cell_id(r, c) for r in range(L["rows"]) for c in range(L["cols"])]
    return out + [x["id"] for x in L["right"]] + [x["id"] for x in L["tabs"]]


def nav(node, d, L=LAYOUT):
    """Vizinho de um no na direcao dada (None = aresta inexistente ou proibida)."""
    cell = parse_cell(node)
    if cell:
        r, c = cell
        if d == "up":
            return cell_id(r - 1, c) if r > L["rules"]["noUpFromRow"] else None
        if d == "down":
            if r < L["rows"] - 1:
                return cell_id(r + 1, c)
            return L["tabs"][c]["id"] if c < L["rules"]["downFromLastRowOnlyCols"] else None
        ring = L["cols"] + 1  # ciclo da linha: c0..c10 + no da coluna direita
        i = (c + (1 if d == "right" else -1) + ring) % ring
        return L["right"][r]["id"] if i == L["cols"] else cell_id(r, i)
    ri = next((k for k, x in enumerate(L["right"]) if x["id"] == node), -1)
    if ri >= 0:
        if d in ("up", "down"):
            return None
        ring = L["cols"] + 1
        i = (L["cols"] + (1 if d == "right" else -1) + ring) % ring
        return node if i == L["cols"] else cell_id(ri, i)
    ti = next((k for k, x in enumerate(L["tabs"]) if x["id"] == node), -1)
    if ti < 0:
        return None
    if d == "up":
        return cell_id(L["rows"] - 1, ti)
    if d == "down":
        return None
    n = ti + (1 if d == "right" else -1)
    return L["tabs"][n]["id"] if 0 <= n < len(L["tabs"]) else None  # sem wrap


class Bfs:
    """BFS a partir de um no: path(to) = lista de direcoes (None se nao alcanca)."""

    def __init__(self, start, L=LAYOUT):
        self.prev = {start: None}
        queue = [start]
        qi = 0
        while qi < len(queue):
            node = queue[qi]
            qi += 1
            for d in DIRS:
                n = nav(node, d, L)
                if n is None or n in self.prev:
                    continue
                self.prev[n] = (node, d)
                queue.append(n)

    def path(self, to):
        if to not in self.prev:
            return None
        out = []
        cur = to
        while self.prev[cur]:
            out.append(self.prev[cur][1])
            cur = self.prev[cur][0]
        out.reverse()
        return out


def bfs(start, L=LAYOUT):
    return Bfs(start, L)


def shortest_path(a, b, L=LAYOUT):
    return Bfs(a, L).path(b)
