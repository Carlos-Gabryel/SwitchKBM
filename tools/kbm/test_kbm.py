import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import proto  # noqa: E402
from mapping import Config, Mapper  # noqa: E402

B = proto.BTN


def bit(name):
    return 1 << B[name]


def mk():
    return Mapper(Config(), notify=lambda m: None)


class ProtoTests(unittest.TestCase):
    def test_crc8_check(self):
        self.assertEqual(proto.crc8(b"123456789"), 0xF4)

    def test_roundtrip_with_garbage_and_text(self):
        f1 = proto.encode_frame(proto.TYPE_STATUS, bytes([1, 1]))
        f2 = proto.encode_frame(proto.TYPE_STATUS, bytes([2, 0]))
        stream = b"\x00\xaa\x13junk\nI (123) log line\r\n" + f1 + b"\xaa\x55\xff\x99texto\n" + f2
        p = proto.StreamParser()
        out = []
        for i in range(0, len(stream), 3):      # em pedacos
            out += p.feed(stream[i:i + 3])
        self.assertEqual(out, [(proto.TYPE_STATUS, bytes([1, 1])), (proto.TYPE_STATUS, bytes([2, 0]))])
        text = "\n".join(p.pop_text())
        self.assertIn("I (123) log line", text)

    def test_bad_crc_resync(self):
        good = proto.encode_frame(proto.TYPE_STATUS, bytes([0, 1]))
        bad = bytearray(good)
        bad[-1] ^= 0xFF
        out = proto.StreamParser().feed(bytes(bad) + good)
        self.assertEqual(out, [(proto.TYPE_STATUS, bytes([0, 1]))])

    def test_pack_state_len(self):
        self.assertEqual(proto.STATE_LEN, 33)
        fr = proto.pack_state(seq=7, flags=1, buttons=bit("A"), timestamp_ms=70000)
        self.assertEqual(len(fr), 38)
        out = proto.StreamParser().feed(fr)
        self.assertEqual(len(out), 1)
        t, pl = out[0]
        self.assertEqual(t, proto.TYPE_STATE)
        v = struct.unpack(proto.STATE_FMT, pl)
        self.assertEqual(v[0], 7)
        self.assertEqual(v[3], 1)
        self.assertEqual(v[-1], 70000 & 0xFFFF)
        self.assertEqual(v[-4:-1], (0, 8192, 0))


class MapperTests(unittest.TestCase):
    def test_not_captured_neutral(self):
        m = mk()
        m.key_down(0x57)
        m.mouse_button("lmb", True)
        m.mouse_move(100, 100)
        st = m.build_state(0, 0.005, False)
        self.assertEqual(st["flags"], 0)
        self.assertEqual((st["buttons"], st["lx"], st["ly"], st["r2"]), (0, 0, 0, 0))
        self.assertEqual(st["gyro"], (0, 0, 0))
        self.assertEqual(st["accel"], (0, 8192, 0))
        st = m.build_state(0.005, 0.005, True)     # acumulador foi limpo
        self.assertEqual(st["gyro"], (0, 0, 0))

    def test_wasd(self):
        m = mk()
        m.key_down(0x57)
        st = m.build_state(0, 0.005, True)
        self.assertEqual((st["lx"], st["ly"]), (0, -512))
        self.assertEqual(st["flags"], 1)
        m.key_up(0x57)
        m.key_down(0x53)
        m.key_down(0x44)
        st = m.build_state(0, 0.005, True)
        self.assertEqual((st["lx"], st["ly"]), (361, 361))
        m.key_up(0x53)
        m.key_down(0x41)     # A e D juntos se anulam
        st = m.build_state(0, 0.005, True)
        self.assertEqual(st["lx"], 0)

    def test_diagonal_and_walk(self):
        m = mk()
        m.key_down(0x57)
        m.key_down(0x41)
        st = m.build_state(0, 0.005, True)
        self.assertEqual((st["lx"], st["ly"]), (-362, -362))
        m.key_down(0xA4)     # LAlt vira walk
        st = m.build_state(0, 0.005, True)
        self.assertAlmostEqual(st["lx"], -181, delta=1)
        m.key_up(0xA4)
        m.key_up(0x41)
        m.key_down(0x12)
        st = m.build_state(0, 0.005, True)
        self.assertEqual(st["ly"], -256)

    def test_buttons(self):
        m = mk()
        m.key_down(0x20)
        m.key_down(0x45)
        st = m.build_state(0, 0.005, True)
        self.assertEqual(st["buttons"], bit("A") | bit("X"))
        m.mouse_button("lmb", True)
        m.mouse_button("rmb", True)
        st = m.build_state(0, 0.005, True)
        self.assertEqual(st["r2"], 1023)
        self.assertEqual(st["l2"], 1023)
        self.assertTrue(st["buttons"] & (1 << 7))
        self.assertTrue(st["buttons"] & (1 << 6))
        m.mouse_button("lmb", False)
        st = m.build_state(0, 0.005, True)
        self.assertEqual(st["r2"], 0)
        self.assertFalse(st["buttons"] & (1 << 7))

    def test_wheel_pulse(self):
        m = mk()
        m.wheel(1, 10.0)
        self.assertTrue(m.build_state(10.0, 0.005, True)["buttons"] & bit("Y"))
        self.assertTrue(m.build_state(10.079, 0.005, True)["buttons"] & bit("Y"))
        self.assertFalse(m.build_state(10.081, 0.005, True)["buttons"] & bit("Y"))

    def test_gyro_basic(self):
        m = mk()
        m.mouse_move(100, 0)
        st = m.build_state(0, 0.005, True)
        self.assertEqual(st["gyro"][1], -16000)
        self.assertEqual(st["gyro"][0], 0)
        self.assertEqual(st["gyro"][2], 0)
        st = m.build_state(0.005, 0.005, True)       # consumido
        self.assertEqual(st["gyro"], (0, 0, 0))

    def test_gyro_pitch_and_no_invert(self):
        cfg = Config(invert_yaw=False, invert_pitch=False)
        m = Mapper(cfg, notify=lambda x: None)
        m.mouse_move(10, -10)
        g = m.build_state(0, 0.005, True)["gyro"]
        self.assertEqual(g, (-1600, 1600, 0))

    def test_gyro_clamp_residual(self):
        m = mk()
        m.mouse_move(1000, 0)
        st = m.build_state(0, 0.005, True)
        self.assertEqual(st["gyro"][1], -32000)
        self.assertAlmostEqual(m.acc_dx, 800.0, places=3)
        st = m.build_state(0.005, 0.005, True)
        self.assertEqual(st["gyro"][1], -32000)
        self.assertAlmostEqual(m.acc_dx, 600.0, places=3)
        for _ in range(3):
            m.build_state(0, 0.005, True)
        self.assertAlmostEqual(m.acc_dx, 0.0, places=3)
        self.assertEqual(m.build_state(0, 0.005, True)["gyro"][1], 0)

    def test_f10_combo(self):
        m = mk()
        self.assertEqual(m.key_down(0x79, 5.0), "cycle_trigger")
        self.assertEqual(m.key_down(0x79, 5.01), "repeat")   # auto-repeat ignorado
        sysb, r2b = bit("SYSTEM"), 1 << 7
        s = m.build_state(5.000, 0.005, True)
        self.assertTrue(s["buttons"] & sysb)
        self.assertFalse(s["buttons"] & r2b)
        self.assertEqual(s["r2"], 0)
        s = m.build_state(5.020, 0.005, True)
        self.assertTrue(s["buttons"] & sysb)
        self.assertTrue(s["buttons"] & r2b)
        self.assertEqual(s["r2"], 1023)
        s = m.build_state(5.050, 0.005, True)
        self.assertTrue(s["buttons"] & sysb)
        self.assertFalse(s["buttons"] & r2b)
        s = m.build_state(5.070, 0.005, True)
        self.assertEqual(s["buttons"], 0)

    def test_f11_stick_mode(self):
        m = mk()
        self.assertEqual(m.key_down(0x7A), "toggle_aim")
        self.assertEqual(m.aim_mode, "stick")
        m.mouse_move(100, -50)
        st = m.build_state(0, 0.005, True)
        # 100/0.005*0.6 = 12000 -> clamp 511 ; -50/0.005*0.6 = -6000 -> -512
        self.assertEqual((st["rx"], st["ry"]), (511, -512))
        self.assertEqual(st["gyro"], (0, 0, 0))
        m.mouse_move(0, 1)
        st = m.build_state(0.005, 0.005, True)
        self.assertEqual(st["rx"], 0)
        self.assertEqual(st["ry"], 120 + 60)       # mouse para baixo = stick para baixo (positivo)
        self.assertEqual(m.build_state(0.01, 0.005, True)["ry"], 0)
        m.key_up(0x7A)
        m.key_down(0x7A)
        self.assertEqual(m.aim_mode, "gyro")

    def test_sensitivity_hotkeys(self):
        m = mk()
        m.key_down(0x77)
        self.assertAlmostEqual(m.sens, 1.1)
        m.key_down(0x76)
        self.assertAlmostEqual(m.sens, 1.0)

    def test_hotkeys_not_buttons(self):
        m = mk()
        for vk in (0x7B, 0x7A, 0x79, 0x77, 0x76):
            self.assertIsNotNone(m.key_down(vk, 0))
        m.combo_start = None
        st = m.build_state(100, 0.005, True)
        self.assertEqual(st["buttons"], 0)
        self.assertEqual((st["lx"], st["ly"], st["l2"], st["r2"]), (0, 0, 0, 0))

    def test_config_load_defaults(self):
        import json
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"deg_per_count": 0.1}, f)
        try:
            c = Config.load(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual(c.deg_per_count, 0.1)
        self.assertEqual(c.stick_gain, 0.6)
        self.assertEqual(c.binds["space"], "A")
        d = Config.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"))
        self.assertEqual(d.binds, Config().binds)
        self.assertEqual(Mapper(d).warnings, [])


import json  # noqa: E402
import tempfile  # noqa: E402

import bindings as bd  # noqa: E402
import mapping  # noqa: E402
import profiles as pf  # noqa: E402


class MoveTests(unittest.TestCase):
    def test_arrows_as_movement(self):
        cfg = Config(move={"up": "up", "down": "down", "left": "left", "right": "right",
                           "walk": "lshift"})
        m = Mapper(cfg, notify=lambda x: None)
        m.key_down(mapping.KEY_NAMES["up"])
        m.key_down(mapping.KEY_NAMES["right"])
        st = m.build_state(1.0, 0.005, True)
        self.assertEqual((st["lx"] > 0, st["ly"] < 0), (True, True))
        m.key_down(0xA0)
        st2 = m.build_state(1.0, 0.005, True)
        self.assertLess(abs(st2["lx"]), abs(st["lx"]))

    def test_wasd_no_longer_moves(self):
        m = Mapper(Config(move={"up": "i", "down": "k", "left": "j", "right": "l",
                                "walk": "alt"}), notify=lambda x: None)
        m.key_down(0x57)
        self.assertEqual(m.build_state(1.0, 0.005, True)["ly"], 0)

    def test_sens_line(self):
        msgs = []
        m = Mapper(Config(), notify=msgs.append)
        m.key_down(mapping.VK_F8)
        line = [x for x in msgs if x.startswith("SENS")][0]
        v = bd.parse_sens_line(line)
        self.assertAlmostEqual(v, 0.055, places=4)
        self.assertIsNone(bd.parse_sens_line("Modo gatilho: stick"))


class KeyTableTests(unittest.TestCase):
    def test_roundtrip(self):
        for name, vk in mapping.KEY_NAMES.items():
            self.assertEqual(mapping.vk_to_name(vk), name)
            self.assertTrue(mapping.display_name(name))

    def test_alt_variants(self):
        self.assertEqual(mapping.vk_to_name(0xA4), "alt")
        self.assertEqual(mapping.display_name("lmb"), "Botão Esq. Mouse")
        self.assertEqual(mapping.display_name("space"), "Espaço")
        self.assertIsNone(mapping.vk_to_name(0xFF))

    def test_tk_event(self):
        self.assertEqual(bd.tk_event_to_name(16, "Shift_R"), "rshift")
        self.assertEqual(bd.tk_event_to_name(18, "Alt_R"), "alt")
        self.assertEqual(bd.tk_event_to_name(0x47, "g"), "g")


class BindingTests(unittest.TestCase):
    def rows(self):
        return bd.profile_to_rows({"binds": {"g": "R1", "space": "A"}})

    def test_reserved_rejected(self):
        for k in ("f7", "f8", "f10", "f11", "f12"):
            with self.assertRaises(ValueError):
                bd.assign_key(self.rows(), "B", 0, k)

    def test_move_key(self):
        new, moved = bd.assign_key(self.rows(), "B", 0, "g")
        self.assertEqual(moved, "R1")
        self.assertEqual(new["B"][0], "g")
        self.assertNotIn("g", new["R1"])

    def test_same_slot_noop(self):
        new, moved = bd.assign_key(self.rows(), "R1", 0, "g")
        self.assertIsNone(moved)

    def test_move_row_conflict(self):
        new, moved = bd.assign_key(self.rows(), "B", 0, "w")
        self.assertEqual(moved, "move:up")
        self.assertEqual(new["move:up"][0], "")

    def test_profile_roundtrip(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        with open(path, encoding="utf-8") as f:
            rows = bd.profile_to_rows(json.load(f))
        data = bd.rows_to_profile(rows, {})
        self.assertEqual(data["binds"], mapping.DEFAULT_BINDS)
        self.assertEqual(data["move"], mapping.DEFAULT_MOVE)
        cfg = Config(**{k: v for k, v in data.items() if k in Config.__dataclass_fields__})
        self.assertEqual(Mapper(cfg, notify=lambda x: None).warnings, [])


class ProfileTests(unittest.TestCase):
    def test_default_created(self):
        with tempfile.TemporaryDirectory() as d:
            s = pf.ProfileStore(base=d)
            self.assertEqual(s.names(), [pf.DEFAULT_NAME])
            self.assertEqual(s.load(pf.DEFAULT_NAME)["move"], mapping.DEFAULT_MOVE)

    def test_migrate_legacy(self):
        with tempfile.TemporaryDirectory() as d:
            legacy = os.path.join(d, "config.json")
            with open(legacy, "w", encoding="utf-8") as f:
                json.dump({"deg_per_count": 0.09, "binds": {"x": "A"}}, f)
            s = pf.ProfileStore(base=d)
            p = s.load(pf.DEFAULT_NAME)
            self.assertEqual(p["deg_per_count"], 0.09)
            self.assertEqual(p["binds"], {"x": "A"})
            self.assertIn("move", p)

    def test_crud_and_settings(self):
        with tempfile.TemporaryDirectory() as d:
            s = pf.ProfileStore(base=d)
            s.create("Jogo X")
            s.duplicate("Jogo X", "Jogo Y")
            self.assertEqual(s.rename("Jogo Y", "Jogo Z"), "Jogo Z")
            with self.assertRaises(ValueError):
                s.create("Jogo X")
            s.delete("Jogo Z")
            self.assertEqual(s.names(), ["Jogo X", pf.DEFAULT_NAME])
            s.save_settings(port="COM4", last_profile="Jogo X")
            self.assertEqual(s.load_settings()["port"], "COM4")
            # sensibilidade fica no perfil, nao nos settings
            self.assertNotIn("deg_per_count", s.load_settings())


if __name__ == "__main__":
    unittest.main()
