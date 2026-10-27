"""Captura de uma tecla/botao do mouse sem Tk: hooks de baixo nivel temporarios (so enquanto uma
celula espera). O primeiro evento 'para baixo' depois do inicio vale e e engolido."""
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

import bindings as bd
from mapping import vk_to_name

WH_MOUSE_LL = 14
WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN = 0x201, 0x204, 0x207
WM_MOUSEWHEEL, WM_XBUTTONDOWN = 0x20A, 0x20B
VK_ESCAPE = 0x1B
TIMEOUT_S = 10.0


def key_result(vk):
    """VK -> ('name', nome) | ('cancel', None) | ('error', mensagem)."""
    if vk == VK_ESCAPE:
        return "cancel", None
    name = vk_to_name(vk)
    if name is None:
        return "error", "Tecla não suportada (código %s)." % vk
    err = bd.check_key(name)
    if err:
        return "error", "Aviso: %s" % err
    return "name", name


def mouse_result(msg, data=0):
    """Mensagem WM_*BUTTONDOWN / WM_MOUSEWHEEL (+ mouseData) -> nome ou None (ignorar)."""
    if msg == WM_LBUTTONDOWN:
        return "lmb"
    if msg == WM_RBUTTONDOWN:
        return "rmb"
    if msg == WM_MBUTTONDOWN:
        return "mmb"
    hi = (data >> 16) & 0xFFFF
    if msg == WM_XBUTTONDOWN:
        return {1: "x1", 2: "x2"}.get(hi)
    if msg == WM_MOUSEWHEEL:
        delta = hi - 0x10000 if hi & 0x8000 else hi
        if delta:
            return "wheel_up" if delta > 0 else "wheel_down"
    return None


class Capture:
    """start(callback) instala os hooks numa thread propria; callback(kind, value) roda nessa thread
    com kind = 'name' | 'cancel' | 'error'. 'error' (tecla invalida) nao encerra a captura."""

    def __init__(self):
        self._thread = None
        self._tid = 0
        self._lock = threading.Lock()
        self._done = True

    @property
    def active(self):
        return not self._done

    def start(self, callback, timeout=TIMEOUT_S):
        self.cancel(notify=False)
        self._done = False
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(callback, timeout, ready), daemon=True)
        self._thread.start()
        ready.wait(2)

    def cancel(self, notify=True):
        with self._lock:
            if self._done:
                return
            self._done = True
        self._quit()

    def _quit(self):
        import winput
        if self._tid:
            winput.user32.PostThreadMessageW(self._tid, winput.WM_QUIT, 0, 0)

    def _finish(self, callback, kind, value):
        """Marca como concluida (uma vez) e avisa."""
        with self._lock:
            if self._done:
                return False
            self._done = True
        self._quit()
        callback(kind, value)
        return True

    def _run(self, callback, timeout, ready):
        import winput
        u32, k32 = winput.user32, winput.kernel32

        class MSLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long), ("mouseData", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", winput.ULONG_PTR)]

        hooks = []

        def kb_proc(code, wparam, lparam):
            if code == 0 and wparam in (winput.WM_KEYDOWN, winput.WM_SYSKEYDOWN) and not self._done:
                info = ctypes.cast(lparam, ctypes.POINTER(winput.KBDLLHOOKSTRUCT)).contents
                if not info.flags & winput.LLKHF_INJECTED:
                    kind, value = key_result(info.vkCode)
                    if kind == "error":
                        callback(kind, value)
                    else:
                        self._finish(callback, kind, value)
                    return 1
            return u32.CallNextHookEx(None, code, wparam, lparam)

        def ms_proc(code, wparam, lparam):
            if code == 0 and not self._done:
                info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                if not info.flags & 1:      # LLMHF_INJECTED
                    name = mouse_result(wparam, info.mouseData)
                    if name:
                        self._finish(callback, "name", name)
                        return 1
            return u32.CallNextHookEx(None, code, wparam, lparam)

        kb_cb, ms_cb = winput.HOOKPROC(kb_proc), winput.HOOKPROC(ms_proc)
        msg = wintypes.MSG()
        u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)     # cria a fila de mensagens da thread
        self._tid = k32.GetCurrentThreadId()
        timer = threading.Timer(timeout, self._finish, (callback, "cancel", "Tempo esgotado."))
        timer.daemon = True
        try:
            hooks.append(u32.SetWindowsHookExW(winput.WH_KEYBOARD_LL, kb_cb, None, 0))
            hooks.append(u32.SetWindowsHookExW(WH_MOUSE_LL, ms_cb, None, 0))
            ready.set()
            if not all(hooks):
                self._finish(callback, "cancel", "Não foi possível capturar a tecla.")
                return
            timer.start()
            while not self._done:
                if u32.GetMessageW(ctypes.byref(msg), None, 0, 0) <= 0:
                    break
                u32.TranslateMessage(ctypes.byref(msg))
                u32.DispatchMessageW(ctypes.byref(msg))
        finally:
            timer.cancel()
            for h in hooks:
                if h:
                    u32.UnhookWindowsHookEx(h)
            self._tid = 0
            self._done = True
            ready.set()


def evdev_result(etype, code, value, hires=False):
    """Evento evdev (tipo EV_KEY/EV_REL) -> ('name'|'cancel'|'error', valor) ou None (ignorar).
    So o 'para baixo' conta; roda: REL_WHEEL (ou HI_RES nos mouses que o tem, sem contar em dobro)."""
    import linput as li
    from keymap_linux import MOUSE_BUTTONS, code_to_vk
    if etype == li.EV_KEY:
        if value != 1:
            return None
        if code in MOUSE_BUTTONS:
            return "name", MOUSE_BUTTONS[code]
        vk = code_to_vk(code)
        return key_result(vk) if vk is not None else ("error", "Tecla não suportada (código evdev %s)." % code)
    if etype == li.EV_REL and value:
        if code == (li.REL_WHEEL_HI_RES if hires else li.REL_WHEEL):
            return "name", "wheel_up" if value > 0 else "wheel_down"
    return None


class LinuxCapture(Capture):
    """Mesma interface, lendo os eventos do evdev (sem grab: a tecla tambem chega ao desktop)."""

    def _quit(self):
        pass        # a thread confere _done a cada 50 ms

    def _run(self, callback, timeout, ready):
        import selectors
        import linput as li
        devs = []
        try:
            sc = li.Scanner()
            devs = sc.scan(set())
            ready.set()
            if not devs:
                self._finish(callback, "cancel", "Sem permissão para ler o teclado/mouse "
                             "(grupo input) — veja o Log após Iniciar." if sc.denied else
                             "Nenhum teclado ou mouse encontrado.")
                return
            sel = selectors.DefaultSelector()
            for d in devs:
                try:
                    os.set_blocking(d.dev.fd, False)
                except OSError:
                    pass
                sel.register(d.dev.fd, selectors.EVENT_READ, d)
            end = time.monotonic() + timeout
            while not self._done:
                if time.monotonic() >= end:
                    self._finish(callback, "cancel", "Tempo esgotado.")
                    break
                for key, _ in sel.select(0.05):
                    d = key.data
                    try:
                        events = list(d.dev.read())
                    except OSError:
                        continue
                    for ev in events:
                        res = evdev_result(ev.type, ev.code, ev.value, d.hires)
                        if res is None or self._done:
                            continue
                        if res[0] == "error":
                            callback(*res)
                        else:
                            self._finish(callback, *res)
            sel.close()
        finally:
            for d in devs:
                try:
                    d.dev.close()
                except OSError:
                    pass
            self._done = True
            ready.set()


if sys.platform.startswith("linux"):
    Capture = LinuxCapture
