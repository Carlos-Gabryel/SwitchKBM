"""Captura de teclado e mouse no Windows via ctypes.

Teclado: hook WH_KEYBOARD_LL (taxa baixa, callback minimo). Mouse: SOMENTE Raw Input
(movimento, botoes e roda) numa janela de captura em tela cheia; NAO ha hook LL de mouse
(com mouse de 1000+ Hz o Windows espera o Python a cada movimento e lagava o sistema todo).
Tudo roda na thread principal (GetMessageW). Os callbacks do usuario devem ser rapidos.
"""
import collections
import ctypes
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t

WH_KEYBOARD_LL = 13
WM_QUIT = 0x0012
WM_PAINT, WM_ERASEBKGND = 0x000F, 0x0014
WM_ACTIVATE, WM_KILLFOCUS = 0x0006, 0x0008
WM_INPUT = 0x00FF
WM_APP_KEY = 0x8001               # fila de teclas do hook -> thread principal
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
WA_INACTIVE = 0
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW = 0x8, 0x80
HWND_TOPMOST = -1
SWP_SHOWWINDOW = 0x40
SM_CXSCREEN, SM_CYSCREEN = 0, 1
DT_CENTER, DT_VCENTER, DT_SINGLELINE = 0x1, 0x4, 0x20
TRANSPARENT = 1
HIGH_PRIORITY_CLASS = 0x80
LLKHF_INJECTED = 0x10
RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
MOUSE_MOVE_ABSOLUTE = 0x01
CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT = 0, 1, 2
CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT = 5, 6

# RAWMOUSE.usButtonFlags (baixos 16 bits de ulButtons); usButtonData = altos 16 bits
RI_BTNS = ((0x1, "lmb", True), (0x2, "lmb", False), (0x4, "rmb", True), (0x8, "rmb", False),
           (0x10, "mmb", True), (0x20, "mmb", False), (0x40, "x1", True), (0x80, "x1", False),
           (0x100, "x2", True), (0x200, "x2", False))
RI_WHEEL = 0x400

HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)
CTRLHANDLER = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", RECT),
                ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL),
                ("rgbReserved", ctypes.c_byte * 32)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
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
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
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
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.SetActiveWindow.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.ClipCursor.argtypes = [ctypes.POINTER(RECT)]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.ShowCursor.argtypes = [wintypes.BOOL]
user32.ShowCursor.restype = ctypes.c_int
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = wintypes.HDC
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT), wintypes.BOOL]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(RECT), wintypes.HANDLE]
user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
                             ctypes.POINTER(RECT), wintypes.UINT]
gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
gdi32.CreateSolidBrush.restype = wintypes.HANDLE
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.SetConsoleCtrlHandler.argtypes = [CTRLHANDLER, wintypes.BOOL]
kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL


def _hiword_signed(v):
    v = (v >> 16) & 0xFFFF
    return v - 0x10000 if v >= 0x8000 else v


class InputHook:
    """Callbacks:
      on_key(vk, down) -> None; o bloqueio e decidido por is_captured() / always_block_vks.
      on_mouse_button(name, down), on_wheel(direction), on_move(dx, dy): vem do Raw Input,
      so quando capturado.
      on_capture_lost(): a janela de captura perdeu o foco (a captura ja foi encerrada aqui).
    Contadores para instrumentacao: mouse_ev (eventos WM_INPUT tratados) e kb_hook_max
    (maior tempo gasto no callback do hook de teclado, em s; o leitor zera).
    """

    def __init__(self, on_key, on_mouse_button, on_wheel, on_move, is_captured,
                 always_block_vks=(), log=print, on_capture_lost=None):
        self.on_key = on_key
        self.on_mouse_button = on_mouse_button
        self.on_wheel = on_wheel
        self.on_move = on_move
        self.is_captured = is_captured
        self.always_block_vks = set(always_block_vks)
        self.log = log
        self.on_capture_lost = on_capture_lost
        self._tid = 0
        self._hwnd = None
        self._hk = None
        self._brush = None
        self._capturing = False
        self._cursor_hidden = False
        self._keyq = collections.deque()
        self._passed = set()          # teclas cujo "down" passou (o "up" tambem deve passar)
        self.mouse_ev = 0
        self.kb_hook_max = 0.0
        self._ctrl_cb = None
        self.done = threading.Event()   # o chamador seta apos a limpeza (console fechando)
        # referencias para evitar coleta de lixo
        self._kb_cb = HOOKPROC(self._kb_proc)
        self._wnd_cb = WNDPROC(self._wnd_proc)

    # ---- hook de teclado (minimo: so registra e devolve) ----
    def _kb_proc(self, nCode, wParam, lParam):
        t0 = time.perf_counter()
        try:
            if nCode == 0:
                info = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if not (info.flags & LLKHF_INJECTED):
                    vk = info.vkCode
                    down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    self._keyq.append((vk, down))
                    if self._hwnd:
                        user32.PostMessageW(self._hwnd, WM_APP_KEY, 0, 0)
                    key = ("k", vk)
                    if down:
                        block = self.is_captured() or vk in self.always_block_vks
                        if not block:
                            self._passed.add(key)
                    elif key in self._passed:
                        self._passed.discard(key)
                        block = vk in self.always_block_vks
                    else:
                        block = self.is_captured() or vk in self.always_block_vks
                    dt = time.perf_counter() - t0
                    if dt > self.kb_hook_max:
                        self.kb_hook_max = dt
                    if block:
                        return 1
        except Exception:  # nunca deixar excecao escapar do hook
            pass
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _drain_keys(self):
        q = self._keyq
        while q:
            vk, down = q.popleft()
            try:
                self.on_key(vk, down)
            except Exception as e:
                self.log("erro no tratamento de tecla: %r" % (e,))

    # ---- janela de captura / raw input ----
    def _wnd_proc(self, hwnd, msg, wParam, lParam):
        try:
            if msg == WM_INPUT:
                self._read_raw(lParam)
            elif msg == WM_APP_KEY:
                self._drain_keys()
                return 0
            elif msg == WM_ERASEBKGND:
                return 1
            elif msg == WM_PAINT:
                self._paint(hwnd)
                return 0
            elif msg == WM_ACTIVATE or msg == WM_KILLFOCUS:
                if self._capturing and (msg == WM_KILLFOCUS or (wParam & 0xFFFF) == WA_INACTIVE):
                    self._focus_lost()
        except Exception as e:
            self.log("erro na janela de captura: %r" % (e,))
        return user32.DefWindowProcW(hwnd, msg, wParam, lParam)

    def _paint(self, hwnd):
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        rc = RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rc))
        user32.FillRect(hdc, ctypes.byref(rc), self._brush)
        gdi32.SetBkMode(hdc, TRANSPARENT)
        gdi32.SetTextColor(hdc, 0xC8C8C8)
        user32.DrawTextW(hdc, "CAPTURADO — F12 libera", -1, ctypes.byref(rc),
                         DT_CENTER | DT_VCENTER | DT_SINGLELINE)
        user32.EndPaint(hwnd, ctypes.byref(ps))

    def _focus_lost(self):
        self.end_capture()
        self.log("LIBERADO (janela perdeu o foco)")
        if self.on_capture_lost:
            self.on_capture_lost()

    def _read_raw(self, lParam):
        raw = RAWINPUT_MOUSE()
        size = wintypes.UINT(ctypes.sizeof(raw))
        r = user32.GetRawInputData(lParam, RID_INPUT, ctypes.byref(raw), ctypes.byref(size),
                                   ctypes.sizeof(RAWINPUTHEADER))
        if r == 0xFFFFFFFF or raw.header.dwType != RIM_TYPEMOUSE:
            return
        if not self.is_captured():
            return
        self.mouse_ev += 1
        m = raw.mouse
        bf = m.ulButtons & 0xFFFF
        if bf:
            for bit, name, down in RI_BTNS:
                if bf & bit:
                    self.on_mouse_button(name, down)
            if bf & RI_WHEEL:
                d = _hiword_signed(m.ulButtons)
                if d:
                    self.on_wheel(1 if d > 0 else -1)
        if m.usFlags & MOUSE_MOVE_ABSOLUTE:
            return
        if m.lLastX or m.lLastY:
            self.on_move(m.lLastX, m.lLastY)

    def _create_window(self):
        hinst = kernel32.GetModuleHandleW(None)
        self._brush = gdi32.CreateSolidBrush(0x181818)
        cls = WNDCLASSEXW()
        cls.cbSize = ctypes.sizeof(WNDCLASSEXW)
        cls.lpfnWndProc = self._wnd_cb
        cls.hInstance = hinst
        cls.lpszClassName = "KbmBridgeCaptureWnd"
        if not user32.RegisterClassExW(ctypes.byref(cls)):
            raise ctypes.WinError(ctypes.get_last_error())
        w = user32.GetSystemMetrics(SM_CXSCREEN)
        h = user32.GetSystemMetrics(SM_CYSCREEN)
        hwnd = user32.CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW, cls.lpszClassName,
                                      "kbm captura", WS_POPUP, 0, 0, w, h,
                                      None, None, hinst, None)
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self._hwnd = hwnd
        rid = RAWINPUTDEVICE(1, 2, RIDEV_INPUTSINK, hwnd)
        if not user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(rid)):
            raise ctypes.WinError(ctypes.get_last_error())

    def begin_capture(self):
        """Mostra a janela de captura, prende o cursor e o esconde. Thread principal."""
        if self._capturing or not self._hwnd:
            return
        hwnd = self._hwnd
        w = user32.GetSystemMetrics(SM_CXSCREEN)
        h = user32.GetSystemMetrics(SM_CYSCREEN)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, w, h, SWP_SHOWWINDOW)
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        # SetForegroundWindow pode ser negado; anexa a entrada da thread do foco atual
        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = False
        if fg_tid and fg_tid != self._tid:
            attached = bool(user32.AttachThreadInput(self._tid, fg_tid, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        if attached:
            user32.AttachThreadInput(self._tid, fg_tid, False)
        if user32.GetForegroundWindow() != hwnd:
            self.log("aviso: janela de captura nao obteve o foco")
        cx, cy = w // 2, h // 2
        rc = RECT(cx - 4, cy - 4, cx + 4, cy + 4)
        user32.ClipCursor(ctypes.byref(rc))
        user32.SetCursorPos(cx, cy)
        if not self._cursor_hidden:
            user32.ShowCursor(False)
            self._cursor_hidden = True
        user32.InvalidateRect(hwnd, None, True)
        self._capturing = True

    def end_capture(self):
        """Esconde a janela, libera o cursor e restaura. Idempotente."""
        was = self._capturing
        self._capturing = False
        user32.ClipCursor(None)
        if self._cursor_hidden:
            user32.ShowCursor(True)
            self._cursor_hidden = False
        if was and self._hwnd:
            user32.ShowWindow(self._hwnd, SW_HIDE)

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

    def _uninstall(self):
        self.end_capture()
        if self._hk:
            user32.UnhookWindowsHookEx(self._hk)
            self._hk = None
        if self._hwnd:
            user32.DestroyWindow(self._hwnd)
            self._hwnd = None
        if self._brush:
            gdi32.DeleteObject(self._brush)
            self._brush = None

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
