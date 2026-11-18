"""
Minimal network speed overlay (MB/s) for Windows.

- Drag with left mouse button to move (position is remembered)
- Double-click to open Settings (quit from there)
- Requires: python -m pip install psutil

Settings and error log live in %APPDATA%\\NetSpeedMeter\\
"""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import tkinter as tk
from collections import deque
from ctypes import wintypes
from tkinter import ttk

try:
    import winreg
except ImportError:
    winreg = None

# ---------------- tweakable constants ----------------
UPDATE_MS = 1000        # speed refresh interval
FULLSCREEN_MS = 500     # how often to check for fullscreen apps
FONT = ("Segoe UI", 10, "bold")
FG = "#FFFFFF"
BG = "#1E1E1E"
RED = "#FF4040"
GAP_BETWEEN = 4         # px between download value and upload arrow (one-line layout)
ARROW_GAP = 1           # px between an arrow and its number
SPIKE_MIN = 1.0         # MB/s: ignore spikes below this speed
SPIKE_FACTOR = 2.5      # speed must exceed this x the recent average
SPIKE_HOLD = 2.0        # seconds the arrow stays red
# -----------------------------------------------------

APP_NAME = "NetSpeedMeter"
APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
SETTINGS_DIR = os.path.join(APPDATA, APP_NAME)
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
LOG_FILE = os.path.join(SETTINGS_DIR, "error.log")
STARTUP_DIR = os.path.join(APPDATA, r"Microsoft\Windows\Start Menu\Programs\Startup")
SHORTCUT = os.path.join(STARTUP_DIR, APP_NAME + ".lnk")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"   # used by older versions
NO_WINDOW = 0x08000000

DEFAULTS = {
    "bg_opacity": 0.8,
    "text_opacity": 1.0,
    "layout": "one_line",
    "spike": True,
    "dim_fullscreen": True,
    "dim_level": 0.5,       # fraction of normal opacity while dimmed
    "pos": None,            # [x, y]
}

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


# ---------------- error logging (pythonw has no console) ----------------
def log_error(exc_type, exc, tb):
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S\n"))
            f.write("".join(traceback.format_exception(exc_type, exc, tb)) + "\n")
    except OSError:
        pass


sys.excepthook = log_error

try:
    import psutil
except ImportError:
    user32.MessageBoxW(None, "The 'psutil' module is not installed.\n\n"
                       "Open Command Prompt and run:\npython -m pip install psutil",
                       "Net Speed", 0x10)
    sys.exit(1)

# ---------------- only one copy at a time ----------------
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
_mutex = kernel32.CreateMutexW(None, False, "Local\\NetSpeedMeterOverlay")
if ctypes.get_last_error() == 183:          # ERROR_ALREADY_EXISTS
    sys.exit(0)

# Sharp text and real pixel coordinates on scaled (125%, 150%) displays
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


# ---------------- Win32 helpers ----------------
class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetShellWindow.restype = wintypes.HWND
user32.GetDesktopWindow.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]

MONITOR_DEFAULTTONULL = 0
MONITOR_DEFAULTTONEAREST = 2


def work_area():
    """Primary screen area excluding the taskbar: (left, top, right, bottom)."""
    r = wintypes.RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
    return r.left, r.top, r.right, r.bottom


def monitor_at(x, y, fallback=MONITOR_DEFAULTTONEAREST):
    return user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), fallback)


def fullscreen_monitor():
    """Monitor handle covered by a fullscreen foreground window, else None."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd or hwnd in (user32.GetShellWindow(), user32.GetDesktopWindow()):
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == os.getpid():
        return None
    cls = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, cls, 64)
    if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):   # desktop / taskbar
        return None
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    mon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not mon or not user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        return None
    m = mi.rcMonitor
    if r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom:
        return mon
    return None


# ---------------- settings storage ----------------
def load_settings():
    c = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            c.update(json.load(f))
    except (OSError, ValueError):
        pass
    return c


def save_settings():
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except OSError:
        pass


# ---------------- start with Windows (Startup folder shortcut) ----------------
def launch_target():
    """(program, arguments, working folder) that starts this app."""
    if getattr(sys, "frozen", False):                 # packaged .exe
        return sys.executable, "", os.path.dirname(sys.executable)
    exe = sys.executable
    folder, name = os.path.split(exe)
    if name.lower() == "python.exe" and os.path.exists(os.path.join(folder, "pythonw.exe")):
        exe = os.path.join(folder, "pythonw.exe")     # no console window
    script = os.path.abspath(__file__)
    return exe, f'"{script}"', os.path.dirname(script)


def run_powershell(command):
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=30)
    except Exception:
        log_error(*sys.exc_info())


def ps(s):
    return "'" + s.replace("'", "''") + "'"


def create_shortcut():
    target, args, folder = launch_target()
    run_powershell(
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({ps(SHORTCUT)});"
        f"$s.TargetPath={ps(target)};$s.Arguments={ps(args)};"
        f"$s.WorkingDirectory={ps(folder)};$s.Save()")


def delete_shortcut():
    run_powershell(f"Remove-Item -LiteralPath {ps(SHORTCUT)} -Force -ErrorAction SilentlyContinue")
    try:
        os.remove(SHORTCUT)
    except OSError:
        pass


def legacy_entry_exists():
    if not winreg:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def remove_legacy_entry():
    if not winreg:
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
    except OSError:
        pass


def is_startup_enabled():
    return os.path.exists(SHORTCUT)


def set_startup(enabled):
    remove_legacy_entry()
    if enabled:
        create_shortcut()
    else:
        delete_shortcut()
    return is_startup_enabled()


def startup_maintenance():
    """Move old registry entries to the Startup folder, and keep the
    shortcut pointing at this file even if it was moved."""
    if legacy_entry_exists() or is_startup_enabled():
        set_startup(True)


cfg = load_settings()

# ---------------- windows ----------------
# Two stacked borderless windows so background and text can have separate opacity:
#   root = background panel, fg = text layer with a see-through background
root = tk.Tk()
root.title("Net Speed")
root.report_callback_exception = log_error
root.overrideredirect(True)
root.configure(bg=BG)
root.attributes("-topmost", True)

fg = tk.Toplevel(root)
fg.overrideredirect(True)
fg.configure(bg=BG)
fg.attributes("-topmost", True)
fg.attributes("-transparentcolor", BG)

frame = tk.Frame(fg, bg=BG, padx=6, pady=3)
frame.pack()

dimmed = False


def apply_opacity():
    factor = cfg["dim_level"] if dimmed else 1.0
    root.attributes("-alpha", cfg["bg_opacity"] * factor)
    fg.attributes("-alpha", max(cfg["text_opacity"], 0.05) * factor)


apply_opacity()


def make_arrow(char):
    return tk.Label(frame, text=char, font=FONT, fg=FG, bg=BG, padx=0, bd=0)


def make_value():
    return tk.Label(frame, text="0.00 MB/s", font=FONT, fg=FG, bg=BG, padx=0, bd=0, anchor="w")


arrows = {"down": make_arrow("↓"), "up": make_arrow("↑")}
values = {"down": make_value(), "up": make_value()}

pos = [0, 0]
size = [0, 0]


def place(x=None, y=None):
    if x is not None:
        pos[0], pos[1] = int(x), int(y)
    geo = f"{size[0]}x{size[1]}+{pos[0]}+{pos[1]}"
    root.geometry(geo)
    fg.geometry(geo)


def refresh_size():
    fg.update_idletasks()
    w, h = frame.winfo_reqwidth(), frame.winfo_reqheight()
    if [w, h] != size:
        size[0], size[1] = w, h
        place()


def apply_layout():
    for w in list(arrows.values()) + list(values.values()):
        w.grid_forget()
    if cfg["layout"] == "two_lines":      # upload on top, download below
        arrows["up"].grid(row=0, column=0, sticky="w")
        values["up"].grid(row=0, column=1, sticky="w", padx=(ARROW_GAP, 0))
        arrows["down"].grid(row=1, column=0, sticky="w")
        values["down"].grid(row=1, column=1, sticky="w", padx=(ARROW_GAP, 0))
    else:
        arrows["down"].grid(row=0, column=0)
        values["down"].grid(row=0, column=1, padx=(ARROW_GAP, 0))
        arrows["up"].grid(row=0, column=2, padx=(GAP_BETWEEN, 0))
        values["up"].grid(row=0, column=3, padx=(ARROW_GAP, 0))
    refresh_size()


apply_layout()

# Restore the saved position exactly; fall back to bottom-right only if the
# saved spot is no longer on any screen (e.g. a monitor was unplugged).
saved = cfg.get("pos")
if (isinstance(saved, list) and len(saved) == 2
        and monitor_at(saved[0] + size[0] // 2, saved[1] + size[1] // 2, MONITOR_DEFAULTTONULL)):
    place(saved[0], saved[1])
else:
    _, _, right, bottom = work_area()
    place(right - size[0] - 10, bottom - size[1] - 10)


def remember_position():
    cfg["pos"] = [pos[0], pos[1]]
    save_settings()


def quit_app():
    remember_position()
    root.destroy()


# ---------------- dragging / double-click ----------------
drag = {"dx": 0, "dy": 0, "moved": False}


def start_drag(e):
    drag["dx"], drag["dy"], drag["moved"] = e.x_root - pos[0], e.y_root - pos[1], False


def do_drag(e):
    drag["moved"] = True
    place(e.x_root - drag["dx"], e.y_root - drag["dy"])


def end_drag(_e):
    fg.lift()
    if drag["moved"]:
        remember_position()


# ---------------- settings window ----------------
settings_win = None


def open_settings(_e=None):
    global settings_win
    if settings_win is not None and settings_win.winfo_exists():
        settings_win.lift()
        settings_win.focus_force()
        return

    win = tk.Toplevel(root)
    settings_win = win
    win.title("Net Speed Settings")
    win.attributes("-topmost", True)
    win.resizable(False, False)

    pad = {"padx": 14, "pady": 6}
    body = ttk.Frame(win, padding=6)
    body.pack(fill="both", expand=True)

    def add_slider(row, label, key, low=0):
        ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", **pad)
        var = tk.IntVar(value=int(round(cfg[key] * 100)))
        pct = ttk.Label(body, text=f"{var.get()}%", width=5)

        def on_change(_v=None):
            v = int(float(var.get()))
            pct.config(text=f"{v}%")
            cfg[key] = v / 100
            apply_opacity()
            save_settings()

        ttk.Scale(body, from_=low, to=100, orient="horizontal", length=170,
                  variable=var, command=on_change).grid(row=row, column=1, **pad)
        pct.grid(row=row, column=2, **pad)

    # Opacity
    add_slider(0, "Background opacity", "bg_opacity")
    add_slider(1, "Text opacity", "text_opacity", low=5)

    # Layout
    ttk.Label(body, text="Layout").grid(row=2, column=0, sticky="nw", **pad)
    layout_var = tk.StringVar(value=cfg["layout"])

    def on_layout():
        cfg["layout"] = layout_var.get()
        apply_layout()
        save_settings()

    lay = ttk.Frame(body)
    lay.grid(row=2, column=1, columnspan=2, sticky="w", **pad)
    ttk.Radiobutton(lay, text="Download and upload in one line",
                    variable=layout_var, value="one_line", command=on_layout).pack(anchor="w")
    ttk.Radiobutton(lay, text="Upload above, download below",
                    variable=layout_var, value="two_lines", command=on_layout).pack(anchor="w")

    # Fullscreen dimming
    dim_var = tk.BooleanVar(value=cfg["dim_fullscreen"])

    def on_dim():
        cfg["dim_fullscreen"] = dim_var.get()
        save_settings()

    ttk.Checkbutton(body, text="Dim when a video or app is fullscreen", variable=dim_var,
                    command=on_dim).grid(row=3, column=0, columnspan=3, sticky="w", **pad)
    add_slider(4, "    Dim to", "dim_level")

    # Spike warning
    spike_var = tk.BooleanVar(value=cfg["spike"])

    def on_spike():
        cfg["spike"] = spike_var.get()
        save_settings()

    ttk.Checkbutton(body, text="Turn arrow red on sudden increase in speed",
                    variable=spike_var, command=on_spike
                    ).grid(row=5, column=0, columnspan=3, sticky="w", **pad)

    # Start with Windows (checkbox shows the real result after trying)
    startup_var = tk.BooleanVar(value=is_startup_enabled())

    def on_startup():
        win.config(cursor="watch")
        win.update_idletasks()
        startup_var.set(set_startup(startup_var.get()))
        win.config(cursor="")

    ttk.Checkbutton(body, text="Start with Windows", variable=startup_var,
                    command=on_startup).grid(row=6, column=0, columnspan=3, sticky="w", **pad)

    # Buttons
    btns = ttk.Frame(body)
    btns.grid(row=7, column=0, columnspan=3, sticky="e", padx=14, pady=(10, 6))
    ttk.Button(btns, text="Quit app", command=quit_app).pack(side="left", padx=(0, 8))
    ttk.Button(btns, text="Close", command=win.destroy).pack(side="left")

    # Place near the overlay
    win.update_idletasks()
    ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
    sx = min(max(pos[0] + size[0] - ww, 0), win.winfo_screenwidth() - ww)
    sy = pos[1] - wh - 10
    if sy < 0:
        sy = pos[1] + size[1] + 10
    win.geometry(f"+{sx}+{sy}")


for widget in [root, fg, frame] + list(arrows.values()) + list(values.values()):
    widget.bind("<Button-1>", start_drag)
    widget.bind("<B1-Motion>", do_drag)
    widget.bind("<ButtonRelease-1>", end_drag)
    widget.bind("<Double-Button-1>", open_settings)


# ---------------- fullscreen dimming ----------------
def check_fullscreen():
    global dimmed
    try:
        want = False
        if cfg["dim_fullscreen"]:
            mon = fullscreen_monitor()
            if mon:
                here = monitor_at(pos[0] + size[0] // 2, pos[1] + size[1] // 2)
                want = (mon == here)      # only dim if fullscreen is on our screen
        if want != dimmed:
            dimmed = want
            apply_opacity()
    finally:
        root.after(FULLSCREEN_MS, check_fullscreen)


# ---------------- speed calculation ----------------
last = {"t": time.time(), "c": psutil.net_io_counters()}
history = {"down": deque(maxlen=8), "up": deque(maxlen=8)}
red_until = {"down": 0.0, "up": 0.0}


def check_spike(key, speed, now):
    h = history[key]
    if cfg["spike"] and len(h) >= 3:
        avg = sum(h) / len(h)
        if speed >= SPIKE_MIN and speed > SPIKE_FACTOR * max(avg, 0.05):
            red_until[key] = now + SPIKE_HOLD
    h.append(speed)


def update():
    try:
        now = time.time()
        c = psutil.net_io_counters()
        dt = (now - last["t"]) or 1e-9
        speeds = {
            "down": max(c.bytes_recv - last["c"].bytes_recv, 0) / dt / 1_000_000,
            "up": max(c.bytes_sent - last["c"].bytes_sent, 0) / dt / 1_000_000,
        }
        last["t"], last["c"] = now, c

        for key, speed in speeds.items():
            check_spike(key, speed, now)
            values[key].config(text=f"{speed:.2f} MB/s")
            hot = cfg["spike"] and now < red_until[key]
            arrows[key].config(fg=RED if hot else FG)

        refresh_size()
        root.lift()      # stay above other windows (and the taskbar)
        fg.lift()        # text layer above background layer
    finally:
        root.after(UPDATE_MS, update)


threading.Thread(target=startup_maintenance, daemon=True).start()
root.after(UPDATE_MS, update)
root.after(FULLSCREEN_MS, check_fullscreen)
root.mainloop()
