"""Teclado + mouse do PC -> gamepad virtual via serial (ESP32).

Uso: python tools/kbm/kbm_bridge.py --port COM4 [--config caminho] [--dry-run] [--verbose]
"""
import argparse
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import proto  # noqa: E402
from mapping import Config, Mapper, HOTKEY_VKS, VK_F9, VK_F12  # noqa: E402
from typing_engine import MAX_PENDING, TypingEngine  # noqa: E402

RATE_HZ = 200
STATE_MIN_S = 0.1                   # DIGITACAO_ESTADO no maximo 10x/s
MAX_TEXT = 2000                     # caracteres por comando "text"
TYPING_BUSY_MSG = "Saia do modo digitação com F9"
TYPING_DIRS = ("up", "down", "left", "right")
QUEUE_OPS = ("text", "backspace", "submit", "nav", "clear", "reset")

BANNER = """Teclado e mouse -> Switch (bridge)
Hotkeys:
  F12  captura / libera (liberar sempre funciona)
  F9   modo digitacao (teclado do Switch 2); F9 de novo volta
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
        # modo digitacao: o motor so e tocado com self.lock
        self.typing = False
        self.resume_capture = False
        self.engine = TypingEngine()
        self._hot = set()               # F9/F12 fisicamente apertadas
        self._typing_edge = {}          # vk -> apertada (borda no modo digitacao)
        self._t0 = time.perf_counter()
        self._state_sent = None
        self._state_at = 0.0
        # instrumentacao (so contadores)
        self.st_write_max = 0.0

    def say(self, msg):
        print(msg, flush=True)

    # ---- callbacks da captura (thread principal) ----
    def on_key(self, vk, down):
        act = None
        with self.lock:
            if vk in (VK_F9, VK_F12):       # borda propria: vale com o Mapper desligado
                (self._hot.add if down else self._hot.discard)(vk)
            if self.typing:
                # Mapper nunca recebe teclas no modo digitacao; so F9 (sai) e F12 (avisa) contam
                if down and vk in (VK_F9, VK_F12):
                    if self._typing_edge.get(vk):
                        act = "repeat"
                    else:
                        act = "toggle_typing" if vk == VK_F9 else "typing_f12"
                if vk in (VK_F9, VK_F12):
                    self._typing_edge[vk] = down
            elif not down:
                self.mapper.key_up(vk)
            else:
                act = self.mapper.key_down(vk, time.perf_counter())
        if act == "toggle_capture":
            self._toggle_capture()
        elif act == "toggle_typing":
            self._set_typing(not self.typing)
        elif act == "typing_f12":
            self.say(TYPING_BUSY_MSG)

    # ---- modo digitacao (chamar na thread do hook, sem o lock) ----
    def _set_typing(self, want):
        if want:
            with self.lock:
                if self.typing:
                    return
                resume = self.captured
                self.typing = True              # antes de soltar a captura: nada de jogo vaza
                self.resume_capture = resume
                self.mapper.release_all()
                self.engine.reset_keyboard()    # cada sessao comeca com o teclado recem-aberto
                self._typing_edge = {vk: True for vk in self._hot}   # tecla ja apertada nao repete
                self._state_sent = None
            if resume and self.captured:
                self._toggle_capture()
            self._allow_parent_foreground()
            self.say("DIGITACAO ON")
        else:
            with self.lock:
                if not self.typing:
                    return
                self.typing = False
                resume, self.resume_capture = self.resume_capture, False
                self.engine.reset_keyboard()
                if VK_F9 in self._hot:          # F9 ainda apertada: o auto-repeat nao pode religar
                    self.mapper.pressed.add(VK_F9)
            self.say("DIGITACAO OFF")
            if resume and not self.captured:
                self._toggle_capture()

    @staticmethod
    def _allow_parent_foreground():
        """Windows: o bridge recebe a tecla F9; deixa o app (processo pai) trazer a janela para frente."""
        if os.name != "nt":
            return
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(os.getppid())
        except Exception:
            pass

    def typing_command(self, obj):
        """Aplica um comando 'type' (dict ja decodificado). Devolve texto de erro ou None."""
        if not isinstance(obj, dict) or not isinstance(obj.get("op"), str):
            return "type: comando invalido"
        op = obj["op"]
        if op in ("on", "off"):
            done = threading.Event()

            def fn():
                try:
                    self._set_typing(op == "on")
                finally:
                    done.set()
            if self.hook:
                self.hook.call_soon(fn)         # captura/janela so na thread do hook
                done.wait(2.0)                  # os comandos seguintes ja veem o novo estado
            else:
                fn()
            return None
        with self.lock:
            e = self.engine
            if op in QUEUE_OPS and not self.typing:
                return "type: modo digitação desligado (ignorado: %s)" % op
            if op == "text":
                s = obj.get("s")
                if not isinstance(s, str):
                    return "type: text exige 's' texto"
                room = max(0, MAX_PENDING - e.pending_count)
                e.enqueue(s[:min(MAX_TEXT, room)])
                if len(s) > room:
                    return "type: fila cheia, texto cortado"
            elif op == "backspace":
                n = obj.get("n", 1)
                if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_PENDING:
                    return "type: backspace exige 'n' inteiro de 1 a %d" % MAX_PENDING
                for _ in range(n):
                    e.backspace_requested()
            elif op == "submit":
                e.enqueue_submit()
            elif op == "clear":
                e.clear_pending()
            elif op == "nav":
                if obj.get("d") not in TYPING_DIRS:
                    return "type: nav exige 'd' up|down|left|right"
                e.press_manual(obj["d"])
            elif op == "reset":
                e.reset_keyboard()
            elif op == "cursor":
                if not isinstance(obj.get("id"), str) or obj["id"] not in e._nodes:
                    return "type: cursor desconhecido"
                e.sync_cursor(obj["id"])
            elif op == "page":
                if not isinstance(obj.get("id"), str) or obj["id"] not in e.layout["pages"]:
                    return "type: página desconhecida"
                e.sync_page(obj["id"])
            elif op == "speed":
                hold, gap = obj.get("hold"), obj.get("gap", obj.get("hold"))
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (hold, gap)):
                    return "type: speed exige 'hold' e 'gap' numéricos (ms)"
                e.set_timing(hold, gap)
            elif op == "strip":
                if not isinstance(obj.get("v"), bool):
                    return "type: strip exige 'v' booleano"
                e.strip_accents = obj["v"]
            else:
                return "type: operação desconhecida: %s" % op[:20]
        return None

    def _typing_state_line(self, now):
        """Linha DIGITACAO_ESTADO se mudou (no maximo 10x/s), senao None. Chamar sem o lock."""
        if now - self._state_at < STATE_MIN_S:
            return None
        with self.lock:
            st = self.engine.state()
        key = json.dumps(st, sort_keys=True)
        if key == self._state_sent:
            return None
        self._state_sent, self._state_at = key, now
        return "DIGITACAO_ESTADO " + json.dumps(st)

    def _typing_buttons_state(self, now):
        """Estado neutro conectado + botoes do motor de digitacao (chamar com o lock)."""
        return {"flags": proto.FLAG_CONNECTED, "battery": 200,
                "buttons": self.engine.tick((now - self._t0) * 1000.0),
                "lx": 0, "ly": 0, "rx": 0, "ry": 0, "l2": 0, "r2": 0,
                "gyro": (0, 0, 0), "accel": (0, 8192, 0)}

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

    def _capture_command(self):
        if self.typing:
            self.say(TYPING_BUSY_MSG)
        else:
            self._toggle_capture()

    def on_capture_lost(self):
        # a janela ja foi escondida pelo hook; so zera o estado (mensagem ja impressa)
        with self.lock:
            self.captured = False
            self.mapper.release_all()

    def on_mouse_button(self, name, down):
        with self.lock:
            if not self.typing:
                self.mapper.mouse_button(name, down)

    def on_wheel(self, d):
        with self.lock:
            if not self.typing:
                self.mapper.wheel(d, time.perf_counter())

    def on_move(self, dx, dy):
        with self.lock:
            if self.captured and not self.typing:
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
                    if self.typing:
                        st = self._typing_buttons_state(now)    # nada do Mapper: nenhum comando de jogo vaza
                    else:
                        st = self.mapper.build_state(now, dt, self.captured)
                    typing = self.typing
                if typing:
                    line = self._typing_state_line(now)
                    if line:
                        self.say(line)
                if st_tx and dt > st_gap:
                    st_gap = dt
                self._send(st)
                st_tx += 1
                if self.ser:
                    self._poll_serial()
                if now - st_t >= 1.0:
                    if self.captured and self.hook and not typing:
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
            self.typing = False
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
    """Comando do app pai: 'quit' | 'capture' | ('type', dict) | ('type_error', motivo) |
    None (linha desconhecida)."""
    text = line.strip()
    cmd = text.lower()
    if cmd in ("quit", "capture"):
        return cmd
    if cmd == "type" or cmd.startswith("type "):
        try:
            obj = json.loads(text[4:])
        except ValueError:
            return ("type_error", "type: JSON invalido")
        if not isinstance(obj, dict):
            return ("type_error", "type: esperado um objeto JSON")
        return ("type", obj)
    return None


def _stdin_watch(br):
    """Le comandos do app pai: 'quit' (ou EOF) encerra como Ctrl+C; 'capture' alterna a captura (como F12);
    'type {json}' controla o modo digitacao."""
    try:
        for line in sys.stdin:
            cmd = parse_control(line)
            if cmd == "quit":
                break
            if cmd == "capture" and br.hook:
                br.hook.call_soon(br._capture_command)    # janela/cursor so na thread do hook
            elif isinstance(cmd, tuple):
                err = cmd[1] if cmd[0] == "type_error" else br.typing_command(cmd[1])
                if err:
                    br.say(err)
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
                    help="le comandos no stdin: 'quit' (ou EOF) encerra; 'capture' alterna a captura; 'type {json}' modo digitacao")
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
                               br.is_captured, always_block_vks={VK_F9, VK_F12}, log=br.say,
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
    print("Pronto. F12 captura; F9 modo digitacao.", flush=True)
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
