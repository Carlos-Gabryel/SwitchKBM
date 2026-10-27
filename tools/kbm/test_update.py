import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import controller  # noqa: E402
import flasher  # noqa: E402
import profiles as pf  # noqa: E402
import updater  # noqa: E402
from controller import Controller  # noqa: E402
from kbm_bridge import status_fw_version  # noqa: E402

BODY = b"novo exe" * 100
SHA = hashlib.sha256(BODY).hexdigest()
ASSET = {"name": "SwitchKBM.exe", "browser_download_url": "https://x/S.exe",
         "size": len(BODY), "digest": "sha256:" + SHA}


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def api(assets, tag="v2.1.0"):
    return lambda req, timeout: Resp(json.dumps({"tag_name": tag, "assets": assets}).encode())


def setUpModule():
    # os testes abaixo cobrem o caminho do Windows (.exe); o do Linux esta em LinuxUpdaterTests
    global _pin
    _pin = mock.patch.object(updater, "IS_LINUX", False)
    _pin.start()


def tearDownModule():
    _pin.stop()


def make():
    return Controller(pf.ProfileStore(base=tempfile.mkdtemp(prefix="kbmtest")))


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kbmupd"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_parse_version(self):
        self.assertEqual(updater.parse_version("v2.1.0"), (2, 1, 0))
        self.assertEqual(updater.parse_version("2.0"), (2, 0))
        with self.assertRaises(updater.UpdateError):
            updater.parse_version("beta")

    def test_latest_and_newer(self):
        rel = updater.latest(opener=api([ASSET]))
        self.assertEqual(rel, updater.Release("v2.1.0", (2, 1, 0), "https://x/S.exe", len(BODY), SHA))
        self.assertTrue(updater.newer(rel, "1.0.1"))
        self.assertTrue(updater.newer(rel, "2.0.9"))
        self.assertFalse(updater.newer(rel, "2.1.0"))
        self.assertFalse(updater.newer(rel, "10.0.0"))      # comparacao numerica, nao de texto
        self.assertFalse(updater.newer(None, "1.0.1"))

    def test_asset_lookup(self):
        self.assertIsNone(updater.latest(opener=api([])))
        other = {"name": "outro.zip", "browser_download_url": "https://x/o.zip", "size": 1, "digest": "sha256:aa"}
        self.assertIsNone(updater.latest(opener=api([other])))
        self.assertEqual(updater.latest(opener=api([other, ASSET])).url, "https://x/S.exe")
        with self.assertRaises(updater.UpdateError):
            updater.latest(opener=api([{**ASSET, "digest": None}]))

    def test_latest_errors_are_updateerror(self):
        def offline(req, timeout):
            raise OSError("sem rede")

        with self.assertRaises(updater.UpdateError):
            updater.latest(opener=offline)
        with self.assertRaises(updater.UpdateError):
            updater.latest(opener=lambda req, timeout: Resp(b"<html>rate limit</html>"))
        with self.assertRaises(updater.UpdateError):
            updater.latest(opener=lambda req, timeout: Resp(b"[]"))
        with self.assertRaises(updater.UpdateError):
            updater.latest(opener=api([ASSET], tag="beta"))

    def test_download_checks_size_and_hash(self):
        rel = updater.Release("v2.1.0", (2, 1, 0), "https://x/S.exe", len(BODY), SHA)
        seen = []
        path = updater.download(rel, self.tmp, opener=lambda req, timeout: Resp(BODY), progress=seen.append)
        self.assertEqual(path.read_bytes(), BODY)
        self.assertEqual(path.name, "SwitchKBM-v2.1.0.exe")
        self.assertEqual(seen[-1], 1.0)
        bad = updater.Release("v2.1.0", (2, 1, 0), "https://x/S.exe", len(BODY), "0" * 64)
        with self.assertRaises(updater.UpdateError):
            updater.download(bad, self.tmp, opener=lambda req, timeout: Resp(BODY))
        self.assertFalse((self.tmp / "SwitchKBM.exe.part").exists())

    def test_apply_swaps_relaunches_and_cleanup(self):
        exe = self.tmp / "SwitchKBM.exe"
        exe.write_bytes(b"velho")
        new = self.tmp / "novo.exe"
        new.write_bytes(b"novo")
        launched = []
        updater.apply(new, exe, launch=lambda argv, **kw: launched.append(argv))
        self.assertEqual(exe.read_bytes(), b"novo")
        self.assertEqual((self.tmp / "SwitchKBM.exe.old").read_bytes(), b"velho")
        self.assertEqual(launched, [[str(exe)]])
        updater.cleanup(exe)
        self.assertFalse((self.tmp / "SwitchKBM.exe.old").exists())

    def test_apply_rolls_back_when_the_move_fails(self):
        exe = self.tmp / "SwitchKBM.exe"
        exe.write_bytes(b"velho")
        new = self.tmp / "novo.exe"
        new.write_bytes(b"novo")
        with mock.patch.object(shutil, "move", side_effect=PermissionError("sem permissão")):
            with self.assertRaises(OSError):
                updater.apply(new, exe, launch=lambda argv, **kw: None)
        self.assertEqual(exe.read_bytes(), b"velho")

    def test_can_apply_only_when_frozen(self):
        self.assertFalse(updater.can_apply())
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertTrue(updater.can_apply())


LINUX_BODY = b"novo appimage" * 100
LINUX_SHA = hashlib.sha256(LINUX_BODY).hexdigest()
LINUX_ASSET = {"name": "SwitchKBM-x86_64.AppImage", "browser_download_url": "https://x/S.AppImage",
               "size": len(LINUX_BODY), "digest": "sha256:" + LINUX_SHA}


class LinuxUpdaterTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(updater, "IS_LINUX", True)
        p.start()
        self.addCleanup(p.stop)
        self.tmp = Path(tempfile.mkdtemp(prefix="kbmupd"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_asset_is_the_appimage(self):
        rel = updater.latest(opener=api([ASSET, LINUX_ASSET]))
        self.assertEqual(rel.url, "https://x/S.AppImage")
        self.assertEqual(rel.sha256, LINUX_SHA)
        self.assertIsNone(updater.latest(opener=api([ASSET])))      # so o .exe: nada para o Linux
        bad = dict(LINUX_ASSET, digest="")
        with self.assertRaises(updater.UpdateError):
            updater.latest(opener=api([bad]))

    def test_can_apply_needs_frozen_and_appimage_env(self):
        env = {k: v for k, v in os.environ.items() if k != "APPIMAGE"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(updater.can_apply())
            with mock.patch.object(sys, "frozen", True, create=True):
                self.assertFalse(updater.can_apply())           # empacotado mas fora do AppImage
                self.assertEqual(updater.not_frozen_msg(), updater.NOT_APPIMAGE_MSG)
                os.environ["APPIMAGE"] = "/x/SwitchKBM-x86_64.AppImage"
                self.assertTrue(updater.can_apply())
                self.assertEqual(updater.target_path(), Path("/x/SwitchKBM-x86_64.AppImage"))

    def test_download_verifies_digest(self):
        rel = updater.Release("v2.1.0", (2, 1, 0), "https://x/S.AppImage", len(LINUX_BODY), LINUX_SHA)
        path = updater.download(rel, self.tmp, opener=lambda req, timeout: Resp(LINUX_BODY))
        self.assertEqual(path.name, "SwitchKBM-v2.1.0.AppImage")
        self.assertEqual(path.read_bytes(), LINUX_BODY)
        bad = updater.Release("v2.1.0", (2, 1, 0), "https://x/S.AppImage", len(LINUX_BODY), "0" * 64)
        with self.assertRaises(updater.UpdateError):
            updater.download(bad, self.tmp, opener=lambda req, timeout: Resp(LINUX_BODY))
        self.assertFalse((self.tmp / "SwitchKBM-x86_64.AppImage.part").exists())

    def test_apply_replaces_chmods_and_relaunches(self):
        img = self.tmp / "SwitchKBM-x86_64.AppImage"
        img.write_bytes(b"velho")
        new = self.tmp / "SwitchKBM-v2.1.0.AppImage"
        new.write_bytes(b"novo")
        launched = []
        updater.apply_update(new, img, launch=lambda argv, **kw: launched.append((argv, kw)))
        self.assertEqual(img.read_bytes(), b"novo")
        self.assertFalse(new.exists())
        self.assertEqual(img.stat().st_mode & 0o777, 0o755)
        self.assertEqual(launched[0][0], [str(img)])
        self.assertEqual(launched[0][1]["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_controller_downloads_next_to_appimage_and_replaces_it(self):
        c = make()
        c.check_update(api([LINUX_ASSET], tag="v99.0.0"))
        img = self.tmp / "SwitchKBM-x86_64.AppImage"
        img.write_bytes(b"velho")
        launched = []
        c.stop = lambda: None
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.dict(os.environ, {"APPIMAGE": str(img)}):
            self.assertIsNone(c.install_update(opener=lambda req, timeout: Resp(LINUX_BODY),
                                               launch=lambda argv, **kw: launched.append(argv), wait=True))
        self.assertTrue(c.update_ready)
        self.assertEqual(img.read_bytes(), LINUX_BODY)
        self.assertEqual(launched, [[str(img)]])
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), [img.name])

    def test_controller_refuses_outside_appimage(self):
        c = make()
        c.check_update(api([LINUX_ASSET], tag="v99.0.0"))
        env = {k: v for k, v in os.environ.items() if k != "APPIMAGE"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(sys, "frozen", True, create=True):
            self.assertEqual(c.install_update(), updater.NOT_APPIMAGE_MSG)


class ControllerUpdateTests(unittest.TestCase):
    def test_check_update_states(self):
        c = make()
        self.assertEqual(c.check_update(api([ASSET], tag="v%s" % controller.APP_VERSION)), "uptodate")
        self.assertEqual(c.check_update(api([ASSET], tag="v99.0.0")), "available")
        self.assertEqual(c.update_release.tag, "v99.0.0")
        self.assertEqual(c.check_update(api([])), "uptodate")

    def test_check_update_offline_does_not_raise(self):
        c = make()

        def offline(req, timeout):
            raise OSError("sem rede")

        self.assertEqual(c.check_update(offline), "error")
        self.assertTrue(c.update_error)

    def test_install_refused_when_not_frozen_or_flashing_or_none(self):
        c = make()
        c.check_update(api([ASSET], tag="v99.0.0"))
        self.assertEqual(c.install_update(), updater.NOT_FROZEN_MSG)     # codigo-fonte
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertIsNone(c.update_blocker())
            with mock.patch.object(type(c.flasher), "running", new_callable=mock.PropertyMock, return_value=True):
                self.assertIn("gravação", c.install_update())
            c.update_state = "uptodate"
            self.assertIn("Nenhuma", c.install_update())

    def test_install_stops_bridge_downloads_and_applies(self):
        c = make()
        c.check_update(api([ASSET], tag="v99.0.0"))
        tmp = Path(tempfile.mkdtemp(prefix="kbminst"))
        self.addCleanup(shutil.rmtree, tmp, True)
        exe = tmp / "SwitchKBM.exe"
        exe.write_bytes(b"velho")
        stops, launched = [], []
        c.stop = lambda: stops.append(1)
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertIsNone(c.install_update(exe=exe, opener=lambda req, timeout: Resp(BODY),
                                               launch=lambda argv, **kw: launched.append(argv), wait=True))
        self.assertEqual(stops, [1])
        self.assertTrue(c.update_ready)
        self.assertEqual(exe.read_bytes(), BODY)
        self.assertEqual(launched, [[str(exe)]])

    def test_install_bad_download_goes_to_error(self):
        c = make()
        c.check_update(api([ASSET], tag="v99.0.0"))
        tmp = Path(tempfile.mkdtemp(prefix="kbminst"))
        self.addCleanup(shutil.rmtree, tmp, True)
        exe = tmp / "SwitchKBM.exe"
        exe.write_bytes(b"velho")
        with mock.patch.object(sys, "frozen", True, create=True):
            c.install_update(exe=exe, opener=lambda req, timeout: Resp(b"corrompido"), wait=True)
        self.assertEqual(c.update_state, "error")
        self.assertFalse(c.update_ready)
        self.assertEqual(exe.read_bytes(), b"velho")


class FirmwareVersionTests(unittest.TestCase):
    def test_header_matches_embedded_version(self):
        header = Path(__file__).resolve().parents[2] / "common" / "bridge_proto" / "include" / "bridge_proto.h"
        m = re.search(r"#define\s+BRIDGE_FW_VERSION\s+(\d+)", header.read_text(encoding="utf-8"))
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), flasher.FIRMWARE_VERSION)

    def test_status_fw_version_parsing(self):
        self.assertEqual(status_fw_version(bytes([0, 1])), 1)
        self.assertEqual(status_fw_version(bytes([0, 0])), 0)       # firmware antigo
        self.assertEqual(status_fw_version(bytes([0, 7])), 7)
        self.assertIsNone(status_fw_version(b"\x00"))
        self.assertIsNone(status_fw_version(b""))

    def test_controller_firmware_old_logic(self):
        c = make()
        self.assertFalse(c.firmware_old)                  # desconhecido: sem aviso
        c.on_bridge_line("FIRMWARE v0")
        self.assertEqual(c.fw_version, 0)
        self.assertTrue(c.firmware_old)
        c.on_bridge_line("FIRMWARE v%d" % flasher.FIRMWARE_VERSION)
        self.assertFalse(c.firmware_old)
        c.on_bridge_line("FIRMWARE v%d" % (flasher.FIRMWARE_VERSION + 1))
        self.assertFalse(c.firmware_old)                  # placa mais nova: sem aviso
        c.on_bridge_line("FIRMWARE v0")
        self.assertTrue(c.firmware_old)

    def test_firmware_old_cleared_after_successful_flash(self):
        c = make()
        c.on_bridge_line("FIRMWARE v0")
        c.flash_resume = False
        c.flasher.proc = mock.Mock(returncode=1)
        c.flash_done()
        self.assertTrue(c.firmware_old)                   # falhou: continua desatualizado
        c.flasher.proc = mock.Mock(returncode=0)
        c.flash_done()
        self.assertFalse(c.firmware_old)


if __name__ == "__main__":
    unittest.main()
