"""Captura de uma tecla/botao do mouse sem Tk: hooks de baixo nivel temporarios (so enquanto uma
celula espera). O primeiro evento 'para baixo' depois do inicio vale e e engolido."""
import ctypes
import threading
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
