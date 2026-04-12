# SPDX-FileCopyrightText: 2026 Katushiro Endo
# SPDX-License-Identifier: MIT

__version__ = "1.0.0"

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

import win32gui
import win32con
import win32api
from pynput import keyboard
import pystray
from PIL import Image, ImageDraw

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
    os._exit(0)


def setup_tray():
    global _tray_icon

    menu = pystray.Menu(
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
# エントリポイント
# ============================================================

def main():
    # キーリスナーをバックグラウンドスレッドで起動
    listener        = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()

    # タスクトレイはメインスレッドで実行
    tray = setup_tray()
    tray.run()


if __name__ == "__main__":
    main()
