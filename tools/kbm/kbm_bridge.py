"""Teclado + mouse do PC -> gamepad virtual via serial (ESP32 Placa-MicroB).

Uso: python tools/kbm/kbm_bridge.py --port COM4 [--config caminho] [--dry-run] [--verbose]
"""
import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import proto  # noqa: E402
from mapping import Config, Mapper, HOTKEY_VKS, VK_F12  # noqa: E402

RATE_HZ = 200
TRIG_MODES = {0: "normal", 1: "stick", 2: "pwm"}

BANNER = """Teclado e mouse -> Switch (bridge)
Hotkeys:
  F12  captura / libera (liberar sempre funciona)
  F11  alterna mira: giroscopio <-> analogico
  F10  troca modo do gatilho no ESP32 (normal -> stick -> pwm)
  F8 / F7  sensibilidade do giro +10% / -10%
Ctrl+C ou fechar o console tambem libera tudo."""


class Bridge:
    def __init__(self, args, cfg):
        self.args = args
        self.mapper = Mapper(cfg, notify=self.say)
        self.lock = threading.Lock()
        self.captured = False
        self.stop = threading.Event()
        self.ser = None
        self.hook = None
        self.seq = 0
        self.parser = proto.StreamParser()
        self.last_mode = None
        self.last_ds5 = None

    def say(self, msg):
        print(msg, flush=True)

    # ---- callbacks da captura (thread principal) ----
    def on_key(self, vk, down):
        with self.lock:
            if not down:
                self.mapper.key_up(vk)
                return
            act = self.mapper.key_down(vk, time.perf_counter())
            if act == "toggle_capture":
                self._toggle_capture()

    def _toggle_capture(self):
        self.captured = not self.captured
        self.mapper.release_all()
        # F12 ja esta marcado como pressionado pelo key_down; release_all limpou, entao
        # o auto-repeat poderia religar. Reinsere para manter a borda.
        self.mapper.pressed.add(VK_F12)
        self.say("CAPTURADO (F12 libera)" if self.captured else "LIBERADO")

    def on_mouse_button(self, name, down):
        with self.lock:
            self.mapper.mouse_button(name, down)

    def on_wheel(self, d):
        with self.lock:
            self.mapper.wheel(d, time.perf_counter())

    def on_move(self, dx, dy):
        with self.lock:
            if self.captured:
                self.mapper.mouse_move(dx, dy)

    def is_captured(self):
        return self.captured

    # ---- serial ----
    def open_serial(self):
        import serial
        s = serial.Serial()
        s.port = self.args.port
        s.baudrate = 115200
        s.timeout = 0
        s.dtr = False   # nao resetar o ESP32
        s.rts = False
        s.open()
        self.ser = s

    def _poll_serial(self):
        data = self.ser.read(4096)
        if not data:
            return
        for ftype, payload in self.parser.feed(data):
            if ftype == proto.TYPE_STATUS and len(payload) >= 2:
                mode, ds5 = payload[0], payload[1]
                if mode != self.last_mode:
                    self.last_mode = mode
                    self.say("Modo gatilho: %s" % TRIG_MODES.get(mode, str(mode)))
                if ds5 != self.last_ds5:
                    self.last_ds5 = ds5
                    self.say("DualSense: %s" % ("conectado" if ds5 else "desconectado"))
        for line in self.parser.pop_text():
            if self.args.verbose:
                self.say("[esp] " + line)

    def _send(self, st):
        ts = int(time.perf_counter() * 1000) & 0xFFFF
        frame = proto.pack_state(seq=self.seq, timestamp_ms=ts, **st)
        self.seq = (self.seq + 1) & 0xFF
        if self.ser:
            self.ser.write(frame)

    def sender_loop(self):
        period = 1.0 / RATE_HZ
        nxt = last = time.perf_counter()
        n = 0
        try:
            while not self.stop.is_set():
                now = time.perf_counter()
                dt = now - last
                last = now
                with self.lock:
                    st = self.mapper.build_state(now, dt, self.captured)
                self._send(st)
                if self.ser:
                    self._poll_serial()
                n += 1
                if self.args.dry_run and n % (RATE_HZ // 5) == 0:
                    self.say(self.fmt_state(st))
                nxt += period
                delay = nxt - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                elif delay < -0.1:
                    nxt = time.perf_counter()
        except Exception as e:
            self.say("erro no envio: %r" % (e,))
            self.stop.set()
            if self.hook:
                self.hook.quit()

    @staticmethod
    def fmt_state(st):
        return ("[dry] fl=%d btn=%05X L=(%d,%d) R=(%d,%d) L2=%d R2=%d gyro=%s" % (
            st["flags"], st["buttons"], st["lx"], st["ly"], st["rx"], st["ry"],
            st["l2"], st["r2"], st["gyro"]))

    def shutdown(self):
        self.stop.set()
        with self.lock:
            self.captured = False
        try:
            for _ in range(5):
                with self.lock:
                    st = self.mapper.build_state(time.perf_counter(), 0.005, False)
                self._send(st)
                time.sleep(0.005)
            if self.ser:
                self.ser.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description="Teclado e mouse do PC -> gamepad virtual (ESP32)")
    ap.add_argument("--port", help="porta COM da Placa-MicroB (ex.: COM4)")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                     "config.json"))
    ap.add_argument("--dry-run", action="store_true", help="sem serial; imprime o estado a 5 Hz")
    ap.add_argument("--verbose", action="store_true", help="mostra linhas de log do ESP")
    args = ap.parse_args()
    if not args.port and not args.dry_run:
        ap.error("--port e obrigatorio (ou use --dry-run)")

    cfg = Config.load(args.config if os.path.exists(args.config) else None)
    br = Bridge(args, cfg)
    for w in br.mapper.warnings:
        print("aviso config: " + w)
    print(BANNER)
    if not args.dry_run:
        br.open_serial()
        print("Serial aberta em %s" % args.port)

    import winput
    br.hook = winput.InputHook(br.on_key, br.on_mouse_button, br.on_wheel, br.on_move,
                               br.is_captured, always_block_vks={VK_F12}, log=br.say)
    try:
        import ctypes
        ctypes.WinDLL("winmm").timeBeginPeriod(1)
    except Exception:
        pass
    th = threading.Thread(target=br.sender_loop, daemon=True)
    th.start()
    print("Pronto. Pressione F12 para capturar.")
    try:
        br.hook.run()
    finally:
        br.stop.set()
        th.join(timeout=1.0)
        br.shutdown()
        br.hook.done.set()
        print("Encerrado.")


if __name__ == "__main__":
    main()
