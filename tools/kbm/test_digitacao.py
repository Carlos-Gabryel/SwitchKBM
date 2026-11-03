"""Controller (modo digitacao) e a view Digitacao com app falso."""
import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import profiles as pf  # noqa: E402
from controller import Controller  # noqa: E402


def make():
    return Controller(pf.ProfileStore(base=tempfile.mkdtemp(prefix="kbmtest")))


class FakeProc:
    pid = 1

    def __init__(self):
        self.sent = []
        self.stdin = self

    def poll(self):
        return None

    def write(self, b):
        self.sent.append(b.decode("ascii").strip())

    def flush(self):
        pass


def with_bridge(c):
    c.runner.proc = FakeProc()
    return c.runner.proc


class ControllerTyping(unittest.TestCase):
    def test_lines_and_state_not_logged(self):
        c = make()
        with_bridge(c)
        c.on_bridge_line("DIGITACAO ON")
        self.assertTrue(c.typing_on)
        self.assertIn("DIGITACAO ON", c.log)
        n = len(c.log)
        c.on_bridge_line('DIGITACAO_ESTADO {"cursor": "r1c2", "page": "sym", "pending": 3, "cps": 4.5, "skipped": 1, "busy": true}')
        self.assertEqual(len(c.log), n)
        self.assertEqual(c.typing_state["page"], "sym")
        c.on_bridge_line("DIGITACAO_ESTADO {quebrado")          # nao derruba
        c.on_bridge_line("DIGITACAO OFF")
        self.assertFalse(c.typing_on)
        self.assertEqual(c.typing_state, {})

    def test_prefs_sent_on_enter_and_saved(self):
        c = make()
        proc = with_bridge(c)
        c.set_typing_speed(preset="rapido")
        c.set_typing_strip(True)
        self.assertEqual(c.typing_prefs, {"preset": "rapido", "ms": 34, "stripAccents": True})
        proc.sent.clear()
        c.on_bridge_line("DIGITACAO ON")
        self.assertEqual(proc.sent, ['type {"op": "speed", "hold": 34, "gap": 34}',
                                     'type {"op": "strip", "v": true}'])
        c.set_typing_speed(ms=60)
        self.assertEqual(c.typing_prefs["preset"], "custom")
        c.set_typing_speed(ms=500)                               # fora da faixa: volta ao padrao
        self.assertEqual(c.typing_prefs["ms"], 42)
        st = c.store.load_settings()
        self.assertEqual((st["typing_preset"], st["typing_ms"], st["typing_strip"]), ("normal", 42, True))
        c2 = Controller(c.store)
        self.assertEqual(c2.typing_prefs, {"preset": "normal", "ms": 42, "stripAccents": True})

    def test_send_ascii_json(self):
        c = make()
        proc = with_bridge(c)
        self.assertIsNone(c.typing_send("text", s="Céu ☃"))
        line = proc.sent[-1]
        line.encode("ascii")
        self.assertEqual(json.loads(line[5:]), {"op": "text", "s": "Céu ☃"})

    def test_without_bridge(self):
        c = make()
        c.port = ""
        r = c.typing_send("text", s="x")
        self.assertEqual(r[0], "warn")
        r = c.typing_send("on")                 # tenta iniciar como o botao: sem porta -> mensagem clara
        self.assertEqual(r[0], "warn")
        self.assertIn("porta", r[1].lower())

    def test_capture_blocked_while_typing(self):
        c = make()
        proc = with_bridge(c)
        c.on_bridge_line("DIGITACAO ON")
        self.assertFalse(c.toggle_capture())
        self.assertNotIn("capture", proc.sent)
        c.on_bridge_line("DIGITACAO OFF")
        self.assertTrue(c.toggle_capture())

    def test_stop_clears_typing(self):
        c = make()
        with_bridge(c)
        c.runner.stop = lambda: None
        c.on_bridge_line("DIGITACAO ON")
        c.stop()
        self.assertFalse(c.typing_on)


class ViewTests(unittest.TestCase):
    def setUp(self):
        from ui.views.digitacao import DigitacaoView
        self.ctrl = make()
        self.proc = with_bridge(self.ctrl)
        self.infos = []
        shell = types.SimpleNamespace(
            ctrl=self.ctrl, info=self.infos.append, render=lambda: None,
            page=types.SimpleNamespace(run_task=lambda *a, **k: None, update=lambda: None))
        self.v = DigitacaoView(shell)
        for ctl in (self.v.field, self.v.msg):
            ctl.update = lambda: None
        self.ctrl.on_bridge_line("DIGITACAO ON")
        self.proc.sent.clear()

    def ops(self):
        return [json.loads(s[5:]) for s in self.proc.sent]

    def test_diff_to_ops(self):
        ev = lambda v: types.SimpleNamespace(control=types.SimpleNamespace(value=v))   # noqa: E731
        self.v._changed(ev("oi"))
        self.v._changed(ev("o"))
        self.v._changed(ev("ot"))
        self.assertEqual(self.ops(), [{"op": "text", "s": "oi"}, {"op": "backspace", "n": 1},
                                      {"op": "text", "s": "t"}])

    def test_submit_clears(self):
        self.v.field.value = "abc"
        self.v._prev = "abc"
        self.v._submit()
        self.assertEqual(self.ops(), [{"op": "submit"}])
        self.assertEqual((self.v.field.value, self.v._prev), ("", ""))

    def test_enter_in_field_submits(self):
        ev = lambda v: types.SimpleNamespace(control=types.SimpleNamespace(value=v, update=lambda: None))   # noqa: E731
        self.v.field.value = "oi"
        self.v._changed(ev("oi"))
        self.v._changed(ev("oi\n"))
        self.assertEqual(self.ops(), [{"op": "text", "s": "oi"}, {"op": "submit"}])
        self.assertEqual((self.v.field.value, self.v._prev), ("", ""))

    def test_paste_with_newlines_becomes_spaces(self):
        c = types.SimpleNamespace(value="a\nb", update=lambda: None)
        self.v._changed(types.SimpleNamespace(control=c))
        self.assertEqual(self.ops(), [{"op": "text", "s": "a b"}])
        self.assertEqual(c.value, "a b")

    def test_shortcuts(self):
        K = lambda k: types.SimpleNamespace(key=k)   # noqa: E731
        self.assertTrue(self.v.on_key(K("Arrow Left")))
        self.assertTrue(self.v.on_key(K("Home")))
        self.v.field.value = "x"
        self.assertFalse(self.v.on_key(K("Arrow Left")))       # campo com texto: seta e do campo
        self.assertFalse(self.v.on_key(K("Home")))
        self.assertTrue(self.v.on_key(K("Escape")))
        self.assertEqual(self.v.field.value, "")
        self.assertEqual(self.ops(), [{"op": "nav", "d": "left"}, {"op": "reset"}, {"op": "clear"}])

    def test_cell_and_tab_clicks(self):
        self.v._click("r2c3")
        self.v._click("acc1")
        self.v._click("globe")
        self.assertEqual(self.ops(), [{"op": "cursor", "id": "r2c3"}, {"op": "page", "id": "acc1"},
                                      {"op": "cursor", "id": "acc1"}, {"op": "cursor", "id": "globe"}])

    def test_paint_from_state(self):
        self.ctrl.on_bridge_line('DIGITACAO_ESTADO {"cursor": "r1c8", "page": "acc1", "pending": 2, "cps": 3.0, "skipped": 1, "busy": true}')
        self.v.refresh()
        box, label = self.v.cells["r1c8"]
        self.assertEqual(label.value, "é")
        self.assertEqual(box.bgcolor, "#E8445A")
        self.assertEqual(self.v.cells["r1c7"][0].bgcolor, "#1A1D22")
        self.assertEqual(self.v.cells["acc1"][0].border.top.color, "#3DD68C")    # aba da pagina atual
        self.assertEqual((self.v.c_pending.value, self.v.c_cps.value, self.v.c_skipped.value), ("2", "3.0", "1"))
        self.assertFalse(self.v.field.disabled)

    def test_off_disables_and_ignores(self):
        self.ctrl.on_bridge_line("DIGITACAO OFF")
        self.v.refresh()
        self.assertTrue(self.v.field.disabled)
        self.proc.sent.clear()
        self.v._click("r1c1")
        self.assertFalse(self.v.on_key(types.SimpleNamespace(key="Escape")))
        self.assertEqual(self.proc.sent, [])

    def test_speed_controls(self):
        self.v._preset("seguro")
        self.assertEqual(self.ctrl.typing_prefs["ms"], 50)
        self.v.shell.page.update = lambda: None
        self.v._custom(70)
        self.assertEqual(self.ctrl.typing_prefs, {"preset": "custom", "ms": 70, "stripAccents": False})
        self.assertEqual(self.v.ms_label.value, "70 ms")
        self.proc.sent.clear()
        self.v._test()
        self.v._reopen()
        self.assertEqual(self.ops(), [{"op": "text", "s": "qwertyuiop"}, {"op": "reset"}])




class WinFocusTest(unittest.TestCase):
    def test_script_escapes_title(self):
        import winfocus
        self.assertIn('w.caption === "Switch \\"KBM\\""', winfocus.kwin_script('Switch "KBM"'))

    def test_only_kde_wayland(self):
        import winfocus
        kde = {"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"}
        if sys.platform.startswith("linux"):
            self.assertTrue(winfocus.is_kde_wayland(kde))
        self.assertFalse(winfocus.is_kde_wayland({"XDG_CURRENT_DESKTOP": "GNOME", "XDG_SESSION_TYPE": "wayland"}))
        self.assertFalse(winfocus.is_kde_wayland({"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "x11"}))


if __name__ == "__main__":
    unittest.main()
