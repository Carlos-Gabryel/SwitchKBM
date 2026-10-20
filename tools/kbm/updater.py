"""Atualizacao automatica pelo GitHub Releases: achar, baixar (conferindo o SHA-256) e trocar o .exe.

O Windows nao deixa sobrescrever um .exe aberto, mas deixa renomea-lo: o atual vira
SwitchKBM.exe.old, o novo assume o nome e e aberto; a proxima abertura apaga o .old.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = "Carlos-Gabryel/switch-kbm"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = "SwitchKBM.exe"
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "SwitchKBM"}
NOT_FROZEN_MSG = "Atualização automática só no programa (.exe)"


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class Release:
    tag: str
    version: tuple[int, ...]
    url: str
    size: int
    sha256: str
    html_url: str = field(default="", compare=False)


def can_apply() -> bool:
    """So o programa empacotado (.exe) sabe se trocar."""
    return bool(getattr(sys, "frozen", False))


def parse_version(text: str) -> tuple[int, ...]:
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", str(text).strip())
    if not match:
        raise UpdateError(f"versão inválida: {text!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def _release(opener) -> dict:
    try:
        with opener(urllib.request.Request(API, headers=HEADERS), timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except UpdateError:
        raise
    except Exception as e:      # offline, limite da API, JSON ruim...
        raise UpdateError(f"não foi possível consultar o GitHub ({type(e).__name__}: {e})") from e
    if not isinstance(data, dict):
        raise UpdateError("resposta inesperada do GitHub")
    return data


def latest(opener=urllib.request.urlopen) -> Release | None:
    """Release mais recente com o SwitchKBM.exe (None se nao houver). UpdateError em qualquer falha."""
    data = _release(opener)
    for asset in data.get("assets") or []:
        if asset.get("name") != ASSET:
            continue
        digest = asset.get("digest") or ""
        if not digest.startswith("sha256:"):
            raise UpdateError("o Release não publica o SHA-256 do .exe")
        try:
            return Release(data["tag_name"], parse_version(data["tag_name"]),
                           asset["browser_download_url"], int(asset["size"]),
                           digest.removeprefix("sha256:"), data.get("html_url", ""))
        except (KeyError, TypeError, ValueError) as e:
            raise UpdateError(f"Release malformado ({e})") from e
    return None


def newer(release: Release | None, current: str) -> bool:
    return release is not None and release.version > parse_version(current)


def download(release: Release, folder: Path, opener=urllib.request.urlopen, progress=None) -> Path:
    """Baixa para folder conferindo tamanho e SHA-256. progress(0..1) opcional."""
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / (ASSET + ".part")
    digest, size = hashlib.sha256(), 0
    request = urllib.request.Request(release.url, headers={"User-Agent": HEADERS["User-Agent"]})
    try:
        with opener(request, timeout=60) as resp, open(part, "wb") as out:
            while chunk := resp.read(1 << 16):
                digest.update(chunk)
                out.write(chunk)
                size += len(chunk)
                if progress and release.size:
                    progress(min(1.0, size / release.size))
    except Exception as e:
        part.unlink(missing_ok=True)
        raise UpdateError(f"falha no download ({type(e).__name__}: {e})") from e
    if size != release.size or digest.hexdigest() != release.sha256.lower():
        part.unlink(missing_ok=True)
        raise UpdateError("o download não confere (tamanho ou SHA-256)")
    ready = folder / f"SwitchKBM-{release.tag}.exe"
    part.replace(ready)
    return ready


def apply(new_exe: Path, exe: Path, launch=subprocess.Popen) -> None:
    """Troca exe pelo novo (o antigo vira .old) e abre o novo."""
    old = exe.with_name(exe.name + ".old")
    old.unlink(missing_ok=True)
    exe.rename(old)
    try:
        shutil.move(str(new_exe), str(exe))
    except OSError:
        old.rename(exe)
        raise
    # PyInstaller onefile: sem isto o filho reaproveitaria a pasta temporaria do pai (apagada ao sair)
    launch([str(exe)], close_fds=True, env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1"))


def cleanup(exe: Path) -> None:
    try:
        exe.with_name(exe.name + ".old").unlink(missing_ok=True)
    except OSError:
        pass        # a versao anterior ainda esta fechando; fica para a proxima abertura
