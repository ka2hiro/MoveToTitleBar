# SPDX-FileCopyrightText: 2026 Katushiro Endo
# SPDX-License-Identifier: MIT

__version__ = "1.1.0"

"""
move_to_titlebar.py  ― タスクトレイ常駐版

指定したキーバインドで、アクティブウィンドウのタイトルバーにマウスポインタを移動するスクリプト。

キーバインドの変更:
    下の HOTKEY_* 変数を編集してください。
"""

import ctypes
import ctypes.wintypes
import threading
import os
import sys
import json
import winreg

import win32gui
import win32con
import win32api
from pynput import keyboard
import pystray
from PIL import Image, ImageDraw
import customtkinter

# ============================================================
# ★ キーバインド設定（ここを変更してください）
# ============================================================
# 修飾キー: keyboard.Key.ctrl_l / alt_l / shift / cmd (Winキー)
# 通常キー: keyboard.KeyCode.from_char('t') など

HOTKEY_MODIFIERS = {keyboard.Key.ctrl_l, keyboard.Key.alt_l}  # Ctrl + Alt
HOTKEY_KEY       = keyboard.KeyCode.from_vk(0x54)              # + T

HOTKEY2_MODIFIERS = {keyboard.Key.ctrl_l, keyboard.Key.alt_l}  # Ctrl + Alt
HOTKEY2_KEY       = keyboard.KeyCode.from_vk(0x58)              # + X (閉じるボタンへ移動)

# タイトルバー内の水平位置（0.0=左端 〜 1.0=右端、0.5=中央）
TITLE_BAR_X_RATIO = 0.5


# ============================================================
# 設定ファイルの永続化
# ============================================================

CONFIG_DIR  = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "move_to_titlebar")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

# 文字列 <-> pynput.keyboard.Key のマップ（修飾キー用）
_MOD_NAME_TO_KEY = {
    "ctrl_l":  keyboard.Key.ctrl_l,
    "ctrl_r":  keyboard.Key.ctrl_r,
    "alt_l":   keyboard.Key.alt_l,
    "alt_r":   keyboard.Key.alt_r,
    "shift":   keyboard.Key.shift,
    "shift_r": keyboard.Key.shift_r,
    "cmd":     keyboard.Key.cmd,
    "cmd_r":   keyboard.Key.cmd_r,
}
_KEY_TO_MOD_NAME = {v: k for k, v in _MOD_NAME_TO_KEY.items()}


def _mods_to_names(mods):
    names = []
    for m in mods:
        nm = _KEY_TO_MOD_NAME.get(normalize_key(m))
        if nm:
            names.append(nm)
    return names


def _names_to_mods(names):
    out = set()
    for n in names:
        k = _MOD_NAME_TO_KEY.get(n)
        if k is not None:
            out.add(k)
    return out


DEFAULT_CONFIG = {
    "hotkey1": {"modifiers": ["ctrl_l", "alt_l"], "vk": 0x54},  # Ctrl+Alt+T
    "hotkey2": {"modifiers": ["ctrl_l", "alt_l"], "vk": 0x58},  # Ctrl+Alt+X
    "title_bar_x_ratio": 0.5,
    "autostart": False,
}


def _merge_defaults(cfg):
    out = json.loads(json.dumps(DEFAULT_CONFIG))
    if not isinstance(cfg, dict):
        return out
    for k, v in cfg.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return _merge_defaults(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def apply_config(cfg):
    """グローバル設定に反映する（on_press と競合しないよう _lock を取る）"""
    global HOTKEY_MODIFIERS, HOTKEY_KEY, HOTKEY2_MODIFIERS, HOTKEY2_KEY, TITLE_BAR_X_RATIO
    with _lock:
        HOTKEY_MODIFIERS  = _names_to_mods(cfg["hotkey1"]["modifiers"])
        HOTKEY_KEY        = keyboard.KeyCode.from_vk(int(cfg["hotkey1"]["vk"]))
        HOTKEY2_MODIFIERS = _names_to_mods(cfg["hotkey2"]["modifiers"])
        HOTKEY2_KEY       = keyboard.KeyCode.from_vk(int(cfg["hotkey2"]["vk"]))
        TITLE_BAR_X_RATIO = float(cfg["title_bar_x_ratio"])
        pressed_keys.clear()


# ============================================================
# Windows スタートアップ登録（HKCU\...\Run）
# ============================================================

STARTUP_KEY        = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_VALUE_NAME = "MoveToTitleBar"


def _startup_command():
    """スタートアップに登録するコマンド文字列を返す"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    runner = pyw if os.path.exists(pyw) else sys.executable
    return f'"{runner}" "{os.path.abspath(__file__)}"'


def is_autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY) as k:
            winreg.QueryValueEx(k, STARTUP_VALUE_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def enable_autostart():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, STARTUP_VALUE_NAME, 0, winreg.REG_SZ, _startup_command())


def disable_autostart():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, STARTUP_VALUE_NAME)
    except FileNotFoundError:
        pass


# ============================================================
# タスクトレイアイコン生成（外部 .ico 不要・PIL で動的生成）
# ============================================================

def create_tray_icon(size=64, enabled=True):
    """シンプルなアイコン画像をPILで生成して返す"""
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 背景円：有効=青、無効=グレー
    bg = (70, 130, 180, 255) if enabled else (120, 120, 120, 255)
    draw.ellipse([2, 2, size - 2, size - 2], fill=bg)

    # 上向き矢印
    cx    = size // 2
    white = (255, 255, 255, 255)
    draw.rectangle([cx - 4, size // 3, cx + 4, size * 2 // 3], fill=white)
    draw.polygon([
        (cx,      size // 6),
        (cx - 10, size // 3),
        (cx + 10, size // 3),
    ], fill=white)

    return img


# ============================================================
# マウス移動ロジック
# ============================================================

def get_titlebar_point(hwnd):
    """ウィンドウのタイトルバー上の座標を計算して返す（DPI対応）"""
    rect  = win32gui.GetWindowRect(hwnd)
    left, top, right, _ = rect

    dpi   = ctypes.windll.user32.GetDpiForWindow(hwnd) or 96
    scale = dpi / 96.0

    frame_y   = int(win32api.GetSystemMetrics(win32con.SM_CYSIZEFRAME) * scale)
    caption_h = int(win32api.GetSystemMetrics(win32con.SM_CYCAPTION)   * scale)

    title_top   = top   + frame_y
    title_bot   = top   + frame_y + caption_h
    title_left  = left  + frame_y
    title_right = right - frame_y

    cy = (title_top + title_bot) // 2
    cx = int(title_left + (title_right - title_left) * TITLE_BAR_X_RATIO)
    return cx, cy


def get_close_button_point(hwnd):
    """ウィンドウの閉じるボタン（×）中央の座標を計算して返す（DPI対応）"""
    rect  = win32gui.GetWindowRect(hwnd)
    _, top, right, _ = rect

    dpi   = ctypes.windll.user32.GetDpiForWindow(hwnd) or 96
    scale = dpi / 96.0

    frame_x   = int(win32api.GetSystemMetrics(win32con.SM_CXSIZEFRAME) * scale)
    frame_y   = int(win32api.GetSystemMetrics(win32con.SM_CYSIZEFRAME) * scale)
    caption_h = int(win32api.GetSystemMetrics(win32con.SM_CYCAPTION)   * scale)
    button_w  = int(win32api.GetSystemMetrics(win32con.SM_CXSIZE)      * scale)

    cy = top + frame_y + caption_h // 2
    cx = right - frame_x - button_w // 2
    return cx, cy


def has_titlebar(hwnd):
    """ウィンドウにタイトルバーがあるか判定する"""
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    return bool(style & win32con.WS_CAPTION)


def move_mouse_to_titlebar():
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd or win32gui.IsIconic(hwnd):
        return
    try:
        if not has_titlebar(hwnd):
            return
        cx, cy = get_titlebar_point(hwnd)
        ctypes.windll.user32.SetCursorPos(cx, cy)
    except Exception as e:
        print(f"[Error] {e}")


def has_close_button(hwnd):
    """ウィンドウに有効な閉じるボタンがあるか判定する"""
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    if not (style & win32con.WS_SYSMENU):
        return False
    hsysmenu = win32gui.GetSystemMenu(hwnd, False)
    if not hsysmenu:
        return False
    state = win32gui.GetMenuState(hsysmenu, win32con.SC_CLOSE, win32con.MF_BYCOMMAND)
    if state == -1:
        return False
    if state & (win32con.MF_DISABLED | win32con.MF_GRAYED):
        return False
    return True


def move_mouse_to_close_button():
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd or win32gui.IsIconic(hwnd):
        return
    try:
        if not has_close_button(hwnd):
            return
        cx, cy = get_close_button_point(hwnd)
        ctypes.windll.user32.SetCursorPos(cx, cy)
    except Exception as e:
        print(f"[Error] {e}")


# ============================================================
# ホットキー監視
# ============================================================

pressed_keys = set()
_lock        = threading.Lock()
_enabled     = True   # トグル用


def normalize_key(key):
    """左右修飾キーを同一視する"""
    _alias = {
        keyboard.Key.ctrl_r:  keyboard.Key.ctrl_l,
        keyboard.Key.alt_r:   keyboard.Key.alt_l,
        keyboard.Key.shift_r: keyboard.Key.shift,
        keyboard.Key.cmd_r:   keyboard.Key.cmd,
    }
    return _alias.get(key, key)


def _vk_of(key):
    """KeyCode から仮想キーコードを取り出す（char しかない場合は ord で変換）"""
    if isinstance(key, keyboard.KeyCode):
        if key.vk is not None:
            return key.vk
        if key.char is not None:
            return ord(key.char.upper())
    return None


def on_press(key):
    global _enabled
    with _lock:
        pressed_keys.add(normalize_key(key))
        if not _enabled:
            return
        nkey = normalize_key(key)
        mods1 = {normalize_key(k) for k in HOTKEY_MODIFIERS}
        if mods1 <= pressed_keys and _vk_of(nkey) == _vk_of(normalize_key(HOTKEY_KEY)):
            threading.Thread(target=move_mouse_to_titlebar, daemon=True).start()
        mods2 = {normalize_key(k) for k in HOTKEY2_MODIFIERS}
        if mods2 <= pressed_keys and _vk_of(nkey) == _vk_of(normalize_key(HOTKEY2_KEY)):
            threading.Thread(target=move_mouse_to_close_button, daemon=True).start()


def on_release(key):
    with _lock:
        pressed_keys.discard(normalize_key(key))


# ============================================================
# タスクトレイ
# ============================================================

_tray_icon = None


def hotkey_label(modifiers, key):
    mod_names = [
        str(k).replace("Key.", "").replace("_l", "").capitalize()
        for k in modifiers
    ]
    key_name = (
        key.char if hasattr(key, "char") and key.char
        else chr(key.vk) if hasattr(key, "vk") and key.vk
        else str(key).replace("Key.", "")
    )
    return " + ".join(mod_names + [key_name.upper()])


def build_tooltip():
    state = "有効" if _enabled else "無効"
    label1 = hotkey_label(HOTKEY_MODIFIERS, HOTKEY_KEY)
    label2 = hotkey_label(HOTKEY2_MODIFIERS, HOTKEY2_KEY)
    return f"move_to_titlebar v{__version__} [{state}]\nタイトルバー: {label1}\n閉じるボタン: {label2}"


def toggle_enabled(icon, item):
    global _enabled
    _enabled   = not _enabled
    icon.icon  = create_tray_icon(enabled=_enabled)
    icon.title = build_tooltip()


def on_quit(icon, item):
    icon.stop()
    try:
        if _tk_root is not None:
            _tk_root.after(0, _tk_root.quit)
    except Exception:
        pass
    os._exit(0)


def on_open_settings(icon, item):
    if _tk_root is not None:
        _tk_root.after(0, _show_settings_window)


def setup_tray():
    global _tray_icon

    menu = pystray.Menu(
        pystray.MenuItem("設定…", on_open_settings, default=True),
        pystray.MenuItem(
            lambda _: ("✔ 有効" if _enabled else "  有効"),
            toggle_enabled,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("終了", on_quit),
    )

    _tray_icon = pystray.Icon(
        name  = "move_to_titlebar",
        icon  = create_tray_icon(enabled=True),
        title = build_tooltip(),
        menu  = menu,
    )
    return _tray_icon


# ============================================================
# 設定ウィンドウ（CustomTkinter）
# ============================================================

_tk_root         = None
_settings_window = None


def _format_hotkey(mods_names, vk):
    label_mods = [n.replace("_l", "").replace("_r", "").capitalize() for n in mods_names]
    try:
        key_name = chr(int(vk)).upper()
    except Exception:
        key_name = str(vk)
    return " + ".join(label_mods + [key_name]) if label_mods else key_name


class _HotkeyCapture:
    """次に押された「修飾キー + 通常キー」を 1 組だけ拾う一時リスナー"""
    def __init__(self, on_done):
        self.on_done  = on_done
        self.mods     = set()
        self.listener = None

    def start(self):
        self.listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self.listener.daemon = True
        self.listener.start()

    def _on_press(self, key):
        nk = normalize_key(key)
        if nk in _KEY_TO_MOD_NAME:
            self.mods.add(nk)
            return
        vk = _vk_of(nk)
        if vk is None:
            return
        mod_names = sorted(_KEY_TO_MOD_NAME[m] for m in self.mods if m in _KEY_TO_MOD_NAME)
        result = {"modifiers": mod_names, "vk": vk}
        try:
            self.listener.stop()
        except Exception:
            pass
        self.on_done(result)
        return False

    def _on_release(self, key):
        self.mods.discard(normalize_key(key))


class SettingsWindow(customtkinter.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title(f"move_to_titlebar 設定 v{__version__}")
        self.geometry("460x440")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        cfg = load_config()
        self._hotkey1 = dict(cfg["hotkey1"])
        self._hotkey2 = dict(cfg["hotkey2"])

        pad = {"padx": 16, "pady": 6}

        customtkinter.CTkLabel(self, text="タイトルバー移動ホットキー", anchor="w").pack(fill="x", **pad)
        row1 = customtkinter.CTkFrame(self, fg_color="transparent")
        row1.pack(fill="x", padx=16)
        self._hotkey1_label = customtkinter.CTkLabel(row1, text="", width=240, anchor="w")
        self._hotkey1_label.pack(side="left")
        customtkinter.CTkButton(row1, text="変更…", width=90,
                                command=lambda: self._capture("hotkey1")).pack(side="right")

        customtkinter.CTkLabel(self, text="閉じるボタン移動ホットキー", anchor="w").pack(fill="x", **pad)
        row2 = customtkinter.CTkFrame(self, fg_color="transparent")
        row2.pack(fill="x", padx=16)
        self._hotkey2_label = customtkinter.CTkLabel(row2, text="", width=240, anchor="w")
        self._hotkey2_label.pack(side="left")
        customtkinter.CTkButton(row2, text="変更…", width=90,
                                command=lambda: self._capture("hotkey2")).pack(side="right")

        customtkinter.CTkLabel(self, text="タイトルバー水平位置(0.0=左 / 1.0=右)", anchor="w").pack(fill="x", **pad)
        slider_row = customtkinter.CTkFrame(self, fg_color="transparent")
        slider_row.pack(fill="x", padx=16)
        self._ratio_var = customtkinter.DoubleVar(value=float(cfg["title_bar_x_ratio"]))
        self._ratio_label = customtkinter.CTkLabel(slider_row, text="", width=50)
        self._ratio_label.pack(side="right")
        self._slider = customtkinter.CTkSlider(
            slider_row, from_=0.0, to=1.0, number_of_steps=20,
            variable=self._ratio_var, command=self._on_slider,
        )
        self._slider.pack(side="left", fill="x", expand=True)
        self._on_slider(self._ratio_var.get())

        self._autostart_var = customtkinter.BooleanVar(value=bool(cfg.get("autostart", False)))
        customtkinter.CTkCheckBox(
            self, text="Windows スタートアップに登録する",
            variable=self._autostart_var,
        ).pack(anchor="w", padx=16, pady=(16, 6))

        if not getattr(sys, "frozen", False):
            customtkinter.CTkLabel(
                self,
                text="※ スクリプト実行中のため、登録されるのは現在の .py の実行コマンドです",
                text_color="gray60",
                anchor="w",
                wraplength=420,
            ).pack(fill="x", padx=16)

        btn_row = customtkinter.CTkFrame(self, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=16, pady=16)
        customtkinter.CTkButton(btn_row, text="キャンセル", width=110,
                                command=self._on_cancel).pack(side="right", padx=(8, 0))
        customtkinter.CTkButton(btn_row, text="保存", width=110,
                                command=self._on_save).pack(side="right")

        self._refresh_labels()

    def _refresh_labels(self):
        self._hotkey1_label.configure(text=_format_hotkey(self._hotkey1["modifiers"], self._hotkey1["vk"]))
        self._hotkey2_label.configure(text=_format_hotkey(self._hotkey2["modifiers"], self._hotkey2["vk"]))

    def _on_slider(self, value):
        self._ratio_label.configure(text=f"{float(value):.2f}")

    def _capture(self, which):
        label = self._hotkey1_label if which == "hotkey1" else self._hotkey2_label
        label.configure(text="（キーを押してください…）")

        def done(result):
            def apply():
                if which == "hotkey1":
                    self._hotkey1 = result
                else:
                    self._hotkey2 = result
                self._refresh_labels()
            self.after(0, apply)

        _HotkeyCapture(done).start()

    def _on_save(self):
        cfg = {
            "hotkey1":           self._hotkey1,
            "hotkey2":           self._hotkey2,
            "title_bar_x_ratio": round(float(self._ratio_var.get()), 2),
            "autostart":         bool(self._autostart_var.get()),
        }
        try:
            save_config(cfg)
            apply_config(cfg)
            if cfg["autostart"]:
                enable_autostart()
            else:
                disable_autostart()
        except Exception as e:
            print(f"[Settings] save failed: {e}")
            return

        if _tray_icon is not None:
            try:
                _tray_icon.title = build_tooltip()
            except Exception:
                pass

        self._on_cancel()

    def _on_cancel(self):
        global _settings_window
        try:
            self.destroy()
        finally:
            _settings_window = None


def _show_settings_window():
    global _settings_window
    if _settings_window is not None and _settings_window.winfo_exists():
        _settings_window.deiconify()
        _settings_window.lift()
        _settings_window.focus_force()
        return
    _settings_window = SettingsWindow(_tk_root)
    _settings_window.after(100, _settings_window.lift)
    _settings_window.focus_force()


# ============================================================
# シャットダウン監視（WM_QUERYENDSESSION / WM_ENDSESSION 応答）
# ============================================================

WM_DESTROY         = 0x0002
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION      = 0x0016

# LRESULT はポインタ幅(64bit OS では 64bit)。c_long だとオーバーフローする。
LRESULT = ctypes.c_ssize_t

_WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    ctypes.wintypes.HWND,
    ctypes.c_uint,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)

_user32_defwindowproc = ctypes.windll.user32.DefWindowProcW
_user32_defwindowproc.restype  = LRESULT
_user32_defwindowproc.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.c_uint,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]


class _WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style",         ctypes.c_uint),
        ("lpfnWndProc",   _WNDPROC),
        ("cbClsExtra",    ctypes.c_int),
        ("cbWndExtra",    ctypes.c_int),
        ("hInstance",     ctypes.wintypes.HINSTANCE),
        ("hIcon",         ctypes.wintypes.HICON),
        ("hCursor",       ctypes.wintypes.HANDLE),
        ("hbrBackground", ctypes.wintypes.HBRUSH),
        ("lpszMenuName",  ctypes.wintypes.LPCWSTR),
        ("lpszClassName", ctypes.wintypes.LPCWSTR),
    ]


def _shutdown_cleanup():
    try:
        if _tray_icon is not None:
            _tray_icon.stop()
    except Exception:
        pass
    os._exit(0)


def _wnd_proc(hwnd, msg, wparam, lparam):
    if msg == WM_QUERYENDSESSION:
        return 1
    if msg == WM_ENDSESSION:
        if wparam:
            threading.Thread(target=_shutdown_cleanup, daemon=True).start()
        return 0
    if msg == WM_DESTROY:
        ctypes.windll.user32.PostQuitMessage(0)
        return 0
    return _user32_defwindowproc(hwnd, msg, wparam, lparam)


_wnd_proc_ref = _WNDPROC(_wnd_proc)


def _run_shutdown_watcher():
    user32   = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    hInstance  = kernel32.GetModuleHandleW(None)
    class_name = "MoveToTitleBarShutdownWatcher"

    wc = _WNDCLASS()
    wc.lpfnWndProc   = _wnd_proc_ref
    wc.hInstance     = hInstance
    wc.lpszClassName = class_name

    if not user32.RegisterClassW(ctypes.byref(wc)):
        return

    hwnd = user32.CreateWindowExW(
        0, class_name, "MoveToTitleBarShutdownWatcher",
        0, 0, 0, 0, 0, 0, 0, hInstance, None,
    )
    if not hwnd:
        return

    # シャットダウン順序を後ろ寄りにしておく（0x100 = 低い優先度）。
    try:
        kernel32.SetProcessShutdownParameters(0x100, 0)
    except Exception:
        pass

    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


# ============================================================
# エントリポイント
# ============================================================

def main():
    global _tk_root

    # 設定を読み込み、グローバルに反映
    cfg = load_config()
    apply_config(cfg)

    # CustomTkinter ルート（常時非表示・設定画面の親）
    _tk_root = customtkinter.CTk()
    _tk_root.withdraw()
    _tk_root.protocol("WM_DELETE_WINDOW", lambda: _tk_root.withdraw())

    # キーリスナーをバックグラウンドスレッドで起動
    listener        = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()

    # シャットダウン監視ウィンドウを専用スレッドで起動
    watcher        = threading.Thread(target=_run_shutdown_watcher)
    watcher.daemon = True
    watcher.start()

    # タスクトレイはバックグラウンドスレッドで実行
    tray       = setup_tray()
    tray_thread = threading.Thread(target=tray.run, daemon=True)
    tray_thread.start()

    # メインスレッドは Tk mainloop
    _tk_root.mainloop()


if __name__ == "__main__":
    main()
