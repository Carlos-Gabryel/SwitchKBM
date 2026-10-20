import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture  # noqa: E402
import profiles as pf  # noqa: E402
import controller  # noqa: E402
from controller import Controller  # noqa: E402
from kbm_bridge import parse_control  # noqa: E402


def make():
    return Controller(pf.ProfileStore(base=tempfile.mkdtemp(prefix="kbmtest")))


class FakeProc:
    def __init__(self):
        self.pid = 4321
        self.sent = []

    def poll(self):
        return None


class CaptureCommandTests(unittest.TestCase):
    def test_toggle_capture_sends_command(self):
        c = make()
        self.assertFalse(c.toggle_capture())        # parado: nao envia
        c.runner.proc = FakeProc()
        sent, pids = [], []
        c.runner.send = sent.append
        self.assertTrue(c.toggle_capture(pids.append))
        self.assertEqual(sent, ["capture"])
        self.assertEqual(pids, [4321])

    def test_status_prefixes_sem_texto_legado(self):
       self.assertNotIn("Placa-", controller.NO_PORT_MSG)

    def test_parse_control(self):
        self.assertEqual(parse_control("quit\n"), "quit")
        self.assertEqual(parse_control(" Capture \r\n"), "capture")
        self.assertIsNone(parse_control("outra coisa"))
        self.assertIsNone(parse_control(""))


class ControllerTests(unittest.TestCase):
    def test_initial(self):
        c = make()
        self.assertEqual(c.name, pf.DEFAULT_NAME)
        self.assertEqual(c.rows["R1"][0], "g")
        self.assertFalse(c.dirty)

    def test_assign_moves_key(self):
        c = make()
        c.start_capture("B", 0)
        c.on_capture(*capture.key_result(0x47))
        self.assertEqual(c.rows["B"][0], "g")
        self.assertNotIn("g", c.rows["R1"])
        self.assertTrue(c.dirty)
        self.assertIn("saiu de R", c.msg)
        self.assertIsNone(c.waiting)

    def test_f12_not_assignable(self):
        c = make()
        before = c.rows["A"][0]
        c.start_capture("A", 0)
        c.on_capture(*capture.key_result(0x7B))
        self.assertEqual(c.rows["A"][0], before)
        self.assertFalse(c.dirty)

    def test_cancel_capture(self):
        c = make()
        c.start_capture("A", 0)
        c.on_capture(*capture.key_result(0x1B))
        self.assertIsNone(c.waiting)
        self.assertEqual(c.msg, "Cancelado.")

    def test_sens_line_and_save(self):
        c = make()
        c.on_bridge_line("SENS deg_per_count=0.0550")
        self.assertAlmostEqual(c.settings["sens"], 0.055)
        self.assertTrue(c.dirty)
        self.assertEqual(c.collect()["deg_per_count"], 0.055)
        self.assertTrue(c.save())
        self.assertFalse(c.dirty)

    def test_status_prefix_goes_to_status(self):
        c = make()
        c.on_bridge_line("CAPTURADO")
        self.assertEqual(c.stat_extra, "CAPTURADO")
        self.assertEqual(c.status()[0], "stopped")

    def test_settings_mark_dirty_and_clamp(self):
        c = make()
        c.set_setting("walk", "5")
        self.assertTrue(c.dirty)
        self.assertEqual(c.collect()["walk_scale"], 0.95)
        c.set_setting("sens", "abc")
        self.assertEqual(c.collect()["deg_per_count"], 0.05)

    def test_clear_and_restore(self):
        c = make()
        c.clear_row("R1")
        self.assertEqual(c.rows["R1"], ["", ""])
        self.assertTrue(c.dirty)
        c.restore_defaults()
        self.assertEqual(c.rows["R1"][0], "g")

    def test_profiles(self):
        c = make()
        n = c.new_profile("outro")
        c.switch(n)
        self.assertEqual(c.name, n)
        d = c.dup_profile("copia")
        c.switch(d)
        self.assertEqual(c.name, d)
        c.rename("renomeado")
        self.assertEqual(c.name, "renomeado")
        c.delete()
        self.assertNotEqual(c.name, "renomeado")
        self.assertNotIn("renomeado", c.names)

    def test_flash_progress_line(self):
        c = make()
        c.on_flash_line("Writing at 0x00010000... (25 %)")
        self.assertEqual(c.flash_progress, 0.25)


class CaptureMapTests(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(capture.key_result(0x47), ("name", "g"))
        self.assertEqual(capture.key_result(0xA0), ("name", "lshift"))
        self.assertEqual(capture.key_result(0xA5), ("name", "alt"))
        self.assertEqual(capture.key_result(0x1B), ("cancel", None))
        self.assertEqual(capture.key_result(0x7B)[0], "error")
        self.assertEqual(capture.key_result(0xFF)[0], "error")

    def test_mouse(self):
        m = capture
        self.assertEqual(m.mouse_result(m.WM_LBUTTONDOWN), "lmb")
        self.assertEqual(m.mouse_result(m.WM_RBUTTONDOWN), "rmb")
        self.assertEqual(m.mouse_result(m.WM_MBUTTONDOWN), "mmb")
        self.assertEqual(m.mouse_result(m.WM_XBUTTONDOWN, 1 << 16), "x1")
        self.assertEqual(m.mouse_result(m.WM_XBUTTONDOWN, 2 << 16), "x2")
        self.assertEqual(m.mouse_result(m.WM_MOUSEWHEEL, 120 << 16), "wheel_up")
        self.assertEqual(m.mouse_result(m.WM_MOUSEWHEEL, (0x10000 - 120) << 16), "wheel_down")
        self.assertIsNone(m.mouse_result(0x202))      # botao solto nao conta



class BridgeCaptureToggleTest(unittest.TestCase):
    def _bridge(self):
        import kbm_bridge
        from mapping import Config
        return kbm_bridge.Bridge(None, Config())

    def test_button_capture_then_single_f12_releases(self):
        from mapping import VK_F12
        br = self._bridge()
        br._toggle_capture()                    # botao "Capturar" (sem F12 apertado)
        self.assertTrue(br.captured)
        self.assertEqual(br.mapper.key_down(VK_F12), "toggle_capture")   # 1o F12 ja solta

    def test_f12_capture_ignores_autorepeat(self):
        from mapping import VK_F12
        br = self._bridge()
        self.assertEqual(br.mapper.key_down(VK_F12), "toggle_capture")
        br._toggle_capture()
        self.assertEqual(br.mapper.key_down(VK_F12), "repeat")           # segurando F12
        br.mapper.key_up(VK_F12)
        self.assertEqual(br.mapper.key_down(VK_F12), "toggle_capture")


if __name__ == "__main__":
    unittest.main()
