"""Icona nella system tray di Windows (senza dipendenze esterne).

Menu: Mostra, Avvia/Ferma monitoraggio, Scarica motore, Apri cartelle, Esci.
Le azioni passano dalle API locali con il token di sessione, quindi rispettano
gli stessi permessi e la stessa logica della GUI.
"""

from __future__ import annotations

import ctypes
import json
import os
import threading
import urllib.error
import urllib.request
import webbrowser
from ctypes import wintypes
from typing import Any, Callable, Dict, Optional

from . import __version__

IS_WINDOWS = os.name == "nt"

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_APP = 0x8000
WM_CONTEXTMENU = 0x007B
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_NULL = 0
WM_QUIT = 0x0012

NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010

IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_GRAYED = 0x00000001
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
TPM_NONOTIFY = 0x0080

NIIF_INFO = 0x00000001
NIIF_WARNING = 0x00000002
NIIF_ERROR = 0x00000003

ID_SHOW = 1001
ID_START_MONITOR = 1002
ID_STOP_MONITOR = 1003
ID_UNLOAD = 1004
ID_OPEN_MODELS = 1005
ID_OPEN_LOGS = 1006
ID_STOP_MONITOR_ENGINE = 1008
ID_QUIT = 1007

LABELS = {
    "it": {
        "show": "Mostra RVC Portable",
        "start_monitor": "Avvia monitoraggio",
        "stop_monitor": "Ferma monitoraggio",
        "stop_monitor_engine": "Ferma monitoraggio e motore",
        "unload": "Scarica motore",
        "open_models": "Apri cartella Modelli",
        "open_logs": "Apri cartella log",
        "quit": "Esci (chiudi applicazione)",
        "tip": "RVC Portable — monitor: %s · motore: %s",
        "monitor_started": "Monitoraggio avviato.",
        "on": "attivo",
        "off": "fermo",
        "ready": "pronto",
        "not_ready": "non pronto",
        "monitor_error": "Impossibile avviare il monitoraggio: configura la cartella input.",
        "error": "RVC Portable",
    },
    "en": {
        "show": "Show RVC Portable",
        "start_monitor": "Start monitoring",
        "stop_monitor": "Stop monitoring",
        "stop_monitor_engine": "Stop monitoring and engine",
        "unload": "Unload engine",
        "open_models": "Open Modelli folder",
        "open_logs": "Open logs folder",
        "quit": "Quit application",
        "tip": "RVC Portable — monitor: %s · engine: %s",
        "monitor_started": "Monitoring started.",
        "on": "active",
        "off": "idle",
        "ready": "ready",
        "not_ready": "not ready",
        "monitor_error": "Could not start monitoring: set the input folder first.",
        "error": "RVC Portable",
    },
}


def _make_int_resource(value: int):
    return ctypes.cast(ctypes.c_void_p(value), ctypes.c_wchar_p)


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HANDLE),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", _GUID),
        ("hBalloonIcon", wintypes.HANDLE),
    ]


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class TrayIcon:
    """Tray Windows minimale; su altri sistemi ``start`` restituisce False."""

    def __init__(
        self,
        *,
        url: str,
        port: int,
        token: str,
        app_root: str,
        models_dir: str,
        logs_dir: str,
        language: str = "it",
        show_callback: Optional[Callable[[], Any]] = None,
        on_stop: Optional[Callable[[], None]] = None,
    ) -> None:
        self.url = url
        self.port = port
        self.token = token
        self.app_root = app_root
        self.models_dir = models_dir
        self.logs_dir = logs_dir
        self.language = "en" if str(language).lower().startswith("en") else "it"
        self._labels: Dict[str, str] = LABELS[self.language]
        self._show_callback = show_callback
        self._on_stop = on_stop
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stop_event = threading.Event()
        self._hwnd: Optional[int] = None
        self._hicon: Optional[int] = None
        self._nid: Optional[_NOTIFYICONDATAW] = None
        self._class_atom = None
        self._class_name = "RVCPortableTray_%d" % os.getpid()
        self._busy_lock = threading.Lock()
        self._monitor_running = False
        self._engine_ready = False
        self._last_tip = ""
        self._wndproc = None

    # ------------------------------------------------------------------ public
    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> bool:
        if not IS_WINDOWS:
            return False
        if self.running:
            return True
        self._ready.clear()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="rvc-tray", daemon=True)
        self._thread.start()
        return self._ready.wait(timeout=5.0)

    def stop(self) -> None:
        self._stop_event.set()
        if IS_WINDOWS and self._hwnd:
            try:
                user32 = ctypes.windll.user32
                user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

    # -------------------------------------------------------------------- HTTP
    def _request(self, method: str, path: str) -> Dict[str, Any]:
        body = b"{}" if method == "POST" else None
        request = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path),
            data=body,
            headers={
                "Authorization": "Bearer %s" % self.token,
                "Content-Type": "application/json",
            },
            method=method,
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return {}

    def _post(self, path: str) -> Dict[str, Any]:
        return self._request("POST", path)

    def _get(self, path: str) -> Dict[str, Any]:
        return self._request("GET", path)

    # ----------------------------------------------------------------- actions
    def _show(self) -> None:
        try:
            if self._show_callback is not None:
                self._show_callback()
            else:
                webbrowser.open(self.url)
        except Exception:
            webbrowser.open(self.url)

    def _start_monitor(self) -> None:
        try:
            self._post("/api/monitor/start")
            self._notify(self._labels["show"], self._labels.get("monitor_started", "Monitoraggio avviato."))
        except urllib.error.HTTPError as exc:
            if exc.code == 422:
                self._notify(self._labels["error"], self._labels["monitor_error"], NIIF_WARNING)
            else:
                self._notify(self._labels["error"], "HTTP %s" % exc.code, NIIF_ERROR)
        except Exception as exc:
            self._notify(self._labels["error"], str(exc)[:180], NIIF_ERROR)

    def _stop_monitor(self) -> None:
        try:
            self._post("/api/monitor/stop")
        except Exception as exc:
            self._notify(self._labels["error"], str(exc)[:180], NIIF_ERROR)

    def _stop_monitor_engine(self) -> None:
        self._stop_monitor()
        self._unload()

    def _unload(self) -> None:
        try:
            self._post("/api/system/engine/unload")
        except Exception as exc:
            self._notify(self._labels["error"], str(exc)[:180], NIIF_ERROR)

    def _open_folder(self, path: str) -> None:
        try:
            if path and os.path.isdir(path):
                os.startfile(path)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _quit(self) -> None:
        try:
            self._post("/api/system/shutdown")
        except Exception:
            pass
        self.stop()
        if self._on_stop is not None:
            try:
                self._on_stop()
            except Exception:
                pass

    def _run_command(self, command: int) -> None:
        with self._busy_lock:
            if command == ID_SHOW:
                self._show()
            elif command == ID_START_MONITOR:
                self._start_monitor()
            elif command == ID_STOP_MONITOR:
                self._stop_monitor()
            elif command == ID_STOP_MONITOR_ENGINE:
                self._stop_monitor_engine()
            elif command == ID_UNLOAD:
                self._unload()
            elif command == ID_OPEN_MODELS:
                self._open_folder(self.models_dir)
            elif command == ID_OPEN_LOGS:
                self._open_folder(self.logs_dir)
            elif command == ID_QUIT:
                self._quit()

    # ------------------------------------------------------------------- tray
    def _run(self) -> None:
        try:
            user32 = ctypes.windll.user32
            shell32 = ctypes.windll.shell32
            kernel32 = ctypes.windll.kernel32
            shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(_NOTIFYICONDATAW)]
            shell32.Shell_NotifyIconW.restype = wintypes.BOOL
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HANDLE, wintypes.HINSTANCE, ctypes.c_void_p,
            ]
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
            user32.RegisterClassW.restype = wintypes.ATOM
            user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
            user32.LoadIconW.restype = wintypes.HANDLE
            user32.CreatePopupMenu.argtypes = []
            user32.AppendMenuW.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
            user32.AppendMenuW.restype = wintypes.BOOL
            user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.DestroyWindow.argtypes = [wintypes.HWND]
            user32.DestroyMenu.argtypes = [wintypes.HANDLE]
            user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
            user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.DispatchMessageW.restype = ctypes.c_ssize_t
            user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.DefWindowProcW.restype = ctypes.c_ssize_t
            user32.CreatePopupMenu.restype = wintypes.HMENU
            user32.TrackPopupMenu.argtypes = [
                wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, ctypes.c_void_p,
            ]
            user32.TrackPopupMenu.restype = wintypes.UINT
            user32.LoadImageW.argtypes = [
                wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int,
                ctypes.c_int, wintypes.UINT,
            ]
            user32.LoadImageW.restype = wintypes.HANDLE

            hinst = kernel32.GetModuleHandleW(None)
            wndproc_type = _WNDCLASSW._fields_[1][1]
            self._wndproc = wndproc_type(self._window_proc)
            wc = _WNDCLASSW()
            wc.style = 0
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = hinst
            wc.lpszClassName = self._class_name
            self._class_atom = user32.RegisterClassW(ctypes.byref(wc))
            if not self._class_atom:
                # Classe gia' registrata (riavvio nello stesso processo).
                pass
            self._hwnd = user32.CreateWindowExW(
                0, self._class_name, "RVC Portable", 0, 0, 0, 0, 0, None, None, hinst, None
            )
            if not self._hwnd:
                self._ready.set()
                return

            icon_path = os.path.join(self.app_root, "web", "assets", "icon.ico")
            hicon = None
            if os.path.isfile(icon_path):
                hicon = user32.LoadImageW(
                    None, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
                )
            if not hicon:
                hicon = user32.LoadIconW(None, _make_int_resource(IDI_APPLICATION))
            self._hicon = hicon

            nid = _NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
            nid.hWnd = self._hwnd
            nid.uID = 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_APP + 20
            nid.hIcon = hicon
            nid.szTip = "RVC Portable %s" % __version__
            self._nid = nid
            shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

            self._ready.set()
            self._poll_status()
            poll_thread = threading.Thread(target=self._poll_loop, name="rvc-tray-status", daemon=True)
            poll_thread.start()

            msg = wintypes.MSG()
            while not self._stop_event.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result in (0, -1):
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            self._ready.set()
        finally:
            try:
                if self._nid is not None:
                    ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            except Exception:
                pass
            try:
                if self._hwnd:
                    ctypes.windll.user32.DestroyWindow(self._hwnd)
            except Exception:
                pass
            self._hwnd = None

    def _window_proc(self, hwnd, msg, wparam, lparam):
        user32 = ctypes.windll.user32
        if msg == WM_APP + 20:
            event = int(lparam) & 0xFFFF
            if event in (WM_RBUTTONUP, WM_CONTEXTMENU, WM_LBUTTONDBLCLK):
                self._show_menu(hwnd)
            return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self, hwnd) -> None:
        user32 = ctypes.windll.user32
        menu = user32.CreatePopupMenu()
        labels = self._labels
        user32.AppendMenuW(menu, MF_STRING, ID_SHOW, labels["show"])
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(
            menu,
            MF_STRING | (MF_GRAYED if self._monitor_running else 0),
            ID_START_MONITOR,
            labels["start_monitor"],
        )
        user32.AppendMenuW(
            menu,
            MF_STRING | (0 if self._monitor_running else MF_GRAYED),
            ID_STOP_MONITOR,
            labels["stop_monitor"],
        )
        user32.AppendMenuW(
            menu,
            MF_STRING | (MF_GRAYED if (not self._monitor_running and not self._engine_ready) else 0),
            ID_STOP_MONITOR_ENGINE,
            labels["stop_monitor_engine"],
        )
        user32.AppendMenuW(
            menu,
            MF_STRING | (0 if self._engine_ready else MF_GRAYED),
            ID_UNLOAD,
            labels["unload"],
        )
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_OPEN_MODELS, labels["open_models"])
        user32.AppendMenuW(menu, MF_STRING, ID_OPEN_LOGS, labels["open_logs"])
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_QUIT, labels["quit"])

        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.SetForegroundWindow(hwnd)
        command = user32.TrackPopupMenu(
            menu,
            TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_NONOTIFY,
            point.x,
            point.y,
            0,
            hwnd,
            None,
        )
        user32.DestroyMenu(menu)
        user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        if command:
            threading.Thread(target=self._run_command, args=(int(command),), daemon=True).start()

    # ------------------------------------------------------------------ status
    def _poll_loop(self) -> None:
        while not self._stop_event.wait(5.0):
            try:
                self._poll_status()
            except Exception:
                pass

    def _poll_status(self) -> None:
        monitor = self._get("/api/monitor")
        self._monitor_running = bool(monitor.get("running"))
        meta = self._get("/api/meta")
        engine = meta.get("engine") or {}
        loaded = bool(engine.get("loaded"))
        self._engine_ready = loaded
        monitor_label = self._labels["on"] if self._monitor_running else self._labels["off"]
        engine_label = self._labels["ready"] if loaded else self._labels["not_ready"]
        tip = self._labels["tip"] % (monitor_label, engine_label)
        if tip == self._last_tip:
            return
        self._last_tip = tip
        if self._nid is None:
            return
        self._nid.uFlags = NIF_TIP
        self._nid.szTip = tip[:127]
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))

    def _notify(self, title: str, message: str, flags: int = NIIF_INFO) -> None:
        if self._nid is None:
            return
        try:
            self._nid.uFlags = NIF_INFO
            self._nid.szInfoTitle = str(title)[:63]
            self._nid.szInfo = str(message)[:255]
            self._nid.dwInfoFlags = flags
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))
        except Exception:
            pass
