"""Traz a janela do programa para frente quando o sistema nao deixa ela fazer isso sozinha."""
import os
import subprocess
import sys
import tempfile

# KWin 6 usa windowList/activeWindow; KWin 5, clientList/activeClient
_SCRIPT = """
var list = workspace.windowList ? workspace.windowList() : workspace.clientList();
for (var i = 0; i < list.length; i++) {
    var w = list[i];
    if (w.caption === %s) {
        w.minimized = false;
        if (workspace.windowList) workspace.activeWindow = w; else workspace.activeClient = w;
        break;
    }
}
"""


def kwin_script(title):
    return _SCRIPT % _js_str(title)


def _js_str(s):
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


def is_kde_wayland(env=os.environ):
    return (sys.platform.startswith("linux") and "KDE" in env.get("XDG_CURRENT_DESKTOP", "")
            and env.get("XDG_SESSION_TYPE") == "wayland")


def _busctl(*args):
    # Sem as bibliotecas do AppImage, que atrapalham binarios do sistema
    env = {k: v for k, v in os.environ.items() if k not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}
    r = subprocess.run(["busctl", "--user", "--", *args], env=env, capture_output=True, text=True, timeout=2)
    if r.returncode:
        raise OSError(r.stderr.strip() or "busctl falhou")
    return r.stdout.strip()


def activate(title):
    """No KDE com Wayland, ativa a janela por um script do KWin. Devolve True se ativou por esse caminho."""
    if not is_kde_wayland():
        return False
    name = "switchkbm-foco"
    fd, path = tempfile.mkstemp(prefix="switchkbm-", suffix=".js")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(kwin_script(title))
        _busctl("call", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", name)
        out = _busctl("call", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "loadScript", "ss", path, name)
        sid = out.split()[-1]
        _busctl("call", "org.kde.KWin", "/Scripting/Script%s" % sid, "org.kde.kwin.Script", "run")
        return True
    except (OSError, IndexError, subprocess.SubprocessError):
        return False
    finally:
        try:
            _busctl("call", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", name)
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
