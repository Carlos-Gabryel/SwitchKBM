"""Gera dist/SwitchKBM.exe (Windows) ou dist/SwitchKBM-x86_64.AppImage (Linux) com o firmware embutido.

Uso: python tools/kbm/build.py [--skip-firmware]
Etapas: firmware (idf.py), copia para build/firmware (caminhos relativos do flasher_args.json),
flet pack (PyInstaller onefile) e, no Linux, empacotamento em AppImage (appimagetool).
"""
import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

KBM = Path(__file__).resolve().parent
REPO = KBM.parent.parent
LINUX = sys.platform.startswith("linux")
VERSION = "1.0.3"

APPIMAGETOOL_TAG = "1.9.1"
APPIMAGETOOL_URL = ("https://github.com/AppImage/appimagetool/releases/download/%s/appimagetool-x86_64.AppImage"
                    % APPIMAGETOOL_TAG)
APPIMAGETOOL_SHA256 = "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
APPIMAGE_NAME = "SwitchKBM-x86_64.AppImage"

DESKTOP = """[Desktop Entry]
Type=Application
Name=SwitchKBM
Comment=Teclado e mouse como controle do Switch
Exec=SwitchKBM
Icon=switchkbm
Categories=Game;Utility;
Terminal=false
"""

APPRUN = """#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/SwitchKBM" "$@"
"""

HIDDEN = ["kbm_bridge", "proto", "mapping", "flasher", "runners", "controller", "capture", "bindings",
          "updater", "profiles", "serial", "serial.tools.list_ports", "esptool"]


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def build_firmware():
    sw = REPO / "switch-side"
    if LINUX:
        cache = sw / "build" / "CMakeCache.txt"
        if cache.is_file() and ("CMAKE_HOME_DIRECTORY:INTERNAL=%s\n" % sw) not in cache.read_text(errors="replace"):
            shutil.rmtree(sw / "build")     # cache de outra maquina (ex.: Windows): o cmake nao aceita
        run(["bash", "-c", '. "$1/tools/idf-env.sh" && idf.py -C "$1/switch-side" build', "_", str(REPO)])
    else:
        # processo filho: o export.ps1 do ESP-IDF altera o PATH/python
        run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
             ". '%s\\tools\\idf-env.ps1'; idf.py -C '%s\\switch-side' build; exit $LASTEXITCODE" % (REPO, REPO)])


def stage_firmware():
    """Copia o firmware para build/firmware (so os arquivos do flasher_args.json, nos mesmos caminhos)."""
    src = REPO / "switch-side" / "build"
    dst = REPO / "build" / "firmware"
    if not (src / "flasher_args.json").is_file():
        # sem switch-side/build (CI): usa um build/firmware ja preparado
        if (dst / "flasher_args.json").is_file():
            return dst
        raise SystemExit("firmware nao encontrado (nem %s nem %s)" % (src, dst))
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    manifest = json.loads((src / "flasher_args.json").read_text(encoding="utf-8"))
    for rel in ["flasher_args.json"] + list(manifest["flash_files"].values()):
        f = src / rel
        if not f.is_file():
            raise SystemExit("firmware ausente: %s" % f)
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst / rel)
    return dst


def pack(fw):
    """flet pack numa pasta de trabalho propria: ele apaga build/ e a pasta de saida do diretorio atual."""
    work = REPO / ".pack"
    work.mkdir(exist_ok=True)
    hidden = HIDDEN + (["linput", "keymap_linux", "evdev"] if LINUX else ["winput"])
    flet = "import sys; from flet_cli.cli import main; sys.argv[0] = 'flet'; main()"
    cmd = [sys.executable, "-c", flet, "pack", str(KBM / "kbm_app.py"), "--name", "SwitchKBM", "-y",
           "--distpath", str(work / "dist")]
    if LINUX:
        cmd += ["--icon", str(KBM / "ui" / "assets" / "icon.png")]
    else:
        cmd += ["--icon", str(KBM / "ui" / "assets" / "icon.ico"),
                "--product-name", "Switch KBM", "--file-description", "Switch KBM",
                "--product-version", VERSION, "--file-version", VERSION + ".0",
                "--company-name", "Carlos Gabryel", "--copyright", "(c) 2026 Carlos Gabryel - GPL-3.0"]
    cmd += ["--add-data", "%s%sfirmware" % (fw, os.pathsep),
            "%s%s%s" % (KBM / "ui" / "assets", os.pathsep, os.path.join("ui", "assets"))]
    for a in ["--paths=%s" % KBM] + ["--hidden-import=%s" % h for h in hidden] + [
            "--collect-data=esptool", "--collect-submodules=esptool", "--collect-submodules=ui"]:
        cmd.append("--pyinstaller-build-args=%s" % a)
    if (work / "dist").exists():
        shutil.rmtree(work / "dist")
    run(cmd, cwd=work, env=dict(os.environ, PYTHONPATH=str(KBM)))
    out = work / "dist" / ("SwitchKBM" if LINUX else "SwitchKBM.exe")
    if not out.is_file():
        raise SystemExit("executavel nao gerado: %s" % out)
    return out


def fetch_appimagetool():
    cache = REPO / ".appimagetool" / APPIMAGETOOL_TAG
    tool = cache / "appimagetool-x86_64.AppImage"
    if not tool.is_file():
        cache.mkdir(parents=True, exist_ok=True)
        print("baixando", APPIMAGETOOL_URL, flush=True)
        part = tool.with_suffix(".part")
        with urllib.request.urlopen(APPIMAGETOOL_URL, timeout=60) as r, open(part, "wb") as f:
            shutil.copyfileobj(r, f)
        if hashlib.sha256(part.read_bytes()).hexdigest() != APPIMAGETOOL_SHA256:
            part.unlink()
            raise SystemExit("SHA-256 do appimagetool nao confere")
        part.replace(tool)
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    return tool


def has_fuse():
    return bool(shutil.which("fusermount") or shutil.which("fusermount3")) and os.access("/dev/fuse", os.R_OK | os.W_OK)


def make_appimage(binary):
    appdir = REPO / ".pack" / "AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    (appdir / "usr" / "bin").mkdir(parents=True)
    shutil.copy2(binary, appdir / "usr" / "bin" / "SwitchKBM")
    (appdir / "AppRun").write_text(APPRUN)
    (appdir / "AppRun").chmod(0o755)
    (appdir / "switchkbm.desktop").write_text(DESKTOP)
    icon = KBM / "ui" / "assets" / "icon.png"
    shutil.copy2(icon, appdir / "switchkbm.png")
    shutil.copy2(icon, appdir / ".DirIcon")
    tool = fetch_appimagetool()
    dist = REPO / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / APPIMAGE_NAME
    cmd = [str(tool)] + ([] if has_fuse() else ["--appimage-extract-and-run"]) + [str(appdir), str(out)]
    run(cmd, env=dict(os.environ, ARCH="x86_64"))
    out.chmod(0o755)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-firmware", action="store_true",
                    help="nao recompila o firmware; usa o switch-side/build existente")
    ap.add_argument("--stage-firmware-only", action="store_true",
                    help="so copia o switch-side/build para build/firmware (usado pela CI)")
    args = ap.parse_args(argv)
    os.chdir(REPO)
    if not (args.skip_firmware or args.stage_firmware_only):
        build_firmware()
    fw = stage_firmware()
    if args.stage_firmware_only:
        return
    if not LINUX:
        run([sys.executable, "-m", "pip", "install", "--quiet", "-r", str(KBM / "requirements.txt")])
    built = pack(fw)
    if LINUX:
        out = make_appimage(built)
    else:
        (REPO / "dist").mkdir(exist_ok=True)
        out = REPO / "dist" / "SwitchKBM.exe"
        shutil.copy2(built, out)
    print("OK: %s" % out)


if __name__ == "__main__":
    main()
