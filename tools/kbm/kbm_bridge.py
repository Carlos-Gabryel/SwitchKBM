"""Teclado + mouse do PC -> gamepad virtual via serial (ESP32).

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

BANNER = """Teclado e mouse -> Switch (bridge)
Hotkeys:
  F12  captura / libera (liberar sempre funciona)
  F11  alterna mira: giroscopio <-> analogico
  F8 / F7  sensibilidade do giro +10% / -10%
Ctrl+C ou fechar o console tambem libera tudo."""


def _set_priorities(thread=False):
    """Prioridade alta do processo; com thread=True, maxima para a thread atual (so Windows)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.GetCurrentThread.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k32.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
        if thread:
            k32.SetThreadPriority(k32.GetCurrentThread(), 2)    # THREAD_PRIORITY_HIGHEST
        else:
            k32.SetPriorityClass(k32.GetCurrentProcess(), 0x80)  # HIGH_PRIORITY_CLASS
    except Exception:
        pass


def status_fw_version(payload):
    """Versao do firmware no payload do STATUS (byte 1; firmware antigo envia 0). None se curto demais."""
    return payload[1] if len(payload) >= 2 else None


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
        self.fw_version = None
        # instrumentacao (so contadores)
        self.st_write_max = 0.0

    def say(self, msg):
        print(msg, flush=True)

    # ---- callbacks da captura (thread principal) ----
    def on_key(self, vk, down):
        act = None
        with self.lock:
            if not down:
                self.mapper.key_up(vk)
            else:
                act = self.mapper.key_down(vk, time.perf_counter())
        if act == "toggle_capture":
            self._toggle_capture()

    def _toggle_capture(self):
        # janela/cursor fora do lock (SetForegroundWindow pode reentrar no wnd_proc)
        want = not self.captured
        if want and self.hook:
            try:
                self.hook.begin_capture()
            except Exception as e:
                self.say("erro ao capturar: %r" % (e,))
                self.hook.end_capture()
                return
        elif self.hook:
            self.hook.end_capture()
        with self.lock:
            self.captured = want
            f12_held = VK_F12 in self.mapper.pressed
            self.mapper.release_all()
            # Veio do F12: release_all limpou a tecla e o auto-repeat poderia religar; reinsere
            # para manter a borda. Veio do botao do app: nao reinsere, senao o proximo F12 vira
            # "repeat" e e preciso apertar duas vezes para soltar.
            if f12_held:
                self.mapper.pressed.add(VK_F12)
        self.say("CAPTURADO (F12 libera)" if self.captured else "LIBERADO")

    def on_capture_lost(self):
        # a janela ja foi escondida pelo hook; so zera o estado (mensagem ja impressa)
        with self.lock:
            self.captured = False
            self.mapper.release_all()

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
            if ftype == proto.TYPE_STATUS:
                fw = status_fw_version(payload)
                if fw is not None and fw != self.fw_version:
                    self.fw_version = fw
                    self.say("FIRMWARE v%d" % fw)
        for line in self.parser.pop_text():
            if self.args.verbose:
                self.say("[esp] " + line)

    def _send(self, st):
        ts = int(time.perf_counter() * 1000) & 0xFFFF
        frame = proto.pack_state(seq=self.seq, timestamp_ms=ts, **st)
        self.seq = (self.seq + 1) & 0xFF
        if self.ser:
            t0 = time.perf_counter()
            self.ser.write(frame)
            dt = time.perf_counter() - t0
            if dt > self.st_write_max:
                self.st_write_max = dt

    def sender_loop(self):
        period = 1.0 / RATE_HZ
        _set_priorities(thread=True)
        nxt = last = time.perf_counter()
        n = 0
        st_t = last
        st_tx = 0
        st_gap = 0.0
        st_mev = 0
        try:
            while not self.stop.is_set():
                now = time.perf_counter()
                dt = now - last
                last = now
                with self.lock:
                    st = self.mapper.build_state(now, dt, self.captured)
                if st_tx and dt > st_gap:
                    st_gap = dt
                self._send(st)
                st_tx += 1
                if self.ser:
                    self._poll_serial()
                if now - st_t >= 1.0:
                    if self.captured and self.hook:
                        mev = self.hook.mouse_ev
                        kbm = self.hook.kb_hook_max
                        self.hook.kb_hook_max = 0.0
                        self.say("STATS tx/s=%d gap_max_ms=%.1f mouse_ev/s=%d "
                                 "kb_hook_max_ms=%.2f serial_write_max_ms=%.2f" % (
                                     st_tx, st_gap * 1000, mev - st_mev, kbm * 1000,
                                     self.st_write_max * 1000))
                        st_mev = mev
                    st_t = now
                    st_tx = 0
                    st_gap = 0.0
                    self.st_write_max = 0.0
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


def parse_control(line):
    """Comando do app pai: 'quit' | 'capture' | None (linha desconhecida)."""
    cmd = line.strip().lower()
    return cmd if cmd in ("quit", "capture") else None


def _stdin_watch(br):
    """Le comandos do app pai: 'quit' (ou EOF) encerra como Ctrl+C; 'capture' alterna a captura (como F12)."""
    try:
        for line in sys.stdin:
            cmd = parse_control(line)
            if cmd == "quit":
                break
            if cmd == "capture" and br.hook:
                br.hook.call_soon(br._toggle_capture)     # janela/cursor so na thread do hook
    except Exception:
        pass
    br.stop.set()
    if br.hook:
        br.hook.quit()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Teclado e mouse do PC -> gamepad virtual (ESP32)")
    ap.add_argument("--port", help="porta serial da placa ESP32 (ex.: COM4 no Windows, /dev/ttyUSB0 no Linux)")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                     "config.json"))
    ap.add_argument("--dry-run", action="store_true", help="sem serial; imprime o estado a 5 Hz")
    ap.add_argument("--verbose", action="store_true", help="mostra linhas de log do ESP")
    ap.add_argument("--stdin-control", action="store_true",
                    help="le comandos no stdin: 'quit' (ou EOF) encerra; 'capture' alterna a captura")
    args = ap.parse_args(argv)
    if not args.port and not args.dry_run:
        ap.error("--port e obrigatorio (ou use --dry-run)")

    cfg = Config.load(args.config if os.path.exists(args.config) else None)
    br = Bridge(args, cfg)
    access_errors = ()
    if sys.platform.startswith("linux"):
        import linput
        access_errors = (linput.InputAccessError,)
        try:
            linput.require_access()         # sem permissao em /dev/input: avisa e sai, sem travar
        except linput.InputAccessError as e:
            for line in e.lines:
                print(line, flush=True)
            sys.exit(1)
    for w in br.mapper.warnings:
        print("aviso config: " + w, flush=True)
    print(BANNER, flush=True)
    if not args.dry_run:
        br.open_serial()
        print("Serial aberta em %s" % args.port, flush=True)

    if sys.platform.startswith("linux"):
        inputmod = linput
    else:
        import winput as inputmod
    _set_priorities()
    br.hook = inputmod.InputHook(br.on_key, br.on_mouse_button, br.on_wheel, br.on_move,
                               br.is_captured, always_block_vks={VK_F12}, log=br.say,
                               on_capture_lost=br.on_capture_lost)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.WinDLL("winmm").timeBeginPeriod(1)
        except Exception:
            pass
    th = threading.Thread(target=br.sender_loop, daemon=True)
    th.start()
    if args.stdin_control:
        threading.Thread(target=_stdin_watch, args=(br,), daemon=True).start()
    print("Pronto. Pressione F12 para capturar.", flush=True)
    code = 0
    try:
        br.hook.run()
    except access_errors as e:
        for line in e.lines:
            print(line, flush=True)
        code = 1
    finally:
        br.stop.set()
        th.join(timeout=1.0)
        br.shutdown()
        br.hook.done.set()
        print("Encerrado.", flush=True)
    if code:
        sys.exit(code)


if __name__ == "__main__":
    main()
