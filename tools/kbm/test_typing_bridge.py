"""Bridge no modo digitacao: sem placa, com serial e hook falsos."""
import argparse
import io
import contextlib
import os
import struct
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import proto  # noqa: E402
import kbm_bridge  # noqa: E402
from mapping import Config, HOTKEY_VKS, VK_F9, VK_F12  # noqa: E402
from typing_engine import SWITCH_BTN, TypingEngine  # noqa: E402


class FakeSer:
    def __init__(self):
        self.frames = []        # (t, campos)
        self.parser = proto.StreamParser()

    def write(self, data):
        for ftype, payload in self.parser.feed(bytes(data)):
            if ftype == proto.TYPE_STATE:
                f = struct.unpack(proto.STATE_FMT, payload)
                self.frames.append((time.perf_counter(), f))

    def read(self, n):
        return b""

    def close(self):
        pass


class FakeHook:
    def __init__(self):
        self.began = self.ended = 0

    def begin_capture(self):
        self.began += 1

    def end_capture(self):
        self.ended += 1

    def call_soon(self, fn):
        fn()

    def quit(self):
        pass


def make_bridge():
    args = argparse.Namespace(dry_run=False, verbose=False, port=None)
    br = kbm_bridge.Bridge(args, Config())
    br.ser = FakeSer()
    br.hook = FakeHook()
    out = []
    br.say = out.append
    return br, out


class Running:
    """Roda o sender_loop numa thread."""

    def __init__(self, br):
        self.br = br
        self.th = threading.Thread(target=br.sender_loop, daemon=True)

    def __enter__(self):
        self.th.start()
        return self

    def __exit__(self, *a):
        self.br.stop.set()
        self.th.join(2)


def wait_idle(br, timeout=10):
    end = time.perf_counter() + timeout
    time.sleep(0.05)
    while time.perf_counter() < end:
        with br.lock:
            if not br.engine.busy:
                return
        time.sleep(0.02)
    raise AssertionError("motor nao terminou")


def runs(frames):
    """[(botoes, duracao_s)] dos trechos nao nulos."""
    out = []
    cur = None
    for i, (t, f) in enumerate(frames):
        b = f[3]
        if cur and cur[0] == b:
            cur[2] = t
        else:
            cur = [b, t, t]
            out.append(cur)
    return [(b, t1 - t0) for b, t0, t1 in out if b]


class ParseControlTests(unittest.TestCase):
    def test_contract(self):
        pc = kbm_bridge.parse_control
        self.assertEqual(pc("quit\n"), "quit")
        self.assertEqual(pc(" CAPTURE "), "capture")
        self.assertIsNone(pc("outra coisa"))
        self.assertIsNone(pc("typewriter"))
        self.assertEqual(pc('type {"op":"on"}\n'), ("type", {"op": "on"}))
        self.assertEqual(pc('type {"op":"text","s":"C\\u00e9u"}')[1]["s"], "Céu")
        self.assertEqual(pc("type {quebrado")[0], "type_error")
        self.assertEqual(pc("type [1]")[0], "type_error")
        self.assertEqual(pc("type")[0], "type_error")


class HotkeyTests(unittest.TestCase):
    def test_f9_reserved_everywhere(self):
        import bindings as bd
        from mapping import Mapper, RESERVED_NAMES
        self.assertIn(VK_F9, HOTKEY_VKS)
        self.assertIn("f9", RESERVED_NAMES)
        rows = bd.profile_to_rows({"binds": {"g": "R1"}})
        with self.assertRaises(ValueError):
            bd.assign_key(rows, "B", 0, "f9")
        m = Mapper(Config(binds={"f9": "A", "g": "R1"}))
        self.assertTrue(any("f9" in w for w in m.warnings))
        self.assertEqual(m.key_down(VK_F9), "toggle_typing")
        self.assertEqual(m.key_down(VK_F9), "repeat")
        self.assertEqual(m.build_state(0.0, 0.005, True)["buttons"], 0)     # nao vira botao

    def test_toggle_edge_and_autorepeat(self):
        br, out = make_bridge()
        br.on_key(VK_F9, True)
        self.assertTrue(br.typing)
        br.on_key(VK_F9, True)              # auto-repeat
        self.assertTrue(br.typing)
        br.on_key(VK_F9, False)
        br.on_key(VK_F9, True)
        self.assertFalse(br.typing)
        br.on_key(VK_F9, True)              # auto-repeat depois de sair: nao religa
        self.assertFalse(br.typing)
        br.on_key(VK_F9, False)
        br.on_key(VK_F9, True)
        self.assertTrue(br.typing)
        self.assertEqual([x for x in out if x.startswith("DIGITACAO ")],
                         ["DIGITACAO ON", "DIGITACAO OFF", "DIGITACAO ON"])

    def test_f12_ignored_in_typing(self):
        br, out = make_bridge()
        br._set_typing(True)
        br.on_key(VK_F12, True)
        self.assertFalse(br.captured)
        self.assertEqual(br.hook.began, 0)
        self.assertIn("Saia do modo digitação com F9", out)
        br._capture_command()
        self.assertFalse(br.captured)


class CaptureResumeTests(unittest.TestCase):
    def test_capture_ends_and_resumes(self):
        br, out = make_bridge()
        br._toggle_capture()
        self.assertTrue(br.captured)
        br.on_key(VK_F9, True)
        br.on_key(VK_F9, False)
        self.assertTrue(br.typing)
        self.assertFalse(br.captured)
        self.assertTrue(br.resume_capture)
        self.assertEqual(br.hook.ended, 1)
        br.on_key(VK_F9, True)
        self.assertFalse(br.typing)
        self.assertTrue(br.captured)        # recapturou
        self.assertFalse(br.resume_capture)
        self.assertEqual(br.hook.began, 2)

    def test_no_resume_if_not_captured(self):
        br, _ = make_bridge()
        br._set_typing(True)
        br._set_typing(False)
        self.assertFalse(br.captured)
        self.assertEqual(br.hook.began, 0)


class ResetTests(unittest.TestCase):
    def test_leaving_resets_cursor_and_queue(self):
        br, _ = make_bridge()
        br._set_typing(True)
        br.typing_command({"op": "cursor", "id": "r2c3"})
        br.typing_command({"op": "page", "id": "acc1"})
        br.typing_command({"op": "text", "s": "bom dia"})
        br._set_typing(False)
        self.assertEqual(br.engine.cursor, "r0c0")
        self.assertEqual(br.engine.pending_count, 0)
        self.assertEqual(br.engine.page, "acc1")      # o console lembra a pagina

    def test_entering_resets_cursor(self):
        br, _ = make_bridge()
        br.engine.sync_cursor("r2c3")
        br._set_typing(True)
        self.assertEqual(br.engine.cursor, "r0c0")


class FramesTests(unittest.TestCase):
    def test_no_game_command_leaks(self):
        br, _ = make_bridge()
        br.mapper.cfg.binds["space"] = "A"
        br._toggle_capture()
        with Running(br):
            time.sleep(0.05)
            br.on_key(0x20, True)           # espaco = A no perfil
            time.sleep(0.05)
            br.on_key(VK_F9, True)
            br.on_key(VK_F9, False)
            n = len(br.ser.frames)
            br.on_key(0x20, True)           # tecla fisica no modo digitacao: nada
            br.on_key(0x57, True)           # W
            br.on_mouse_button("lmb", True)
            br.on_wheel(1)
            br.on_move(100, 100)
            time.sleep(0.15)
            typed = br.ser.frames[n:]
        self.assertTrue(typed)
        for _, f in typed:
            seq, flags, battery, buttons, lx, ly, rx, ry, l2, r2, *rest = f
            self.assertEqual((flags, battery, buttons, lx, ly, rx, ry, l2, r2), (1, 200, 0, 0, 0, 0, 0, 0, 0))
            self.assertEqual(tuple(rest[:3]), (0, 0, 0))
            self.assertEqual(tuple(rest[3:6]), (0, 8192, 0))
        self.assertFalse(br.mapper.pressed - {VK_F9})

    def test_oi_sequence_hold_gap_42(self):
        br, out = make_bridge()
        with Running(br):
            self.assertIsNone(br.typing_command({"op": "on"}))
            time.sleep(0.05)
            n0 = len(br.ser.frames)
            self.assertIsNone(br.typing_command({"op": "speed", "hold": 42, "gap": 42}))
            self.assertIsNone(br.typing_command({"op": "text", "s": "Oi"}))
            wait_idle(br)
            time.sleep(0.1)
        ref = TypingEngine(42, 42)
        ref.enqueue("Oi")
        expect = []
        for t in range(3000):
            m = ref.tick(t)
            if m and (not expect or expect[-1][1] != t - 1 or expect[-1][0] != m):
                expect.append([m, t])
            elif m:
                expect[-1][1] = t
        got = runs(br.ser.frames)
        self.assertEqual([b for b, _ in got], [e[0] for e in expect])
        names = {v: k for k, v in SWITCH_BTN.items()}
        self.assertEqual([names[b] for b, _ in got],
                         ["DPAD_DOWN", "DPAD_LEFT", "DPAD_LEFT", "DPAD_LEFT", "DPAD_LEFT", "L3", "A",
                          "DPAD_LEFT", "A"])     # O (baixo, 4x esq, L3, A), i (esq, A)
        allowed = set(SWITCH_BTN.values())
        for b, dur in got:
            self.assertIn(b, allowed)
            self.assertNotIn(b, (SWITCH_BTN["Y"],))
            self.assertGreaterEqual(dur, 0.035)
            self.assertLessEqual(dur, 0.075)
        for _, f in br.ser.frames[n0:]:
            self.assertEqual((f[1], f[2]), (1, 200))
            self.assertEqual(f[4:10], (0, 0, 0, 0, 0, 0))
        self.assertTrue(any(l.startswith("DIGITACAO_ESTADO ") for l in out))


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.br, self.out = make_bridge()
        self.br._set_typing(True)

    def test_validation(self):
        tc = self.br.typing_command
        for bad in (None, [], {}, {"op": 3}, {"op": "xx"}, {"op": "text"}, {"op": "text", "s": 3},
                    {"op": "backspace", "n": 0}, {"op": "backspace", "n": "2"}, {"op": "backspace", "n": True},
                    {"op": "nav", "d": "diag"}, {"op": "cursor", "id": "r9c9"}, {"op": "page", "id": "x"},
                    {"op": "speed", "hold": "a"}, {"op": "strip", "v": 1}):
            self.assertIsInstance(tc(bad), str, bad)
        self.assertEqual(self.br.engine.pending_count, 0)

    def test_ops_apply(self):
        tc, e = self.br.typing_command, self.br.engine
        self.assertIsNone(tc({"op": "cursor", "id": "r2c3"}))
        self.assertIsNone(tc({"op": "page", "id": "sym"}))
        self.assertEqual((e.cursor, e.page), ("r2c3", "sym"))
        self.assertIsNone(tc({"op": "speed", "hold": 60, "gap": 30}))
        self.assertEqual((e.hold_ms, e.gap_ms), (60, 30))
        self.assertIsNone(tc({"op": "speed", "hold": 5, "gap": 500}))
        self.assertEqual((e.hold_ms, e.gap_ms), (25, 100))
        self.assertIsNone(tc({"op": "strip", "v": True}))
        self.assertTrue(e.strip_accents)
        self.assertIsNone(tc({"op": "text", "s": "abc"}))
        self.assertEqual(e.pending_count, 3)
        self.assertIsNone(tc({"op": "backspace", "n": 2}))
        self.assertEqual(e.pending_count, 1)
        self.assertIsNone(tc({"op": "clear"}))
        self.assertEqual(e.pending_count, 0)
        self.assertIsNone(tc({"op": "submit"}))
        self.assertIsNone(tc({"op": "nav", "d": "down"}))
        self.assertIsNone(tc({"op": "reset"}))
        self.assertEqual((e.cursor, e.page), ("r0c0", "sym"))

    def test_queue_ops_ignored_when_off(self):
        self.br._set_typing(False)
        self.assertIn("desligado", self.br.typing_command({"op": "text", "s": "x"}))
        self.assertEqual(self.br.engine.pending_count, 0)
        self.assertIsNone(self.br.typing_command({"op": "speed", "hold": 50}))

    def test_queue_limit(self):
        err = self.br.typing_command({"op": "text", "s": "a" * 600})
        self.assertIn("cortado", err)
        self.assertEqual(self.br.engine.pending_count, kbm_bridge.MAX_PENDING)

    def test_state_line_throttled_and_only_on_change(self):
        br = self.br
        l1 = br._typing_state_line(10.0)
        self.assertTrue(l1.startswith("DIGITACAO_ESTADO {"))
        self.assertIsNone(br._typing_state_line(10.05))       # < 100 ms
        self.assertIsNone(br._typing_state_line(10.5))        # igual
        br.typing_command({"op": "text", "s": "ab"})
        self.assertIn('"pending": 2', br._typing_state_line(10.7))

    def test_stdin_watch_reports_bad_json(self):
        br, out = make_bridge()
        br.hook = None
        old = sys.stdin
        sys.stdin = io.StringIO('type {ruim\ntype {"op":"on"}\nquit\n')
        try:
            kbm_bridge._stdin_watch(br)
        finally:
            sys.stdin = old
        self.assertTrue(any("JSON" in x for x in out))
        self.assertTrue(br.typing)


if __name__ == "__main__":
    unittest.main()
