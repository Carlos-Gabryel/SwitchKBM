"""Captura de teclado e mouse no Linux via evdev (/dev/input/event*).

Mesma interface do winput.InputHook. Leitura em /dev/input com python-evdev (movimento bruto, sem
aceleracao); capturar = EVIOCGRAB (grab) em todos os teclados/mouses, para a area de trabalho nao
receber nada; liberar = ungrab. Sem grab o F12 e as demais teclas passam normalmente para o
desktop. Tudo roda numa thread so (selectors); os callbacks do usuario devem ser rapidos.
Precisa de permissao de leitura em /dev/input (grupo `input`).
"""
import atexit
import collections
import glob
import os
import selectors
import signal
import threading
import time

from keymap_linux import MOUSE_BUTTONS, code_to_vk

EV_SYN, EV_KEY, EV_REL = 0, 1, 2
SYN_REPORT, SYN_DROPPED = 0, 3
REL_X, REL_Y, REL_WHEEL, REL_WHEEL_HI_RES = 0, 1, 8, 11
KEY_A, KEY_Z, KEY_F12 = 30, 44, 88
HIRES_STEP = 120                 # unidades da roda de alta resolucao por "clique"
RESCAN_S = 1.0                   # hot-plug: reprocura dispositivos a cada 1 s
WATCHDOG_S = 2.0                 # loop sem andar por mais que isso com grab ativo: solta tudo
PENDING_GRAB_S = 2.0             # tecla "presa" (fantasma) por mais que isso: captura mesmo assim

ACCESS_HELP = (
    "ERRO: sem permissão para ler o teclado/mouse (/dev/input/event*).",
    "ERRO: rode: sudo usermod -aG input $USER   (depois saia e entre na sessão)",
    "ERRO: no Fedora Atomic/Bazzite rode antes: grep -E '^input:' /usr/lib/group | sudo tee -a /etc/group",
)
NO_DEVICE = ("ERRO: nenhum teclado ou mouse encontrado em /dev/input.",)


class InputAccessError(Exception):
    """Sem dispositivo legivel. lines = linhas 'ERRO: ...' para o log do app."""

    def __init__(self, lines):
        super().__init__(" ".join(lines))
        self.lines = tuple(lines)


def _evdev():
    import evdev
    return evdev


def list_event_devices():
    """Todos os /dev/input/event*, legiveis ou nao (evdev.list_devices() esconde os sem permissao,
    e sem eles nao da para distinguir 'sem permissao' de 'sem dispositivo')."""
    return sorted(glob.glob("/dev/input/event*"))


def classify(caps):
    """capabilities() do evdev -> (e_teclado, e_mouse, roda_hires)."""
    keys = set(caps.get(EV_KEY, ()))
    rel = set(caps.get(EV_REL, ()))
    kb = KEY_A in keys and KEY_Z in keys and KEY_F12 in keys
    mouse = REL_X in rel and REL_Y in rel
    return kb, mouse, REL_WHEEL_HI_RES in rel


class _Dev:
    def __init__(self, dev, path, kb, mouse, hires):
        self.dev, self.path, self.kb, self.mouse, self.hires = dev, path, kb, mouse, hires
        self.grabbed = False
        self.pending = False        # grab adiado: ha tecla/botao pressionado
        self.pending_since = 0.0
        self.dx = self.dy = 0
        self.wacc = 0

    @property
    def name(self):
        return getattr(self.dev, "name", self.path)

    def ungrab(self):
        if self.grabbed:
            self.grabbed = False
            try:
                self.dev.ungrab()
            except OSError:
                pass            # dispositivo sumiu: o kernel ja soltou


class Scanner:
    """Descobre teclados/mouses legiveis; guarda os que nao interessam para nao reabrir a cada ciclo."""

    def __init__(self, lister=None, opener=None):
        self.lister = lister or list_event_devices
        self.opener = opener or _evdev().InputDevice
        self.ignored = set()
        self.denied = 0

    def scan(self, known):
        """Abre os dispositivos novos (caminhos fora de known). Devolve lista de _Dev."""
        paths = list(self.lister())
        self.ignored &= set(paths)      # no reaproveitado depois de desplugar
        self.denied = 0
        found = []
        for path in paths:
            if path in known or path in self.ignored:
                continue
            try:
                dev = self.opener(path)
            except PermissionError:
                self.denied += 1
                continue
            except OSError:
                continue
            try:
                kb, mouse, hires = classify(dev.capabilities())
            except Exception:
                kb = mouse = hires = False
            if not (kb or mouse):
                self.ignored.add(path)
                dev.close()
                continue
            found.append(_Dev(dev, path, kb, mouse, hires))
        return found

    def error(self):
        return InputAccessError(ACCESS_HELP if self.denied else NO_DEVICE)


def require_access(lister=None, opener=None):
    """Levanta InputAccessError se nenhum teclado/mouse puder ser lido (ex.: fora do grupo input)."""
    sc = Scanner(lister, opener)
    devs = sc.scan(set())
    for d in devs:
        d.dev.close()
    if not devs:
        raise sc.error()
    return len(devs)


class InputHook:
    """Callbacks (iguais aos do winput):
      on_key(vk, down); on_mouse_button(name, down), on_wheel(direction), on_move(dx, dy): so
      quando is_captured(). on_capture_lost nunca dispara (no Linux nao ha conceito de foco).
    Contadores: mouse_ev (relatorios de mouse tratados) e kb_hook_max (sempre 0).
    """

    def __init__(self, on_key, on_mouse_button, on_wheel, on_move, is_captured,
                 always_block_vks=(), log=print, on_capture_lost=None, lister=None, opener=None,
                 clock=time.monotonic):
        self.on_key = on_key
        self.on_mouse_button = on_mouse_button
        self.on_wheel = on_wheel
        self.on_move = on_move
        self.is_captured = is_captured
        self.always_block_vks = set(always_block_vks)   # o grab ja bloqueia; so por compatibilidade
        self.log = log
        self.on_capture_lost = on_capture_lost
        self.mouse_ev = 0
        self.kb_hook_max = 0.0
        self.done = threading.Event()
        self._scanner = Scanner(lister, opener)
        self._devs = {}                 # caminho -> _Dev
        self._capturing = False
        self._sel = None
        self._wake_r = self._wake_w = None
        self._quit = False
        self._calls = collections.deque()
        self._warned = set()
        self._clock = clock
        self._glock = threading.RLock()     # flags de grab: loop x watchdog
        self._beat = clock()
        self.watchdog_s = WATCHDOG_S
        self.pending_grab_s = PENDING_GRAB_S
        self._wd_stop = threading.Event()

    # ---- eventos ----
    def _handle(self, d, ev):
        t, code, value = ev.type, ev.code, ev.value
        if t == EV_KEY:
            name = MOUSE_BUTTONS.get(code)
            if name:
                if value != 2 and self.is_captured():
                    self.mouse_ev += 1
                    self.on_mouse_button(name, value == 1)
                return
            vk = code_to_vk(code)
            if vk is not None:
                try:
                    self.on_key(vk, value != 0)      # 2 = auto-repeat (o Windows tambem manda "down")
                except Exception as e:
                    self.log("erro no tratamento de tecla: %r" % (e,))
            if value == 0:
                self._grab_pending()
        elif t == EV_REL:
            if code == REL_X:
                d.dx += value
            elif code == REL_Y:
                d.dy += value
            elif code == REL_WHEEL and not d.hires:
                self._wheel(value)
            elif code == REL_WHEEL_HI_RES and d.hires:
                d.wacc += value
                while abs(d.wacc) >= HIRES_STEP:
                    step = 1 if d.wacc > 0 else -1
                    d.wacc -= step * HIRES_STEP
                    self._wheel(step)
        elif t == EV_SYN:
            if code == SYN_REPORT:
                if (d.dx or d.dy) and self.is_captured():
                    self.mouse_ev += 1
                    self.on_move(d.dx, d.dy)
                d.dx = d.dy = 0
            elif code == SYN_DROPPED:
                d.dx = d.dy = d.wacc = 0

    def _wheel(self, delta):
        if delta and self.is_captured():
            self.on_wheel(1 if delta > 0 else -1)

    def _read(self, d):
        try:
            events = list(d.dev.read())
        except BlockingIOError:
            return
        except OSError:                 # desplugado
            self._remove(d)
            return
        for ev in events:
            self._handle(d, ev)

    # ---- dispositivos ----
    def _add(self, d):
        try:
            os.set_blocking(d.dev.fd, False)
        except OSError:
            pass
        self._devs[d.path] = d
        self._sel.register(d.dev.fd, selectors.EVENT_READ, d)
        if self._capturing:
            self._try_grab(d)

    def _remove(self, d):
        self._devs.pop(d.path, None)
        try:
            self._sel.unregister(d.dev.fd)
        except (KeyError, ValueError, OSError):
            pass
        d.ungrab()
        try:
            d.dev.close()
        except OSError:
            pass

    def _rescan(self):
        for d in self._scanner.scan(set(self._devs)):
            self._add(d)

    def _try_grab(self, d, force=False):
        with self._glock:
            self._try_grab_locked(d, force)

    def _try_grab_locked(self, d, force):
        if d.grabbed or not self._capturing:
            return
        try:
            held = d.dev.active_keys()
        except OSError:
            held = ()
        if held and force:
            self.log("aviso: %s com tecla presa há mais de %.0fs; capturando mesmo assim"
                     % (d.name, self.pending_grab_s))
        elif held:
            # grab com tecla/botao pressionado deixaria o "solta" so para nos e a tecla presa no
            # desktop (ex.: o proprio F12): espera soltar tudo
            if not d.pending:
                d.pending, d.pending_since = True, self._clock()
            return
        d.pending = False
        try:
            d.dev.grab()
            d.grabbed = True
        except OSError as e:
            if d.path not in self._warned:
                self._warned.add(d.path)
                self.log("aviso: não foi possível capturar %s (%s)" % (d.name, e))

    def _grab_pending(self):
        with self._glock:
            if self._capturing:
                now = self._clock()
                for d in list(self._devs.values()):
                    if d.pending:
                        self._try_grab(d, force=now - d.pending_since > self.pending_grab_s)

    # ---- captura ----
    def begin_capture(self):
        """Grab exclusivo de todos os teclados/mouses. Idempotente."""
        with self._glock:
            if self._capturing:
                return
            self._capturing = True
            self._beat = self._clock()
            for d in list(self._devs.values()):
                self._try_grab(d)

    def end_capture(self):
        """Solta todos os grabs. Idempotente."""
        with self._glock:
            self._capturing = False
            for d in list(self._devs.values()):
                d.pending = False
                d.ungrab()
                d.dx = d.dy = d.wacc = 0

    def _watchdog(self):
        """Thread propria: com a captura ligada e o loop travado (callback preso), solta os grabs
        para o usuario nao ficar sem teclado/mouse (o ioctl e seguro de outra thread)."""
        while not self._wd_stop.wait(min(0.25, self.watchdog_s / 4)):
            with self._glock:
                age = self._clock() - self._beat
                if not self._capturing or age <= self.watchdog_s:
                    continue
                self._capturing = False
                for d in list(self._devs.values()):
                    d.pending = False
                    d.ungrab()
            self.log("aviso: captura liberada (loop travado há %.1fs)" % age)
            if self.on_capture_lost:
                # em outra thread: o callback pode esperar o mesmo lock que travou o loop
                threading.Thread(target=self.on_capture_lost, daemon=True).start()

    def _release_all(self):
        # atexit / ultimo recurso: o kernel tambem solta ao fechar o fd
        with self._glock:
            for d in list(self._devs.values()):
                d.ungrab()

    # ---- controle ----
    def quit(self):
        """Pode ser chamado de qualquer thread."""
        self._quit = True
        self._wake()

    def call_soon(self, fn):
        """Roda fn() na thread do loop. Qualquer thread."""
        self._calls.append(fn)
        return self._wake()

    def _wake(self):
        w = self._wake_w
        if w is None:
            return False        # fica na fila; run() processa ao iniciar
        try:
            os.write(w, b"x")
            return True
        except OSError:
            return False

    def _run_calls(self):
        while self._calls:
            fn = self._calls.popleft()
            try:
                fn()
            except Exception as e:
                self.log("erro no comando: %r" % (e,))

    def run(self):
        """Abre os dispositivos e roda o loop ate quit() / Ctrl+C / SIGTERM. Levanta InputAccessError
        se nenhum teclado/mouse puder ser lido."""
        self._sel = selectors.DefaultSelector()
        self._wake_r, self._wake_w = os.pipe()
        os.set_blocking(self._wake_r, False)
        os.set_blocking(self._wake_w, False)
        self._sel.register(self._wake_r, selectors.EVENT_READ, None)
        old_term = None
        in_main = threading.current_thread() is threading.main_thread()
        if in_main:
            old_term = signal.signal(signal.SIGTERM, lambda *a: self.quit())
        atexit.register(self._release_all)
        try:
            self._rescan()
            if not self._devs:
                raise self._scanner.error()
            next_scan = time.monotonic() + RESCAN_S
            self._wd_stop.clear()
            wd = threading.Thread(target=self._watchdog, daemon=True)
            wd.start()
            while not self._quit:
                self._beat = self._clock()
                self._run_calls()
                self._grab_pending()
                timeout = min(0.25, max(0.0, next_scan - time.monotonic()))
                for key, _ in self._sel.select(timeout):
                    if key.data is None:
                        try:
                            os.read(self._wake_r, 4096)
                        except OSError:
                            pass
                    else:
                        self._read(key.data)
                if time.monotonic() >= next_scan:
                    self._rescan()
                    next_scan = time.monotonic() + RESCAN_S
        finally:
            self._wd_stop.set()
            self.end_capture()
            for d in list(self._devs.values()):
                self._remove(d)
            atexit.unregister(self._release_all)
            if in_main:
                signal.signal(signal.SIGTERM, old_term)
            self._sel.close()
            for fd in (self._wake_r, self._wake_w):
                try:
                    os.close(fd)
                except OSError:
                    pass
            self._wake_r = self._wake_w = None
