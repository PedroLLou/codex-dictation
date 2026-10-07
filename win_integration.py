"""Optional, fail-closed Windows desktop integration for Ditado Codex.

The module is importable on non-Windows systems. No global keyboard hooks,
clipboard access, startup registration, or eager optional GUI dependencies.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import queue
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Optional

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    from ctypes import wintypes
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # Explicit signatures matter on 64-bit Windows: HWND/HANDLE are pointer sized.
    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = wintypes.BOOL
    _user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    _user32.PeekMessageW.restype = wintypes.BOOL
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.TranslateMessage.restype = wintypes.BOOL
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.DispatchMessageW.restype = wintypes.LPARAM
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.c_void_p]
    _user32.GetGUIThreadInfo.restype = wintypes.BOOL
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
    _user32.SendInput.restype = wintypes.UINT
    _user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.FindWindowW.restype = wintypes.HWND
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.ShowWindow.restype = wintypes.BOOL
    _kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.CreateMutexW.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.GetLastError.argtypes = []
    _kernel32.GetLastError.restype = wintypes.DWORD
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL


class WindowsUnavailable(RuntimeError):
    pass


def _require_windows():
    if not IS_WINDOWS:
        raise WindowsUnavailable("This integration is available only on Windows")

def make_nonactivating(window, taskbar=False):
    """Paleta flutuante que não tira o foco do campo ao receber um clique."""
    _require_windows()
    hwnd = int(window.winfo_id())
    _user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetAncestor.restype = wintypes.HWND
    hwnd = _user32.GetAncestor(hwnd, 2) or hwnd
    _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    _user32.SetWindowLongW.restype = ctypes.c_long
    style = _user32.GetWindowLongW(hwnd, -20)
    style |= 0x08000000
    style = (style | 0x00040000) & ~0x00000080 if taskbar else (style | 0x00000080) & ~0x00040000
    _user32.SetWindowLongW(hwnd, -20, style)
    if taskbar:
        # Janela independente para o Explorer, mantendo a propriedade Tk em Python.
        setter = _user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else _user32.SetWindowLongW
        setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        setter.restype = ctypes.c_ssize_t
        setter(hwnd, -8, 0)  # GWLP_HWNDPARENT: remover owner oculto
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _user32.SetWindowPos.restype = wintypes.BOOL
    if not _user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0020):
        raise ctypes.WinError(ctypes.get_last_error())
    if not _user32.GetWindowLongW(hwnd, -20) & 0x08000000:
        raise RuntimeError('Não foi possível manter o foco no campo original.')


class InstanceGuard:
    """Per-user named mutex; duplicate launch focuses the app's registered title."""
    ERROR_ALREADY_EXISTS = 183

    def __init__(self, app_title: str, mutex_name: Optional[str] = None):
        self.app_title = app_title
        suffix = hashlib.sha256(app_title.encode("utf-8")).hexdigest()[:24]
        self.mutex_name = mutex_name or "Local\\DitadoCodex-" + suffix
        self.handle = None
        self.is_primary = False

    def acquire(self) -> bool:
        _require_windows()
        self.handle = _kernel32.CreateMutexW(None, False, self.mutex_name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.is_primary = _kernel32.GetLastError() != self.ERROR_ALREADY_EXISTS
        if not self.is_primary:
            hwnd = _user32.FindWindowW(None, self.app_title)
            if hwnd:
                _user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                _user32.SetForegroundWindow(hwnd)
            self.release()
        return self.is_primary

    def release(self):
        if self.handle and IS_WINDOWS:
            _kernel32.CloseHandle(self.handle)
        self.handle = None
        self.is_primary = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.release()


_MODIFIERS = {"CTRL": 0x0002, "CONTROL": 0x0002, "ALT": 0x0001,
              "SHIFT": 0x0004, "WIN": 0x0008, "WINDOWS": 0x0008}
_VK = {"SPACE": 0x20, "ESC": 0x1B, "ESCAPE": 0x1B, "ENTER": 0x0D,
       "RETURN": 0x0D, "TAB": 0x09, "DELETE": 0x2E, "INSERT": 0x2D,
       "HOME": 0x24, "END": 0x23, "UP": 0x26, "DOWN": 0x28,
       "LEFT": 0x25, "RIGHT": 0x27, "BACKSPACE": 0x08}


def parse_binding(binding: str):
    """Return RegisterHotKey (modifier mask, virtual key) for e.g. Ctrl+Alt+Space."""
    bits = [part.strip().upper() for part in binding.split("+") if part.strip()]
    if not bits:
        raise ValueError("Hotkey binding is empty")
    mods = 0
    for part in bits[:-1]:
        if part not in _MODIFIERS:
            raise ValueError("Unknown hotkey modifier: " + part)
        if mods & _MODIFIERS[part]:
            raise ValueError("Duplicate hotkey modifier: " + part)
        mods |= _MODIFIERS[part]
    key = bits[-1]
    if key in _MODIFIERS:
        raise ValueError("Hotkey needs a non-modifier key")
    if key in _VK:
        vk = _VK[key]
    elif len(key) == 1 and key.isalpha():
        vk = ord(key)
    elif len(key) == 1 and key.isdigit():
        vk = ord(key)
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError("Unknown hotkey key: " + key)
    return mods, vk


class Hotkeys:
    """Dedicated message thread. Callback receives action strings on that thread.

    Actions: ``toggle`` for toggle mode, ``start``/``stop`` for hold mode,
    and ``cancel`` when Esc is pressed while active. Tk consumers should queue
    these events and process them on the Tk main thread.
    """
    HOTKEY_ID, ESC_ID = 1, 2
    WM_HOTKEY = 0x0312
    MOD_NOREPEAT = 0x4000

    def __init__(self, callback: Callable[[str], None], binding="Ctrl+Alt+Space", mode="toggle"):
        if mode not in ("toggle", "hold"):
            raise ValueError("mode must be 'toggle' or 'hold'")
        self.callback, self.binding, self.mode = callback, binding, mode
        self._thread = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._active = False
        self._registered = False
        self._esc_registered = False
        self._error = None
        self._commands = queue.Queue()

    def start(self):
        _require_windows()
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="DitadoHotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(5)
        if self._error:
            raise self._error
        if not self._registered:
            raise RuntimeError("Could not register global hotkey")
        return self

    def _run(self):
        mods, vk = parse_binding(self.binding)
        if not _user32.RegisterHotKey(None, self.HOTKEY_ID, mods | self.MOD_NOREPEAT, vk):
            self._error = ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
            return
        self._registered = True
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while not self._stop.is_set():
                self._apply_commands()
                while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    if msg.message == self.WM_HOTKEY:
                        if msg.wParam == self.HOTKEY_ID:
                            if self.mode == "toggle":
                                self.callback("toggle")
                            else:
                                self.callback("start")
                                while not self._stop.is_set() and _user32.GetAsyncKeyState(vk) & 0x8000:
                                    self._apply_commands()
                                    self._dispatch_pending(msg)
                                    time.sleep(0.01)
                                if not self._stop.is_set():
                                    self.callback("stop")
                        elif msg.wParam == self.ESC_ID:
                            self.callback("cancel")
                    else:
                        _user32.TranslateMessage(ctypes.byref(msg))
                        _user32.DispatchMessageW(ctypes.byref(msg))
                time.sleep(0.01)
        finally:
            if self._registered:
                _user32.UnregisterHotKey(None, self.HOTKEY_ID)
                if self._esc_registered:
                    _user32.UnregisterHotKey(None, self.ESC_ID)
                    self._esc_registered = False
            self._registered = False

    def set_active(self, active: bool):
        """Register Esc only during recording/finalizing; safe to call repeatedly."""
        self._active = bool(active)
        if IS_WINDOWS and self._registered:
            self._commands.put(bool(active))

    def _apply_commands(self):
        while True:
            try:
                active = self._commands.get_nowait()
            except queue.Empty:
                return
            if active:
                if not self._esc_registered and not _user32.RegisterHotKey(None, self.ESC_ID, self.MOD_NOREPEAT, 0x1B):
                    self._error = ctypes.WinError(ctypes.get_last_error())
                else:
                    self._esc_registered = True
            else:
                if self._esc_registered:
                    _user32.UnregisterHotKey(None, self.ESC_ID)
                    self._esc_registered = False

    def _dispatch_pending(self, msg):
        while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            if msg.message == self.WM_HOTKEY and msg.wParam == self.ESC_ID:
                self.callback("cancel")

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._registered and IS_WINDOWS:
            _user32.UnregisterHotKey(None, self.HOTKEY_ID)
            if self._esc_registered:
                _user32.UnregisterHotKey(None, self.ESC_ID)
        self._registered = False


@dataclass(frozen=True)
class CaptureTarget:
    hwnd: int
    pid: int
    child_hwnd: int
    child_pid: int
    known: bool = True
    # Defaults preserve construction by existing callers and platform mocks.
    uia_runtime_id: tuple[int, ...] = ()
    uia_pid: int = 0
    uia_control_type: int = 0
    uia_is_password: Optional[bool] = None
    uia_enabled: Optional[bool] = None
    uia_has_keyboard_focus: Optional[bool] = None
    focus_kind: str = "unknown"


@contextmanager
def _com_apartment():
    """Initialize COM for this callback thread; balance only successful init."""
    import comtypes
    comtypes.CoInitialize()
    try:
        yield
    finally:
        comtypes.CoUninitialize()


def _focused_uia_identity():
    """Read identity/safety flags only; deliberately never read Name or Value."""
    with _com_apartment():
        import comtypes.client
        # Cada thread cria seu próprio cliente COM: não compartilha ponteiros
        # de automação entre a thread do atalho e a thread da interface.
        module = comtypes.client.GetModule('UIAutomationCore.dll')
        client = comtypes.client.CreateObject('{ff48dba4-60ef-4201-aa87-54103eef594e}', interface=module.IUIAutomation)
        element = None
        try:
            element = client.GetFocusedElement()
            if element is None: return None
            return (tuple(int(x) for x in element.GetRuntimeId()), int(element.CurrentProcessId),
                    int(element.CurrentControlType), bool(element.CurrentIsPassword), bool(element.CurrentIsEnabled),
                    bool(element.CurrentHasKeyboardFocus), int(element.CurrentNativeWindowHandle or 0))
        finally:
            # Release deve ocorrer antes de CoUninitialize, na mesma thread.
            element = None
            client = None


class _GUITHREADINFO(ctypes.Structure):
    # Layout used by GetGUIThreadInfo on both 32/64-bit Windows.
    _fields_ = [("cbSize", ctypes.c_ulong), ("flags", ctypes.c_ulong),
                ("hwndActive", ctypes.c_void_p), ("hwndFocus", ctypes.c_void_p),
                ("hwndCapture", ctypes.c_void_p), ("hwndMenuOwner", ctypes.c_void_p),
                ("hwndMoveSize", ctypes.c_void_p), ("hwndCaret", ctypes.c_void_p),
                ("rcCaret", ctypes.c_long * 4)]


def _window_pid(hwnd):
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def capture_target() -> CaptureTarget:
    """Snapshot foreground and focused child; unknown focus is never pasteable."""
    _require_windows()
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return CaptureTarget(0, 0, 0, 0, False)
    tid = _user32.GetWindowThreadProcessId(hwnd, None)
    info = _GUITHREADINFO()
    info.cbSize = ctypes.sizeof(info)
    if not tid or not _user32.GetGUIThreadInfo(tid, ctypes.byref(info)) or not info.hwndFocus:
        return CaptureTarget(int(hwnd), _window_pid(hwnd), 0, 0, False)
    child = int(info.hwndFocus)
    root_pid, child_pid = _window_pid(hwnd), _window_pid(child)
    try:
        identity = _focused_uia_identity()
    except Exception:
        identity = None
    if identity:
        rid, pid, ctype, password, enabled, focused, native_hwnd = identity
        valid = bool(rid and pid == child_pid and ctype == 50004 and not password and enabled and focused)
        if valid:
            return CaptureTarget(int(hwnd), root_pid, child, child_pid, True,
                                 rid, pid, ctype, password, enabled, focused, "uia")
    # The only UIA-free allowance is a classic, same-process native Edit.
    cls = _class_name(child).lower()
    if child_pid == root_pid and cls == "edit":
        style = int(_user32.GetWindowLongW(child, -16)) & 0xFFFFFFFF
        if not style & 0x20:
            return CaptureTarget(int(hwnd), root_pid, child, child_pid, True,
                                 focus_kind="native_edit")
    return CaptureTarget(int(hwnd), root_pid, child, child_pid, False)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("padding", ctypes.c_byte * 32)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTUNION)]


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    if not _user32.GetClassNameW(hwnd, buf, len(buf)):
        return ""
    return buf.value


def foreground_is_t3():
    """Match the foreground executable, never a page/window title."""
    if not IS_WINDOWS: return False
    hwnd = _user32.GetForegroundWindow()
    if not hwnd: return False
    return _process_name(_window_pid(hwnd)) in {
        't3 code.exe', 't3 code (nightly).exe', 't3code.exe',
    }


def _process_name(pid):
    handle = _kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return os.path.basename(buf.value).lower()
    finally:
        _kernel32.CloseHandle(handle)


def _uia_target_matches(target):
    try:
        identity = _focused_uia_identity()
    except Exception:
        identity = None
    expected = (tuple(getattr(target, "uia_runtime_id", ())), int(getattr(target, "uia_pid", 0)),
                int(getattr(target, "uia_control_type", 0)), getattr(target, "uia_is_password", None),
                getattr(target, "uia_enabled", None), getattr(target, "uia_has_keyboard_focus", None))
    return bool(identity and identity[:6] == expected and identity[1] == int(target.child_pid)
                and identity[2] == 50004 and identity[3] is False
                and identity[4] is True and identity[5] is True)


def _safe_target(target):
    if not target or not getattr(target, "known", False) or not target.hwnd or not target.child_hwnd:
        return False, "Captured focus is unknown"
    if int(_user32.GetForegroundWindow() or 0) != int(target.hwnd):
        return False, "Original window is no longer foreground"
    tid = _user32.GetWindowThreadProcessId(target.hwnd, None)
    info = _GUITHREADINFO()
    info.cbSize = ctypes.sizeof(info)
    if not tid or not _user32.GetGUIThreadInfo(tid, ctypes.byref(info)) or not info.hwndFocus:
        return False, "Current focus could not be verified"
    if int(info.hwndFocus) != int(target.child_hwnd):
        return False, "Original focused control is no longer focused"
    if _window_pid(target.hwnd) != int(target.pid) or _window_pid(target.child_hwnd) != int(target.child_pid):
        return False, "Original window or control process changed"
    cls = _class_name(target.child_hwnd).lower()
    root_cls = _class_name(target.hwnd).lower()
    if cls in {"consolewindowclass", "cascadia_hosting_window_class", "credential dialog xaml host"} or root_cls in {"consolewindowclass", "cascadia_hosting_window_class"}:
        return False, "Terminal or protected target is not supported"
    if _process_name(int(getattr(target, "pid", 0))) in {
        "cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "wt.exe",
        "bash.exe", "wsl.exe", "ubuntu.exe", "alacritty.exe", "wezterm-gui.exe",
        "mintty.exe", "conhost.exe", "conemu64.exe", "cmder.exe",
    }:
        return False, "Terminal or protected target is not supported"
    # Standard edit controls with ES_PASSWORD must never receive automatic text.
    style = int(_user32.GetWindowLongW(target.child_hwnd, -16)) & 0xFFFFFFFF
    if cls in {"edit", "richedit", "richedit20w", "richedit50w"} and style & 0x20:
        return False, "Password fields are not supported"
    if getattr(target, "focus_kind", "unknown") == "uia":
        if not _uia_target_matches(target):
            return False, "Focused UI Automation element changed or could not be verified"
    elif getattr(target, "focus_kind", "unknown") != "native_edit" or cls != "edit" or int(target.child_pid) != int(target.pid):
        return False, "Focused control is not a verified editable field"
    return True, ""


def paste_text(target, text: str) -> tuple[bool, str]:
    """Type Unicode into the captured focus using SendInput; never touches clipboard."""
    if not IS_WINDOWS:
        return False, "Text insertion is available only on Windows"
    if not isinstance(text, str) or not text:
        return False, "There is no text to insert"
    if any(ch in text for ch in "\r\n\0") or any(ord(ch) < 32 and ch != "\t" for ch in text):
        return False, "Text contains a newline or unsafe control character"
    ok, reason = _safe_target(target)
    if not ok:
        return False, reason
    # Send UTF-16 code units, including both halves of supplementary characters.
    units = text.encode("utf-16-le", errors="strict")
    inputs = (_INPUT * (len(units) // 2 * 2))()
    idx = 0
    for offset in range(0, len(units), 2):
        code = units[offset] | units[offset + 1] << 8
        inputs[idx] = _INPUT(type=1, ki=_KEYBDINPUT(0, code, 0x0004, 0, 0)); idx += 1
        inputs[idx] = _INPUT(type=1, ki=_KEYBDINPUT(0, code, 0x0004 | 0x0002, 0, 0)); idx += 1
    # Recheck immediately before the irreversible input operation.
    ok, reason = _safe_target(target)
    if not ok:
        return False, reason
    sent = _user32.SendInput(len(inputs), ctypes.byref(inputs), ctypes.sizeof(_INPUT))
    if sent != len(inputs):
        return False, "Windows accepted only part of the Unicode input"
    return True, "Text inserted"


class Tray:
    """Optional pystray tray icon. Callbacks are delegated to the caller."""
    def __init__(self, callback: Callable[[str], None], language='pt-BR'):
        self.callback = callback
        self.language = language
        self._icon = None
        self._thread = None
        self._state = (False, False)

    def start(self):
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError:
            return False
        from app_identity import app_image
        image = app_image(64)
        from i18n import tr
        menu = pystray.Menu(
            pystray.MenuItem(tr("Mostrar",self.language), lambda *_: self.callback("show")),
            pystray.MenuItem(tr("Iniciar/Parar",self.language), lambda *_: self.callback("toggle")),
            pystray.MenuItem(tr("Cancelar",self.language), lambda *_: self.callback("cancel")),
            pystray.MenuItem(tr("Sair",self.language), lambda *_: self.callback("exit")),
        )
        self._icon = pystray.Icon("Ditado Codex", image, "Ditado Codex", menu)
        self._thread = threading.Thread(target=self._icon.run, name="DitadoTray", daemon=True)
        self._thread.start()
        return True

    def update(self, recording=False, busy=False):
        self._state = (bool(recording), bool(busy))
        if self._icon:
            state = "Gravando" if recording else "Processando" if busy else "Pronto"
            from i18n import tr
            self._icon.title = "Ditado Codex — " + tr(state,self.language)

    def notify(self, message: str, title="Ditado Codex"):
        if self._icon:
            try:
                self._icon.notify(message, title)
            except Exception:
                pass

    def close(self):
        if self._icon:
            self._icon.stop()
            self._icon = None
