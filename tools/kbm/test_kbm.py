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


def grav(theta, tilt=False):
    import math
    r = math.radians(theta) if tilt else 0.0
    return (0, round(8192 * math.cos(r)), round(-8192 * math.sin(r)))


class MapperTests(unittest.TestCase):
    def test_accel_noise_only_when_moving(self):
        m = mk()
        st = m.build_state(0, 0.005, True)
        self.assertEqual(st["accel"], (0, 8192, 0))
        seen = set()
        for _ in range(200):
            m.mouse_move(5, -5 if _ % 2 else 5)  # pitch oscila perto de 0
            a = m.build_state(0, 0.005, True)["accel"]
            g = grav(m.theta)
            self.assertTrue(all(abs(a[i] - g[i]) <= 41 for i in range(3)))
            seen.add(a)
        self.assertGreater(len(seen), 10)

    def test_accel_noise_disabled_and_deadband(self):
        m = Mapper(Config(accel_noise=0), notify=lambda x: None)
        m.mouse_move(5, 5)
        self.assertEqual(m.build_state(0, 0.005, True)["accel"], grav(m.theta))
        m = Mapper(Config(gyro_deadband_units=100000), notify=lambda x: None)
        m.mouse_move(5, 5)
        st = m.build_state(0, 0.005, True)
        self.assertEqual(st["gyro"], (0, 0, 0))
        self.assertEqual(st["accel"], (0, 8192, 0))

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
        self.assertEqual(g[:2], (-1600, 1600))
        self.assertLessEqual(abs(g[2]), 20)  # theta = -0.5 grau: yaw quase todo em y

    def test_virtual_pitch_clamps_and_tilts_gravity(self):
        m = Mapper(Config(virtual_tilt=True), notify=lambda x: None)
        for _ in range(400):  # bem mais que 80 graus para cima
            m.mouse_move(0, -100)
            st = m.build_state(0, 0.005, True)
        self.assertAlmostEqual(m.theta, 80.0)
        self.assertEqual(st["gyro"][0], 0)  # no limite nao gira mais
        m.mouse_move(100, 0)  # yaw em torno da vertical do mundo
        st = m.build_state(0, 0.005, True)
        g, a = st["gyro"], grav(m.theta, True)
        self.assertEqual(g[0], 0)
        # gyro paralelo a gravidade no referencial do controle
        self.assertAlmostEqual(g[1] * a[2] - g[2] * a[1], 0, delta=abs(g[1]) * 8192 * 0.01)
        m.release_all()
        self.assertEqual(m.theta, 0.0)

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
        for vk in (0x7B, 0x7A, 0x77, 0x76):
            self.assertIsNotNone(m.key_down(vk, 0))
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
        self.assertIsNone(bd.parse_sens_line("CAPTURADO"))


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


class BindingTests(unittest.TestCase):
    def rows(self):
        return bd.profile_to_rows({"binds": {"g": "R1", "space": "A"}})

    def test_reserved_rejected(self):
        for k in ("f7", "f8", "f11", "f12"):
            with self.assertRaises(ValueError):
                bd.assign_key(self.rows(), "B", 0, k)

    def test_f10_assignable(self):
        new, _ = bd.assign_key(self.rows(), "B", 0, "f10")
        self.assertEqual(new["B"][0], "f10")

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

    def test_migrate_data_copies_old_profiles(self):
        with tempfile.TemporaryDirectory() as d:
            old, new = os.path.join(d, "old"), os.path.join(d, "new")
            os.makedirs(os.path.join(old, "profiles"))
            with open(os.path.join(old, "profiles", "Fortnite.json"), "w", encoding="utf-8") as f:
                f.write("{}")
            with open(os.path.join(old, "settings.json"), "w", encoding="utf-8") as f:
                f.write('{"port": "COM5"}')
            self.assertTrue(pf.migrate_data(old, new))
            self.assertTrue(os.path.isfile(os.path.join(new, "profiles", "Fortnite.json")))
            self.assertTrue(os.path.isfile(os.path.join(new, "settings.json")))
            self.assertTrue(os.path.isfile(os.path.join(old, "profiles", "Fortnite.json")))  # nao apaga
            self.assertFalse(pf.migrate_data(old, new))     # ja migrado: nao sobrescreve

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


class ArrowAimTests(unittest.TestCase):
    L, U, R, D = 0x25, 0x26, 0x27, 0x28

    @staticmethod
    def mp(**kw):
        return Mapper(Config(**kw), notify=lambda x: None)

    def test_gyro_mode_arrows_stick(self):
        m = self.mp()
        m.key_down(self.U)
        m.key_down(self.R)
        st = m.build_state(1.0, 0.005, True)
        self.assertEqual(st["rx"], round(511 * 0.7071))
        self.assertEqual(st["ry"], round(-512 * 0.7071))
        self.assertEqual(st["gyro"], (0, 0, 0))

    def test_gyro_mode_left(self):
        m = self.mp()
        m.key_down(self.L)
        st = m.build_state(1.0, 0.005, True)
        self.assertEqual((st["rx"], st["ry"]), (-512, 0))

    def _ref_gyro(self, dx, dy):
        m = self.mp()
        m.mouse_move(dx, dy)
        return m.build_state(1.0, 0.005, True)["gyro"]

    def test_stick_mode_right_arrow_gyro(self):
        m = self.mp(aim_mode="stick")
        m.key_down(self.R)
        st = m.build_state(1.0, 0.005, True)
        self.assertEqual((st["rx"], st["ry"]), (0, 0))
        ref = self._ref_gyro(50, 0)
        self.assertNotEqual(st["gyro"][1], 0)
        self.assertEqual(st["gyro"][1] > 0, ref[1] > 0)
        self.assertEqual(st["gyro"][1], -1440)

    def test_stick_mode_up_arrow_pitch_sign(self):
        m = self.mp(aim_mode="stick")
        m.key_down(self.U)
        st = m.build_state(1.0, 0.005, True)
        ref = self._ref_gyro(0, -50)
        self.assertNotEqual(st["gyro"][0], 0)
        self.assertEqual(st["gyro"][0] > 0, ref[0] > 0)

    def test_arrow_as_move_keeps_function(self):
        mv = {"up": "up", "down": "down", "left": "left", "right": "right", "walk": "alt"}
        m = self.mp(move=mv)
        m.key_down(self.U)
        st = m.build_state(1.0, 0.005, True)
        self.assertEqual((st["ly"], st["rx"], st["ry"]), (-512, 0, 0))

    def test_arrow_as_button_keeps_function(self):
        m = self.mp(binds={"up": "A"})
        m.key_down(self.U)
        st = m.build_state(1.0, 0.005, True)
        self.assertTrue(st["buttons"] & (1 << B["A"]))
        self.assertEqual(st["ry"], 0)

    def test_mouse_and_arrows_together_in_stick_mode(self):
        m = self.mp(aim_mode="stick")
        m.key_down(self.U)
        m.mouse_move(100, 0)
        st = m.build_state(1.0, 0.005, True)
        self.assertGreater(st["rx"], 0)
        self.assertNotEqual(st["gyro"][0], 0)


class FlasherTests(unittest.TestCase):
    def setUp(self):
        import json
        import shutil
        import tempfile
        self.d = tempfile.mkdtemp(prefix="kbmfw")
        self.addCleanup(shutil.rmtree, self.d, True)
        self.files = {"0x10000": "switch_side.bin", "0x1000": "bootloader/bootloader.bin",
                      "0x8000": "partition_table/partition-table.bin"}
        for rel in self.files.values():
            os.makedirs(os.path.dirname(os.path.join(self.d, rel)), exist_ok=True)
            open(os.path.join(self.d, rel), "wb").close()
        self.manifest = {"write_flash_args": ["--flash_mode", "dio"], "flash_files": self.files,
                         "extra_esptool_args": {"after": "hard_reset", "before": "default_reset",
                                                "stub": True, "chip": "esp32"}}
        with open(os.path.join(self.d, "flasher_args.json"), "w") as f:
            json.dump(self.manifest, f)

    def test_args_order_and_paths(self):
        import flasher
        a = flasher.esptool_args("COM9", self.d, flasher.load_manifest(self.d))
        self.assertEqual(a[:4], ["--chip", "esp32", "--port", "COM9"])
        self.assertIn("default_reset", a)
        self.assertIn("hard_reset", a)
        self.assertNotIn("--no-stub", a)
        i = a.index("write_flash")
        tail = a[i + 1:]
        self.assertEqual(tail[:2], ["--flash_mode", "dio"])
        pairs = tail[2:]
        self.assertEqual(pairs[0::2], ["0x1000", "0x8000", "0x10000"])
        self.assertTrue(all(os.path.isabs(x) for x in pairs[1::2]))

    def test_no_stub(self):
        import flasher
        self.manifest["extra_esptool_args"]["stub"] = False
        self.assertIn("--no-stub", flasher.esptool_args("COM9", self.d, self.manifest))

    def test_missing_bin_raises(self):
        import flasher
        os.remove(os.path.join(self.d, "switch_side.bin"))
        with self.assertRaises(FileNotFoundError):
            flasher.load_manifest(self.d)


if __name__ == "__main__":
    unittest.main()
