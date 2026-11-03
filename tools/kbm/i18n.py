"""Idioma da interface (pt/en). O texto em portugues e a chave: tr("texto pt") devolve o ingles em en.

Traduz so na exibicao (nunca valores salvos nem comparados). Os subprocessos (bridge, flasher) imprimem
sempre em portugues; a UI traduz as linhas com tr_line."""
import locale
import os
import re

LANGUAGES = {"pt": "Português", "en": "English"}
_lang = "pt"

# %% | %s %d %r | %.Nf | %0NX
PLACEHOLDER = re.compile(r"%%|%(?:\.\d+f|0\d+X|[sdr])")
_PATTERNS = None


def get_language():
    return _lang


def set_language(code):
    global _lang
    _lang = code if code in LANGUAGES else "pt"


def default_language(environ=os.environ):
    value = ""
    if os.name != "nt":
        value = next((environ[k] for k in ("LC_ALL", "LC_MESSAGES", "LANG") if environ.get(k)), "")
    if not value:
        try:
            value = locale.getlocale()[0] or ""
        except (ValueError, TypeError):
            value = ""
    v = value.lower()
    return "pt" if v.startswith("pt") or v.startswith("portuguese") else "en"


def _en():
    from i18n_en import EN
    return EN


def tr(text):
    if _lang == "en":
        return _en().get(text, text)
    return text


def N_(text):
    """Marca um texto para traducao sem traduzir agora (constantes de modulo, saida de subprocessos)."""
    return text


_REGEX = {"%s": "(.*)", "%r": "(.*)", "%d": "(-?\\d+)"}


def _compile(key):
    out, pos = [], 0
    for m in PLACEHOLDER.finditer(key):
        out.append(re.escape(key[pos:m.start()]))
        tok = m.group(0)
        if tok == "%%":
            out.append("%")
        elif tok.endswith("f"):
            out.append("(-?\\d+(?:\\.\\d+)?)")
        elif tok.endswith("X"):
            out.append("([0-9A-Fa-f]+)")
        else:
            out.append(_REGEX[tok])
        pos = m.end()
    out.append(re.escape(key[pos:]))
    return re.compile("^" + "".join(out) + "$", re.S)


def _patterns():
    global _PATTERNS
    if _PATTERNS is None:
        en = _en()
        keys = [k for k in en if any(m.group(0) != "%%" for m in PLACEHOLDER.finditer(k))]
        keys.sort(key=len, reverse=True)
        _PATTERNS = [(_compile(k), en[k]) for k in keys]
    return _PATTERNS


def _fill(template, groups):
    it = iter(groups)
    return PLACEHOLDER.sub(lambda m: "%" if m.group(0) == "%%" else next(it, m.group(0)), template)


def _tr_line(line, depth):
    en = _en()
    if line in en:
        return en[line]
    if depth >= 2:
        return line
    for rx, template in _patterns():
        m = rx.match(line)
        if m:
            return _fill(template, [_tr_line(g, depth + 1) for g in m.groups()])
    return line


def tr_line(line):
    """Linha vinda do bridge/flasher (sempre em pt) -> texto para exibir. Desconhecida volta igual."""
    if _lang != "en":
        return line
    return _tr_line(line, 0)
