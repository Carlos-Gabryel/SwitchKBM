"""Captura de teclado e mouse no Windows via ctypes (hooks LL + Raw Input).

Tudo roda na thread principal (GetMessageW). Os callbacks do usuario devem ser rapidos.
"""
import ctypes
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_QUIT = 0x0012
WM_INPUT = 0x00FF
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
WM_MOUSEMOVE = 0x200
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x201, 0x202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x204, 0x205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x207, 0x208
WM_MOUSEWHEEL = 0x20A
WM_XBUTTONDOWN, WM_XBUTTONUP = 0x20B, 0x20C
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x01
RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
MOUSE_MOVE_ABSOLUTE = 0x01
CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT = 0, 1, 2
CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT = 5, 6
HWND_MESSAGE = -3

HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)
CTRLHANDLER = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", POINT), ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HANDLE), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HANDLE), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HANDLE)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE), ("wParam", WPARAM)]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [("usFlags", wintypes.USHORT), ("ulButtons", ctypes.c_uint32),
                ("ulRawButtons", ctypes.c_uint32), ("lLastX", ctypes.c_long),
                ("lLastY", ctypes.c_long), ("ulExtraInformation", ctypes.c_uint32)]


class RAWINPUT_MOUSE(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, WPARAM, LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, WPARAM, LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
user32.RegisterRawInputDevices.restype = wintypes.BOOL
user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID,
                                   ctypes.POINTER(wintypes.UINT), wintypes.UINT]
user32.GetRawInputData.restype = wintypes.UINT
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.SetConsoleCtrlHandler.argtypes = [CTRLHANDLER, wintypes.BOOL]
kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL

_BTN_MSGS = {
    WM_LBUTTONDOWN: ("lmb", True), WM_LBUTTONUP: ("lmb", False),
    WM_RBUTTONDOWN: ("rmb", True), WM_RBUTTONUP: ("rmb", False),
    WM_MBUTTONDOWN: ("mmb", True), WM_MBUTTONUP: ("mmb", False),
}


def _hiword_signed(v):
    v = (v >> 16) & 0xFFFF
    return v - 0x10000 if v >= 0x8000 else v


class InputHook:
    """Callbacks:
      on_key(vk, down) -> None; o bloqueio e decidido por is_captured() / always_block_vks.
      on_mouse_button(name, down), on_wheel(direction), on_move(dx, dy).
    """

    def __init__(self, on_key, on_mouse_button, on_wheel, on_move, is_captured,
                 always_block_vks=(), log=print):
        self.on_key = on_key
        self.on_mouse_button = on_mouse_button
        self.on_wheel = on_wheel
        self.on_move = on_move
        self.is_captured = is_captured
        self.always_block_vks = set(always_block_vks)
        self.log = log
        self._tid = 0
        self._hwnd = None
        self._hk = None
        self._hm = None
        self._passed = set()          # teclas/botoes cujo "down" passou (o "up" tambem deve passar)
        self._last_raw = time.perf_counter()
        self._hook_moves_no_raw = 0
        self._fallback = False
        self._ctrl_cb = None
        self.done = threading.Event()   # o chamador seta apos a limpeza (console fechando)
        # referencias para evitar coleta de lixo
        self._kb_cb = HOOKPROC(self._kb_proc)
        self._ms_cb = HOOKPROC(self._ms_proc)
        self._wnd_cb = WNDPROC(self._wnd_proc)

    # ---- hooks ----
    def _kb_proc(self, nCode, wParam, lParam):
        try:
            if nCode == 0:
                info = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if not (info.flags & LLKHF_INJECTED):
                    vk = info.vkCode
                    down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    self.on_key(vk, down)
                    key = ("k", vk)
                    if down:
                        block = self.is_captured() or vk in self.always_block_vks
                        if not block:
                            self._passed.add(key)
                    else:
                        if key in self._passed:
                            self._passed.discard(key)
                            block = vk in self.always_block_vks
                        else:
                            block = self.is_captured() or vk in self.always_block_vks
                    if block:
                        return 1
        except Exception as e:  # nunca deixar excecao escapar do hook
            self.log("erro no hook de teclado: %r" % (e,))
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _ms_proc(self, nCode, wParam, lParam):
        try:
            if nCode == 0:
                info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                if not (info.flags & LLMHF_INJECTED):
                    if self._handle_mouse(wParam, info):
                        return 1
        except Exception as e:
            self.log("erro no hook de mouse: %r" % (e,))
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _handle_mouse(self, msg, info):
        captured = self.is_captured()
        if msg == WM_MOUSEMOVE:
            if captured:
                now = time.perf_counter()
                if now - self._last_raw > 1.0:
                    self._hook_moves_no_raw += 1
                    if self._hook_moves_no_raw >= 5:
                        cur = POINT()
                        user32.GetCursorPos(ctypes.byref(cur))
                        if not self._fallback:
                            self._fallback = True
                            self.log("Raw Input sem movimento: usando fallback pelo hook LL")
                        self.on_move(info.pt.x - cur.x, info.pt.y - cur.y)
            return captured
        if msg == WM_MOUSEWHEEL:
            d = _hiword_signed(info.mouseData)
            self.on_wheel(1 if d > 0 else -1)
            return captured
        name = None
        down = False
        if msg in _BTN_MSGS:
            name, down = _BTN_MSGS[msg]
        elif msg in (WM_XBUTTONDOWN, WM_XBUTTONUP):
            xb = (info.mouseData >> 16) & 0xFFFF
            name = "x1" if xb == 1 else "x2"
            down = msg == WM_XBUTTONDOWN
        if name is None:
            return False
        self.on_mouse_button(name, down)
        key = ("m", name)
        if down:
            if not captured:
                self._passed.add(key)
            return captured
        if key in self._passed:
            self._passed.discard(key)
            return False
        return captured

    # ---- janela de mensagens / raw input ----
    def _wnd_proc(self, hwnd, msg, wParam, lParam):
        if msg == WM_INPUT:
            try:
                self._read_raw(lParam)
            except Exception as e:
                self.log("erro no raw input: %r" % (e,))
        return user32.DefWindowProcW(hwnd, msg, wParam, lParam)

    def _read_raw(self, lParam):
        raw = RAWINPUT_MOUSE()
        size = wintypes.UINT(ctypes.sizeof(raw))
        r = user32.GetRawInputData(lParam, RID_INPUT, ctypes.byref(raw), ctypes.byref(size),
                                   ctypes.sizeof(RAWINPUTHEADER))
        if r == 0xFFFFFFFF or raw.header.dwType != RIM_TYPEMOUSE:
            return
        m = raw.mouse
        if m.usFlags & MOUSE_MOVE_ABSOLUTE:
            return
        if m.lLastX or m.lLastY:
            self._last_raw = time.perf_counter()
            self._hook_moves_no_raw = 0
            if self._fallback:
                self._fallback = False
                self.log("Raw Input voltou; fallback desativado")
            self.on_move(m.lLastX, m.lLastY)

    def _create_window(self):
        hinst = kernel32.GetModuleHandleW(None)
        cls = WNDCLASSEXW()
        cls.cbSize = ctypes.sizeof(WNDCLASSEXW)
        cls.lpfnWndProc = self._wnd_cb
        cls.hInstance = hinst
        cls.lpszClassName = "KbmBridgeMsgWnd"
        if not user32.RegisterClassExW(ctypes.byref(cls)):
            raise ctypes.WinError(ctypes.get_last_error())
        hwnd = user32.CreateWindowExW(0, cls.lpszClassName, "kbm", 0, 0, 0, 0, 0,
                                      HWND_MESSAGE, None, hinst, None)
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self._hwnd = hwnd
        rid = RAWINPUTDEVICE(1, 2, RIDEV_INPUTSINK, hwnd)
        if not user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(rid)):
            raise ctypes.WinError(ctypes.get_last_error())

    # ---- controle ----
    def quit(self):
        """Pode ser chamado de qualquer thread."""
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)

    def _install(self):
        self._tid = kernel32.GetCurrentThreadId()
        self._create_window()
        self._hk = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_cb, None, 0)
        if not self._hk:
            raise ctypes.WinError(ctypes.get_last_error())
        self._hm = user32.SetWindowsHookExW(WH_MOUSE_LL, self._ms_cb, None, 0)
        if not self._hm:
            raise ctypes.WinError(ctypes.get_last_error())

    def _uninstall(self):
        if self._hk:
            user32.UnhookWindowsHookEx(self._hk)
            self._hk = None
        if self._hm:
            user32.UnhookWindowsHookEx(self._hm)
            self._hm = None
        if self._hwnd:
            user32.DestroyWindow(self._hwnd)
            self._hwnd = None

    def run(self):
        """Instala tudo e roda o loop de mensagens ate WM_QUIT / Ctrl+C / fechar console."""
        def handler(ev):
            if ev in (CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT,
                      CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT):
                self.quit()
                if ev != CTRL_C_EVENT and ev != CTRL_BREAK_EVENT:
                    self.done.wait(3.0)   # da tempo da limpeza antes do SO matar o processo
                return True
            return False
        self._ctrl_cb = CTRLHANDLER(handler)
        kernel32.SetConsoleCtrlHandler(self._ctrl_cb, True)
        try:
            self._install()
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._uninstall()
            kernel32.SetConsoleCtrlHandler(self._ctrl_cb, False)
