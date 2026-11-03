"""Gera web/test/vectors.json a partir de mapping.py e proto.py (referencia para os testes JS).

Uso: python3 tools/kbm/gen_web_vectors.py
Cada cenario e uma lista de eventos deterministicos com dt fixos; a saida esperada de cada
evento vem do Mapper em Python (accel_noise=0)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mapping  # noqa: E402
import proto  # noqa: E402

OUT = os.path.join(HERE, "..", "..", "web", "test", "vectors.json")
DT = 0.005


class Scenario:
    def __init__(self, name, **cfg):
        self.name = name
        self.cfg = dict(cfg, accel_noise=0)
        self.notes = []
        self.mapper = mapping.Mapper(mapping.Config(**{k: v for k, v in self.cfg.items()
                                                       if k in mapping.Config.__dataclass_fields__}),
                                     notify=self.notes.append)
        self.events = []
        self.t = 0.0

    def _rec(self, ev, ret=None):
        ev["notes"], self.notes[:] = list(self.notes), []
        if ret is not None:
            ev["ret"] = ret
        self.events.append(ev)

    def down(self, k):
        self._rec({"op": "key_down", "key": k}, self.mapper.key_down(mapping.KEY_NAMES[k]) or "")

    def up(self, k):
        self.mapper.key_up(mapping.KEY_NAMES[k])
        self._rec({"op": "key_up", "key": k})

    def btn(self, name, down):
        self.mapper.mouse_button(name, down)
        self._rec({"op": "mouse_button", "name": name, "down": down})

    def wheel(self, d):
        self.mapper.wheel(d, self.t)
        self._rec({"op": "wheel", "dir": d, "now": self.t})

    def move(self, dx, dy):
        self.mapper.mouse_move(dx, dy)
        self._rec({"op": "mouse_move", "dx": dx, "dy": dy})

    def release(self):
        self.mapper.release_all()
        self._rec({"op": "release_all"})

    def tick(self, n=1, captured=True, dt=DT):
        for _ in range(n):
            self.t += dt
            st = self.mapper.build_state(self.t, dt, captured)
            st = {k: (list(v) if isinstance(v, tuple) else v) for k, v in st.items()}
            self._rec({"op": "build", "now": self.t, "dt": dt, "captured": captured, "expect": st})

    def dump(self):
        cfg = {k: v for k, v in self.cfg.items()}
        return {"name": self.name, "config": cfg, "events": self.events}


def scenarios():
    out = []

    s = Scenario("gyro: mouse variado")
    for dx, dy in [(3, -2), (1, 1), (0, 5), (-7, 0), (12, 9), (-1, -1), (0, 0), (25, -30), (2, 3)]:
        s.move(dx, dy)
        s.tick(2)
    s.tick(3)
    out.append(s)

    s = Scenario("gyro: dt irregular, sens e inversao off", invert_yaw=False, invert_pitch=False,
                 gyro_sensitivity=1.7)
    for i, dt in enumerate([0.0042, 0.0061, 0.005, 0.0003, 0.011, 0.0049]):
        s.move(i * 3 - 4, 7 - i * 2)
        s.tick(1, dt=dt)
    out.append(s)

    s = Scenario("gyro: arredondamento metade-par", deg_per_count=0.03125, gyro_sensitivity=1.0)
    for c in range(1, 12):
        s.move(c, -c)
        s.tick(1, dt=1.0)
    out.append(s)

    s = Scenario("gyro: mouse grande satura e devolve residuo")
    s.move(100000, -80000)
    s.tick(8)
    s.move(-50000, 0)
    s.tick(5)
    out.append(s)

    s = Scenario("gyro: deadband, virtual_tilt e theta", virtual_tilt=True, gyro_deadband_units=40)
    for dx, dy in [(0, 20), (1, 0), (0, 400), (5, 600), (0, -3000), (0, 0)]:
        s.move(dx, dy)
        s.tick(3)
    s.release()
    s.tick(2)
    out.append(s)

    s = Scenario("gyro: virtual_tilt limite de pitch", virtual_tilt=True, max_pitch_deg=30.0)
    for _ in range(6):
        s.move(0, 4000)
        s.tick(4)
    out.append(s)

    s = Scenario("stick F11: mouse e drenagem")
    s.down("f11")
    s.up("f11")
    for dx, dy in [(40, 0), (0, -60), (10, 10), (500, 200), (-3, 1), (1000, 0)]:
        s.move(dx, dy)
        s.tick(12)
    s.tick(40)
    s.down("f11")
    s.up("f11")
    s.move(5, 5)
    s.tick(2)
    out.append(s)

    s = Scenario("stick: curva, sens e zona morta", stick_curve=0.6, stick_max=0.8,
                 stick_deadzone_comp=100, stick_sens=2.0, aim_mode="stick")
    for dx, dy in [(8, 8), (-300, 40), (2, -1), (0, 700)]:
        s.move(dx, dy)
        s.tick(15)
    out.append(s)

    s = Scenario("F7/F8 modo giro")
    s.down("f8")
    s.up("f8")
    s.down("f8")
    s.up("f8")
    s.down("f7")
    s.up("f7")
    s.move(10, 10)
    s.tick(2)
    s.down("f8")  # repeat sem soltar
    s.down("f8")
    s.up("f8")
    s.move(10, 10)
    s.tick(2)
    out.append(s)

    s = Scenario("F7/F8 modo analogico", aim_mode="stick")
    s.down("f8")
    s.up("f8")
    s.down("f7")
    s.up("f7")
    s.down("f7")
    s.up("f7")
    s.move(100, 0)
    s.tick(6)
    out.append(s)

    s = Scenario("hotkeys nao viram botao; f12 toggle")
    s.down("f12")
    s.tick(2)
    s.down("f12")
    s.up("f12")
    s.down("f11")
    s.up("f11")
    s.down("f11")
    s.up("f11")
    s.tick(2)
    out.append(s)

    s = Scenario("setas modo giro")
    for combo in (["left"], ["up"], ["right", "down"], ["left", "up"], ["down"]):
        for k in combo:
            s.down(k)
        s.move(4, 4)
        s.tick(3)
        for k in combo:
            s.up(k)
    s.tick(1)
    out.append(s)

    s = Scenario("setas modo analogico", aim_mode="stick", arrow_gyro_dps=120.0)
    for combo in (["left"], ["up"], ["right", "down"], ["left", "up"]):
        for k in combo:
            s.down(k)
        s.move(30, -10)
        s.tick(3)
        for k in combo:
            s.up(k)
    s.tick(2)
    out.append(s)

    s = Scenario("setas como botao/movimento nao miram", move={"up": "up", "down": "down",
                 "left": "left", "right": "right", "walk": "alt"}, arrow_stick_scale=0.6)
    s.down("left")
    s.down("up")
    s.tick(2)
    out.append(s)

    s = Scenario("setas livres com escala", arrow_stick_scale=0.37)
    s.down("right")
    s.down("down")
    s.tick(2)
    s.up("down")
    s.tick(2)
    out.append(s)

    s = Scenario("walk e movimento")
    for combo in (["w"], ["s"], ["a"], ["d"], ["w", "d"], ["s", "a"], ["w", "s"], ["a", "d"]):
        for k in combo:
            s.down(k)
        s.tick(1)
        s.down("alt")
        s.tick(1)
        s.up("alt")
        for k in combo:
            s.up(k)
    s.tick(1)
    out.append(s)

    s = Scenario("walk_scale personalizado e movimento remapeado",
                 walk_scale=0.33, move={"up": "i", "down": "k", "left": "j", "right": "l", "walk": ""})
    for k in ("i", "l", "k", "j"):
        s.down(k)
        s.tick(1)
        s.up(k)
    s.down("alt")
    s.down("i")
    s.down("l")
    s.tick(1)
    out.append(s)

    s = Scenario("movimento com nome desconhecido gera aviso", move={"up": "xyz", "down": "s",
                 "left": "a", "right": "d", "walk": "alt"})
    s.down("w")
    s.down("d")
    s.tick(1)
    out.append(s)

    s = Scenario("wheel pulso", wheel_pulse_ms=40.0)
    s.tick(2)
    s.wheel(1)
    s.tick(10)
    s.wheel(-1)
    s.tick(10)
    s.wheel(1)
    s.wheel(-1)
    s.tick(3)
    out.append(s)

    s = Scenario("botoes L2/R2, mouse e teclas")
    s.btn("lmb", True)
    s.tick(1)
    s.btn("rmb", True)
    s.tick(1)
    s.btn("lmb", False)
    s.btn("mmb", True)
    s.btn("x1", True)
    s.btn("x2", True)
    s.tick(1)
    s.release()
    s.tick(1)
    for k in ("space", "lctrl", "c", "r", "q", "g", "lshift", "tab", "esc", "home", "p", "1", "2", "3", "4"):
        s.down(k)
    s.tick(1)
    for k in ("space", "lctrl", "c", "r", "q", "g", "lshift", "tab", "esc", "home", "p", "1", "2", "3", "4"):
        s.up(k)
    s.tick(1)
    out.append(s)

    s = Scenario("binds personalizados com L2/R2 por teclado", binds={"z": "L2", "x": "R2", "lmb": "A",
                 "wheel_up": "R2", "foo": "A", "y": "NADA", "n": "START"})
    s.down("z")
    s.down("x")
    s.down("n")
    s.btn("lmb", True)
    s.wheel(1)
    s.tick(2)
    out.append(s)

    s = Scenario("nao capturado zera acumuladores")
    s.move(50, 50)
    s.tick(2, captured=False)
    s.tick(1)
    s.down("w")
    s.tick(1, captured=False)
    s.tick(1)
    out.append(s)

    s = Scenario("accel e gyro com yaw/pitch combinados", invert_yaw=True, invert_pitch=False)
    for dx, dy in [(6, 6), (-6, 6), (6, -6), (-6, -6)]:
        s.move(dx, dy)
        s.tick(2)
    out.append(s)
    return out


def crc_vectors():
    datas = [b"", b"\x00", b"\x01\x02\x03", b"123456789", bytes(range(48)), b"\xff" * 33]
    return [{"hex": d.hex(), "crc": proto.crc8(d)} for d in datas]


def frame_vectors():
    cases = [
        dict(),
        dict(seq=7, flags=1, buttons=1, timestamp_ms=70000),
        dict(seq=300, flags=1, battery=200, buttons=0x3FFFF, lx=-512, ly=511, rx=300, ry=-300,
             l2=1023, r2=1023, gyro=(32000, -32000, 5), accel=(1, 8192, -1), timestamp_ms=65535),
        dict(lx=9999, ly=-9999, rx=512, ry=-513, l2=5000, r2=-5, gyro=(40000, -40000, 0),
             accel=(100000, -100000, 0)),
        dict(lx=3.9, ly=-3.9, gyro=(1.9, -1.9, 0.5), accel=(0, 8192.7, 0), timestamp_ms=123456),
    ]
    out = []
    for c in cases:
        args = {k: (list(v) if isinstance(v, tuple) else v) for k, v in c.items()}
        out.append({"args": args, "frame": proto.pack_state(**c).hex()})
    return out


def main():
    data = {
        "crc8": crc_vectors(),
        "packState": frame_vectors(),
        "encodeFrame": [{"type": proto.TYPE_STATUS, "payload": "0001",
                         "frame": proto.encode_frame(proto.TYPE_STATUS, bytes([0, 1])).hex()}],
        "mapping": [s.dump() for s in scenarios()],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    n = sum(len(s["events"]) for s in data["mapping"])
    print("OK: %d cenarios, %d eventos -> %s" % (len(data["mapping"]), n, os.path.normpath(OUT)))


if __name__ == "__main__":
    main()
