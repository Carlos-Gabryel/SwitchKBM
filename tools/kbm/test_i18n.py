import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import i18n
import profiles as pf
from controller import Controller
from i18n import tr, tr_line
from i18n_en import EN

KBM = Path(__file__).resolve().parent
SKIP_SCAN = {"build.py", "make_icon.py", "gen_web_vectors.py"}
ACCENTS = re.compile("[ãáàâéêíóôõúçÃÁÀÂÉÊÍÓÔÕÚÇ]")
GUARDED = ("controller.py", "capture.py", "updater.py", "profiles.py", "bindings.py")
WIDGET_FUNCS = {"text", "muted", "button", "notice", "info", "ask", "dialog", "ask_name"}
WIDGET_KW = {"tooltip", "hint_text", "label", "yes", "no"}
# texto que nao precisa de traducao
ALLOW_TEXT = {"Switch KBM", "By Carlos Gabryel", "Idioma / Language", "OK"}
ALLOW_ACCENT = {"Switch KBM"}


@pytest.fixture(autouse=True)
def _pt():
    i18n.set_language("pt")
    yield
    i18n.set_language("pt")


def _sources():
    files = list(KBM.glob("*.py")) + list((KBM / "ui").rglob("*.py"))
    return sorted(p for p in files if ".venv" not in p.parts and not p.name.startswith("test_")
                  and not p.name.startswith("i18n") and p.name not in SKIP_SCAN)


def _marked():
    keys, bad = set(), []
    for p in _sources():
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("tr", "N_") and n.args:
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    keys.add(a.value)
                elif n.func.id == "N_":
                    bad.append("%s:%d" % (p.name, n.lineno))
    return keys, bad


def _placeholders(text):
    return sorted(m for m in i18n.PLACEHOLDER.findall(text) if m != "%%")


def test_varredura_marcados_x_en():
    keys, bad = _marked()
    assert not bad, "N_ com nao-literal: %s" % bad
    assert not keys - set(EN), "faltam em EN: %s" % sorted(keys - set(EN))
    assert not set(EN) - keys, "chaves de EN sem uso: %s" % sorted(set(EN) - keys)


@pytest.mark.parametrize("pt,en", list(EN.items()))
def test_paridade_entrada(pt, en):
    assert en.strip(), pt
    assert _placeholders(pt) == _placeholders(en), pt
    assert pt[:len(pt) - len(pt.lstrip())] == en[:len(en) - len(en.lstrip())], "espaco inicial: %r" % pt
    assert pt[len(pt.rstrip()):] == en[len(en.rstrip()):], "espaco final: %r" % pt
    assert not ACCENTS.search(en), en


def _docstring_nodes(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def _wrapped_nodes(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("tr", "N_"):
            for sub in ast.walk(n):
                out.add(id(sub))
    return out


def _guard_files():
    return [p for p in _sources() if p.name in GUARDED or "ui" in p.relative_to(KBM).parts]


def test_guarda_acentos_sem_marcacao():
    found = []
    for p in _guard_files():
        tree = ast.parse(p.read_text(encoding="utf-8"))
        skip = _docstring_nodes(tree) | _wrapped_nodes(tree)
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip \
                    and ACCENTS.search(n.value) and n.value not in ALLOW_ACCENT:
                found.append("%s:%d %r" % (p.name, n.lineno, n.value))
    assert not found, "texto com acento sem tr/N_:\n" + "\n".join(found)


def _func_name(call):
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def test_guarda_widgets_sem_tr():
    found = []
    for p in _guard_files():
        if "ui" not in p.relative_to(KBM).parts:
            continue
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if not isinstance(n, ast.Call):
                continue
            cands = []
            if _func_name(n) in WIDGET_FUNCS and n.args:
                cands.append(n.args[0])
            cands += [k.value for k in n.keywords if k.arg in WIDGET_KW]
            for c in cands:
                if isinstance(c, ast.Constant) and isinstance(c.value, str) and re.search("[A-Za-z]", c.value) \
                        and c.value not in ALLOW_TEXT:
                    found.append("%s:%d %r" % (p.name, c.lineno, c.value))
    assert not found, "literal de widget sem tr:\n" + "\n".join(found)


def test_tr_line():
    i18n.set_language("en")
    assert tr_line("Modo de mira: Giroscópio") == "Aim mode: Gyro"
    assert tr_line("Aviso: Modo de mira: Giroscópio") == "Warning: Aim mode: Gyro"
    assert tr_line("Aviso: tecla desconhecida: x") == "Warning: unknown key: x"
    assert tr_line("Sensibilidade giro: 0.050") == "Gyro sensitivity: 0.050"
    assert tr_line("Sensibilidade analogico: 1.210") == "Stick sensitivity: 1.210"
    assert tr_line("CAPTURADO (F12 libera)") == "CAPTURED (F12 releases)"
    assert tr_line("aviso config: tecla desconhecida: zz") == "config warning: unknown key: zz"
    assert tr_line("Writing at 0x1000... (10 %)") == "Writing at 0x1000... (10 %)"
    assert tr_line("linha qualquer") == "linha qualquer"


def test_tr_line_pt_inalterado():
    for line in ("Modo de mira: Giroscópio", "CAPTURADO (F12 libera)", "Writing at 0x1000... (10 %)"):
        assert tr_line(line) == line
    assert tr("Parado") == "Parado"


def test_tr_en():
    i18n.set_language("en")
    assert tr("Parado") == "Stopped" and tr("sem chave") == "sem chave"
    i18n.set_language("zz")
    assert i18n.get_language() == "pt"


def test_default_language():
    d = i18n.default_language
    if os.name != "nt":
        assert d({"LANG": "pt_BR.UTF-8"}) == "pt"
        assert d({"LANG": "en_US.UTF-8"}) == "en"
        assert d({"LANG": "C"}) == "en"
        assert d({"LC_ALL": "en_US.UTF-8", "LANG": "pt_BR.UTF-8"}) == "en"
        assert d({"LC_ALL": "", "LC_MESSAGES": "pt_PT", "LANG": "en_US"}) == "pt"


def _ctrl():
    return Controller(pf.ProfileStore(base=tempfile.mkdtemp(prefix="kbmi18n")))


def test_controller_en_perfil_e_protocolo():
    c = _ctrl()
    i18n.set_language("en")
    c.settings["aim"] = "Analógico direito"
    c.save(restart=False)
    c.load_profile(c.name)
    assert c.store.load(c.name)["aim_mode"] == "stick"
    assert c.settings["aim"] == "Analógico direito"
    c.on_bridge_line("CAPTURADO (F12 libera)")
    assert c.stat_extra == "CAPTURED (F12 releases)"
    c.on_bridge_line("SENS deg_per_count=0.0550")
    assert abs(c.settings["sens"] - 0.055) < 1e-9
    c.on_bridge_line("STICKSENS stick_sens=1.210")
    assert abs(c.settings["ssens"] - 1.21) < 1e-9
    c.on_bridge_line("DIGITACAO ON")
    assert c.typing_on and c.stat_extra == "Typing mode (F9 exits)"
    c.on_bridge_line("DIGITACAO OFF")
    assert not c.typing_on
    c.on_bridge_line("ERRO: nenhum teclado ou mouse encontrado em /dev/input.")
    assert c.bridge_errors == ["no keyboard or mouse found in /dev/input."]
    assert "CAPTURED (F12 releases)" in c.log


def test_set_language_persiste():
    c = _ctrl()
    c.set_port("/dev/ttyUSB0")
    c.set_language("en")
    st = c.store.load_settings()
    assert st["language"] == "en" and st["port"] == "/dev/ttyUSB0"
    assert i18n.get_language() == "en"


def test_nome_do_perfil_padrao():
    c = _ctrl()
    assert c.name == pf.DEFAULT_NAME == "Padrão"
    assert pf.label(pf.DEFAULT_NAME) == "Padrão"
    i18n.set_language("en")
    assert pf.label(pf.DEFAULT_NAME) == "Default" and pf.label("Meu") == "Meu"
    assert os.path.exists(c.store.path(pf.DEFAULT_NAME))
    assert pf.DEFAULT_NAME == "Padrão"


def test_controller_init_nao_muda_idioma():
    i18n.set_language("en")
    _ctrl()
    assert i18n.get_language() == "en"


def test_import_das_views():
    for mod in ("ui.app", "ui.theme", "ui.views.ajustes", "ui.views.controles", "ui.views.digitacao",
                "ui.views.placa"):
        __import__(mod)


def test_selftest_subprocesso():
    r = subprocess.run([sys.executable, str(KBM / "kbm_app.py"), "--selftest"], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0 and "selftest OK" in r.stdout, r.stdout + r.stderr


def test_placa_compara_traduzido():
    i18n.set_language("en")
    assert tr("Placa pronta.") == "Board ready."
