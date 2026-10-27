"""Testes do backend Linux (evdev) com dispositivos falsos: nenhum /dev/input real e usado."""
import contextlib
import io
import os
import sys
import threading
import time
import unittest
from collections import namedtuple
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture  # noqa: E402
import controller  # noqa: E402
import profiles as pf  # noqa: E402
import runners  # noqa: E402
from keymap_linux import EVDEV_TO_VK, MOUSE_BUTTONS  # noqa: E402
from mapping import KEY_NAMES, Mapper  # noqa: E402

LINUX = sys.platform.startswith("linux")
Ev = namedtuple("Ev", "type code value")
EV_SYN, EV_KEY, EV_REL = 0, 1, 2
SYN = Ev(EV_SYN, 0, 0)
KEY_F12, KEY_A, KEY_LEFTCTRL = 88, 30, 29
BTN_LEFT, BTN_SIDE = 0x110, 0x113
REL_X, REL_Y, REL_WHEEL, REL_HIRES = 0, 1, 8, 11


class KeyTableTests(unittest.TestCase):
    def test_every_mapping_key_has_an_evdev_code(self):
        have = {Mapper.norm_vk(v) for v in EVDEV_TO_VK.values()}
        missing = [n for n, vk in KEY_NAMES.items() if Mapper.norm_vk(vk) not in have]
        self.assertEqual(missing, [])

    def test_known_codes(self):
        self.assertEqual(EVDEV_TO_VK[30], 0x41)       # KEY_A
        self.assertEqual(EVDEV_TO_VK[88], 0x7B)       # KEY_F12
        self.assertEqual(EVDEV_TO_VK[42], 0xA0)       # KEY_LEFTSHIFT
        self.assertEqual(EVDEV_TO_VK[100], 0xA5)      # KEY_RIGHTALT
        self.assertEqual(EVDEV_TO_VK[125], 0x5B)      # KEY_LEFTMETA
        self.assertEqual(EVDEV_TO_VK[86], 0xE2)       # KEY_102ND
        self.assertEqual(EVDEV_TO_VK[89], 0xC1)       # KEY_RO
        self.assertEqual(set(MOUSE_BUTTONS.values()), {"lmb", "rmb", "mmb", "x1", "x2"})

    def test_values_are_valid_vks(self):
        self.assertEqual(len(EVDEV_TO_VK), len(set(EVDEV_TO_VK)))
        self.assertTrue(all(0 < v < 0x100 for v in EVDEV_TO_VK.values()))


class FakeDev:
    """InputDevice falso: o fd e a ponta de leitura de um pipe (acorda o selector)."""

    def __init__(self, keys=(), rel=(), name="fake"):
        self.name = name
        self.caps = {EV_KEY: list(keys), EV_REL: list(rel)}
        self.r, self.w = os.pipe()
        os.set_blocking(self.r, False)
        self.fd = self.r
        self.events = []
        self.grabs = 0
        self.ungrabs = 0
        self.held = []
        self.closed = False

    def capabilities(self):
        return self.caps

    def push(self, *evs):
        self.events.extend(evs)
        os.write(self.w, b"x")

    def read(self):
        try:
            os.read(self.r, 4096)
        except BlockingIOError:
            raise
        evs, self.events = self.events, []
        yield from evs

    def active_keys(self):
        return list(self.held)

    def grab(self):
        self.grabs += 1

    def ungrab(self):
        self.ungrabs += 1

    def close(self):
        if not self.closed:
            self.closed = True
            os.close(self.r)
            os.close(self.w)


LETTERS = list(range(16, 26)) + [KEY_A, 44, KEY_F12]


def kbd():
    return FakeDev(keys=LETTERS)


def mouse(hires=False):
    return FakeDev(keys=[BTN_LEFT], rel=[REL_X, REL_Y, REL_WHEEL] + ([REL_HIRES] if hires else []))


@unittest.skipUnless(LINUX, "backend evdev so no Linux")
class HookTests(unittest.TestCase):
    def setUp(self):
        import linput
        self.li = linput
        self.captured = False
        self.out = []
        self.devs = {}

    def make(self, devs):
        self.devs = {"/dev/input/event%d" % i: d for i, d in enumerate(devs)}
        o = self.out
        return self.li.InputHook(
            lambda vk, down: o.append(("key", vk, down)), lambda n, d: o.append(("btn", n, d)),
            lambda d: o.append(("wheel", d)), lambda dx, dy: o.append(("move", dx, dy)),
            lambda: self.captured, log=o.append,
            lister=lambda: list(self.devs), opener=lambda p: self.devs[p])

    def start(self, hook):
        self.err = []

        def run():
            try:
                hook.run()
            except BaseException as e:      # noqa: BLE001
                self.err.append(e)
        th = threading.Thread(target=run, daemon=True)
        th.start()
        self.addCleanup(lambda: (hook.quit(), th.join(2)))
        return th

    def wait(self, cond, t=2.0):
        end = time.time() + t
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.005)
        return cond()

    def test_classify(self):
        li = self.li
        self.assertEqual(li.classify(kbd().caps), (True, False, False))
        self.assertEqual(li.classify(mouse(True).caps), (False, True, True))
        self.assertEqual(li.classify({EV_KEY: [116]}), (False, False, False))     # botao de power

    def test_keys_forwarded_even_when_not_captured(self):
        k = kbd()
        hook = self.make([k])
        self.start(hook)
        k.push(Ev(EV_KEY, KEY_F12, 1), SYN, Ev(EV_KEY, KEY_F12, 0), SYN)
        self.assertTrue(self.wait(lambda: len(self.out) >= 2))
        self.assertEqual(self.out[:2], [("key", 0x7B, True), ("key", 0x7B, False)])
        self.assertEqual(k.grabs, 0)

    def test_mouse_translation_when_captured(self):
        m = mouse()
        hook = self.make([m])
        self.captured = True
        self.start(hook)
        m.push(Ev(EV_REL, REL_X, 3), Ev(EV_REL, REL_Y, -2), SYN,
               Ev(EV_REL, REL_X, 1), SYN,
               Ev(EV_KEY, BTN_LEFT, 1), Ev(EV_KEY, BTN_LEFT, 0), Ev(EV_KEY, BTN_SIDE, 1),
               Ev(EV_REL, REL_WHEEL, -1), Ev(EV_REL, REL_WHEEL, 1))
        self.assertTrue(self.wait(lambda: len(self.out) >= 7))
        self.assertEqual(self.out[:7], [("move", 3, -2), ("move", 1, 0), ("btn", "lmb", True),
                                        ("btn", "lmb", False), ("btn", "x1", True),
                                        ("wheel", -1), ("wheel", 1)])
        self.assertEqual(hook.mouse_ev, 5)

    def test_mouse_ignored_when_not_captured(self):
        m = mouse()
        k = kbd()
        hook = self.make([m, k])
        self.start(hook)
        m.push(Ev(EV_REL, REL_X, 5), SYN, Ev(EV_KEY, BTN_LEFT, 1), Ev(EV_REL, REL_WHEEL, 1))
        k.push(Ev(EV_KEY, KEY_A, 1))        # sinal de que os eventos do mouse ja foram lidos
        self.assertTrue(self.wait(lambda: len(self.out) >= 1))
        time.sleep(0.05)
        self.assertEqual(self.out, [("key", 0x41, True)])

    def test_hires_wheel_not_double_counted(self):
        m = mouse(hires=True)
        hook = self.make([m])
        self.captured = True
        self.start(hook)
        # o kernel manda REL_WHEEL e REL_WHEEL_HI_RES juntos: so conta o hi-res
        m.push(Ev(EV_REL, REL_WHEEL, 1), Ev(EV_REL, REL_HIRES, 120), SYN,
               Ev(EV_REL, REL_HIRES, -60), SYN, Ev(EV_REL, REL_HIRES, -60), SYN)
        self.assertTrue(self.wait(lambda: len(self.out) >= 2))
        time.sleep(0.05)
        self.assertEqual(self.out, [("wheel", 1), ("wheel", -1)])

    def test_grab_on_capture_and_ungrab_on_release_and_stop(self):
        k, m = kbd(), mouse()
        hook = self.make([k, m])
        th = self.start(hook)
        hook.call_soon(hook.begin_capture)
        self.assertTrue(self.wait(lambda: k.grabs == 1 and m.grabs == 1))
        hook.call_soon(hook.begin_capture)          # idempotente
        hook.call_soon(hook.end_capture)
        self.assertTrue(self.wait(lambda: k.ungrabs == 1 and m.ungrabs == 1))
        hook.call_soon(hook.begin_capture)
        self.assertTrue(self.wait(lambda: k.grabs == 2))
        hook.quit()                                  # parar com a captura ligada solta tudo
        th.join(2)
        self.assertEqual((k.ungrabs, m.ungrabs), (2, 2))
        self.assertTrue(k.closed and m.closed)
        self.assertEqual(self.err, [])

    def test_ungrab_when_loop_raises(self):
        k = kbd()
        hook = self.make([k])
        hook.on_key = mock.Mock(side_effect=KeyboardInterrupt)       # nao e Exception: escapa do try
        th = self.start(hook)
        hook.call_soon(hook.begin_capture)
        self.assertTrue(self.wait(lambda: k.grabs == 1))
        k.push(Ev(EV_KEY, KEY_A, 1))
        th.join(2)
        self.assertEqual(k.ungrabs, 1)

    def test_grab_waits_until_held_keys_are_released(self):
        k = kbd()
        k.held = [KEY_F12]
        hook = self.make([k])
        self.start(hook)
        hook.call_soon(hook.begin_capture)
        time.sleep(0.1)
        self.assertEqual(k.grabs, 0)
        k.held = []
        k.push(Ev(EV_KEY, KEY_F12, 0))
        self.assertTrue(self.wait(lambda: k.grabs == 1))

    def test_watchdog_releases_grabs_when_loop_hangs(self):
        k, m = kbd(), mouse()
        lost = threading.Event()
        hook = self.make([k, m])
        hook.on_capture_lost = lost.set
        hook.watchdog_s = 0.3
        release = threading.Event()
        hook.on_key = lambda vk, down: release.wait(3)       # callback travado
        self.start(hook)
        self.addCleanup(release.set)
        hook.call_soon(hook.begin_capture)
        self.assertTrue(self.wait(lambda: k.grabs == 1 and m.grabs == 1))
        k.push(Ev(EV_KEY, KEY_A, 1))
        self.assertTrue(self.wait(lambda: k.ungrabs == 1 and m.ungrabs == 1, 1.5))
        self.assertTrue(lost.wait(1))
        self.assertFalse(hook._capturing)
        self.assertTrue(any("loop travado" in str(x) for x in self.out))
        release.set()
        time.sleep(0.1)
        self.assertEqual((k.ungrabs, m.ungrabs), (1, 1))      # sem ungrab em dobro

    def test_phantom_held_key_is_grabbed_after_timeout(self):
        k = kbd()
        k.held = [KEY_F12]          # tecla fantasma: nunca solta
        hook = self.make([k])
        hook.pending_grab_s = 0.2
        self.start(hook)
        hook.call_soon(hook.begin_capture)
        time.sleep(0.1)
        self.assertEqual(k.grabs, 0)
        self.assertTrue(self.wait(lambda: k.grabs == 1, 1.5))
        self.assertTrue(any("tecla presa" in str(x) for x in self.out))

    def test_hotplug_grabs_new_device_while_captured(self):
        k = kbd()
        hook = self.make([k])
        self.start(hook)
        hook.call_soon(hook.begin_capture)
        self.assertTrue(self.wait(lambda: k.grabs == 1))
        m = mouse()
        self.devs["/dev/input/event9"] = m
        with mock.patch.object(self.li, "RESCAN_S", 0.05):
            hook._rescan()
        self.assertEqual(m.grabs, 1)

    def test_no_permission_raises_access_error(self):
        def deny(path):
            raise PermissionError(13, "negado")
        hook = self.li.InputHook(None, None, None, None, lambda: False,
                                 lister=lambda: ["/dev/input/event0"], opener=deny)
        with self.assertRaises(self.li.InputAccessError) as cm:
            hook.run()
        text = " ".join(cm.exception.lines)
        self.assertIn("sudo usermod -aG input $USER", text)
        self.assertIn("/usr/lib/group", text)
        self.assertTrue(all(line.startswith("ERRO:") for line in cm.exception.lines))

    def test_no_devices_at_all(self):
        with self.assertRaises(self.li.InputAccessError) as cm:
            self.li.require_access(lister=lambda: [], opener=None)
        self.assertIn("nenhum teclado", cm.exception.lines[0])

    def test_unrelated_devices_are_closed_and_ignored(self):
        power = FakeDev(keys=[116])
        with self.assertRaises(self.li.InputAccessError):
            self.li.require_access(lister=lambda: ["/dev/input/event0"], opener=lambda p: power)
        self.assertTrue(power.closed)

    def test_bridge_prints_error_and_exits_without_permission(self):
        import kbm_bridge
        err = self.li.InputAccessError(self.li.ACCESS_HELP)
        out = io.StringIO()
        with mock.patch.object(self.li, "require_access", side_effect=err), \
                contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            kbm_bridge.main(["--dry-run"])
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("ERRO: rode: sudo usermod -aG input $USER", out.getvalue())


class CaptureTests(unittest.TestCase):
    def test_evdev_result(self):
        r = capture.evdev_result
        self.assertEqual(r(EV_KEY, KEY_A, 1), ("name", "a"))
        self.assertIsNone(r(EV_KEY, KEY_A, 0))
        self.assertIsNone(r(EV_KEY, KEY_A, 2))
        self.assertEqual(r(EV_KEY, 1, 1), ("cancel", None))                 # Esc
        self.assertEqual(r(EV_KEY, KEY_F12, 1)[0], "error")                 # reservada
        self.assertEqual(r(EV_KEY, 0x2FF, 1)[0], "error")                   # sem VK
        self.assertEqual(r(EV_KEY, BTN_LEFT, 1), ("name", "lmb"))
        self.assertEqual(r(EV_KEY, BTN_SIDE, 1), ("name", "x1"))
        self.assertEqual(r(EV_REL, REL_WHEEL, 1), ("name", "wheel_up"))
        self.assertEqual(r(EV_REL, REL_WHEEL, -1), ("name", "wheel_down"))
        self.assertIsNone(r(EV_REL, REL_X, 4))
        self.assertIsNone(r(EV_REL, REL_WHEEL, 1, hires=True))              # hi-res: ignora o legado
        self.assertEqual(r(EV_REL, REL_HIRES, 120, hires=True), ("name", "wheel_up"))

    @unittest.skipUnless(LINUX, "backend evdev so no Linux")
    def test_linux_capture_returns_first_key(self):
        import linput
        k = kbd()
        got = []
        ev = threading.Event()

        def cb(kind, value):
            got.append((kind, value))
            ev.set()

        with mock.patch("linput._evdev") as m_ev, \
                mock.patch.object(linput, "list_event_devices", lambda: ["/dev/input/event0"]):
            m_ev.return_value.InputDevice = lambda p: k
            cap = capture.Capture()
            cap.start(cb, timeout=3)
            k.push(Ev(EV_KEY, 0x2FF, 1), Ev(EV_KEY, KEY_A, 1))
            self.assertTrue(ev.wait(2))
        self.assertEqual([g[0] for g in got], ["error", "name"])
        self.assertEqual(got[1], ("name", "a"))
        self.assertFalse(cap.active)


class PlatformPiecesTests(unittest.TestCase):
    def test_pick_default_port_by_vid_pid(self):
        ports = [("/dev/ttyS0", "ttyS0 — n/a"), ("/dev/ttyUSB0", "ttyUSB0 — USB Serial"),
                 ("/dev/ttyACM0", "ttyACM0 — ESP32-S3")]
        with mock.patch.dict(runners._USB_IDS, {"/dev/ttyUSB0": (0x1A86, 0x7523)}, clear=True):
            self.assertEqual(runners.pick_default_port(ports), "/dev/ttyUSB0")
        with mock.patch.dict(runners._USB_IDS, {"/dev/ttyACM0": (0x303A, 0x1001)}, clear=True):
            self.assertEqual(runners.pick_default_port(ports), "/dev/ttyACM0")
        with mock.patch.dict(runners._USB_IDS, {}, clear=True):
            self.assertEqual(runners.pick_default_port(ports), "/dev/ttyS0")
            self.assertEqual(runners.pick_default_port([("COM3", "COM3 — Silicon Labs CP210x")]), "COM3")
            self.assertEqual(runners.pick_default_port([]), "")

    def test_creationflags_only_on_windows(self):
        self.assertEqual(runners.CREATE_NO_WINDOW, 0x08000000 if os.name == "nt" else 0)

    @unittest.skipIf(os.name == "nt", "caminhos do Linux")
    def test_data_base_linux(self):
        import tempfile
        home = tempfile.mkdtemp(prefix="kbmhome")
        env = {"HOME": home}
        with mock.patch.dict(os.environ, env), mock.patch.dict(os.environ, {"XDG_DATA_HOME": ""}):
            self.assertEqual(pf.data_base(), os.path.join(home, ".local", "share", "SwitchKBM"))
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": home + "/xdg"}):
                self.assertEqual(pf.data_base(), home + "/xdg/SwitchKBM")
            os.makedirs(os.path.join(home, "SwitchKBM"))        # legado tem prioridade
            self.assertEqual(pf.data_base(), os.path.join(home, "SwitchKBM"))

    def test_controller_shows_bridge_error(self):
        import tempfile
        c = controller.Controller(pf.ProfileStore(base=tempfile.mkdtemp(prefix="kbmtest")))
        c.on_bridge_line("ERRO: sem permissão para ler o teclado/mouse.")
        c.on_bridge_line("ERRO: rode: sudo usermod -aG input $USER")
        c.runner.proc = mock.Mock(returncode=1, poll=lambda: 1)
        ev = c.poll()
        self.assertEqual(ev, [("bridge_exit", 1)])
        self.assertIn("sudo usermod -aG input $USER", c.msg)
        self.assertTrue(c.msg.startswith("Bridge encerrou:"))


if __name__ == "__main__":
    unittest.main()
