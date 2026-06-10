"""
CivicDiag — OBD-II diagnostic suite for the 1999 Honda Civic
(works on any 1996+ OBD-II vehicle via an ELM327 USB adapter).

Run:  python main.py   (or launch CivicDiag.exe)
"""

import csv
import os
import queue
import re
import threading
import time
import webbrowser
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from elm327 import ELM327, ELM327Error, NoDataError, find_ports
from demo_elm import DemoELM327, DEMO_PORT
import obd_data as od
import reports
from diagnostics import PRESETS
from charts import StripChart, CHART_COLORS
from prefs import load_prefs, save_prefs, ensure_save_folder

VERSION = "2.0"
APP_TITLE = "CivicDiag"
POLL_GAP = 0.02

PALETTES = {
    "dark": dict(bg="#14171c", panel="#1b2026", panel2="#242b33",
                 card="#20262e", fg="#e8eaed", muted="#9aa3ad",
                 accent="#e23b3b", green="#34c759", sel="#2f4156",
                 grid="#252c34", chartbg="#171b20",
                 termbg="#101418", termfg="#9fdf9f"),
    "light": dict(bg="#eef1f5", panel="#ffffff", panel2="#dde3ea",
                  card="#f7f9fb", fg="#1a1d21", muted="#5b6570",
                  accent="#d42a2a", green="#1e9e3e", sel="#cfe0f5",
                  grid="#e2e7ee", chartbg="#fcfdfe",
                  termbg="#101418", termfg="#9fdf9f"),
}
SEV_FG = {1: "#34c759", 2: "#e8b339", 3: "#ff8c42", 4: "#ff5252"}

P = dict(PALETTES["dark"])  # active palette, swapped on theme change

EVENT_PRESETS = ["Revved engine", "Felt stumble", "Idle", "Cruise",
                 "Full throttle", "Cold start", "A/C on"]

LIKELY_ADAPTER = re.compile(r"CH340|CP210|FTDI|PROLIFIC|OBD|USB[- ]?SERIAL",
                            re.I)


def numeric(value):
    """Pull a float out of a live-data value ('0.700 V / +1.6%' → 0.7)."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.match(r"\s*([+-]?\d+(?:\.\d+)?)", value)
        if m:
            return float(m.group(1))
    return None


def fmt(x):
    if x is None or x == "":
        return ""
    if isinstance(x, float):
        return f"{x:.1f}".rstrip("0").rstrip(".")
    return str(x)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.prefs = load_prefs()
        global P
        P = dict(PALETTES.get(self.prefs["theme"], PALETTES["dark"]))

        self.title(APP_TITLE)
        self.geometry("1100x780")
        self.minsize(940, 640)

        self.elm = None
        self.supported_pids = set()
        self.live_running = False
        self.csv_file = None
        self.csv_writer = None
        self.csv_path = None
        self.log_started = None
        self.stats = {}           # pid -> [min, max, sum, count]
        self.latest = {}          # pid -> last value
        self.active_alerts = {}   # pid -> (lo, hi, msg)
        self._alerting = set()
        self._pending_events = []
        self._event_lock = threading.Lock()
        self.session = reports.empty_session()
        self.live_pids = [p for p in self.prefs.get("live_pids", [])] or \
            list(od.DEFAULT_LIVE_PIDS)
        self.term_history = []
        self.term_hist_i = 0
        self._play_job = None
        self._last_status = ""

        self.ui_queue = queue.Queue()
        self._fonts()
        self._build_all()
        self.after(50, self._drain_ui_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if not self.prefs.get("first_run_done"):
            self.after(300, self._welcome)

    # ------------------------------------------------------------------
    # Fonts / theme / rebuild
    # ------------------------------------------------------------------

    def _fonts(self):
        big = self.prefs.get("large_controls")
        base = 12 if big else 10
        self.F = ("Segoe UI", base)
        self.F_SM = ("Segoe UI", base - 1)
        self.F_B = ("Segoe UI Semibold", base)
        self.F_BIG = ("Segoe UI", 30 if big else 24, "bold")
        self.F_TITLE = ("Segoe UI", 16 if big else 15, "bold")
        self.BTN_PAD = (20, 12) if big else (14, 7)
        self.ROW_H = 34 if big else 28

    def _apply_theme(self):
        self.configure(bg=P["bg"])
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=P["bg"], foreground=P["fg"],
                        fieldbackground=P["panel"], font=self.F,
                        bordercolor=P["panel2"], lightcolor=P["bg"],
                        darkcolor=P["bg"])
        style.configure("TFrame", background=P["bg"])
        style.configure("TLabel", background=P["bg"], foreground=P["fg"])
        style.configure("TButton", background=P["panel2"],
                        foreground=P["fg"], borderwidth=0,
                        padding=self.BTN_PAD, font=self.F)
        style.map("TButton",
                  background=[("disabled", P["panel"]),
                              ("active", P["sel"])],
                  foreground=[("disabled", P["muted"])])
        style.configure("Accent.TButton", background=P["accent"],
                        foreground="white", font=self.F_B)
        style.map("Accent.TButton",
                  background=[("disabled", P["panel"]),
                              ("active", "#f05050")])
        style.configure("TNotebook", background=P["bg"], borderwidth=0,
                        tabmargins=(8, 6, 8, 0))
        style.configure("TNotebook.Tab", background=P["bg"],
                        foreground=P["muted"], padding=(16, 9),
                        font=self.F, borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", P["card"])],
                  foreground=[("selected", P["fg"])])
        style.configure("Treeview", background=P["panel"],
                        fieldbackground=P["panel"], foreground=P["fg"],
                        rowheight=self.ROW_H, borderwidth=0)
        style.configure("Treeview.Heading", background=P["panel2"],
                        foreground=P["muted"],
                        font=("Segoe UI Semibold", 9), padding=(8, 6),
                        borderwidth=0)
        style.map("Treeview.Heading", background=[("active", P["panel2"])])
        style.map("Treeview", background=[("selected", P["sel"])],
                  foreground=[("selected", P["fg"])])
        style.configure("TCombobox", fieldbackground=P["panel"],
                        background=P["panel2"], foreground=P["fg"],
                        arrowcolor=P["fg"], selectbackground=P["panel"],
                        selectforeground=P["fg"], padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", P["panel"])])
        style.configure("TEntry", fieldbackground=P["panel"],
                        foreground=P["fg"], insertcolor=P["fg"], padding=6,
                        borderwidth=0)
        style.configure("Vertical.TScrollbar", background=P["panel2"],
                        troughcolor=P["bg"], borderwidth=0,
                        arrowcolor=P["muted"])
        for opt, val in (("background", P["panel"]),
                         ("foreground", P["fg"]),
                         ("selectBackground", P["sel"]),
                         ("selectForeground", P["fg"])):
            self.option_add(f"*TCombobox*Listbox.{opt}", val)

    def _dark_title_bar(self):
        try:
            import ctypes
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            value = ctypes.c_int(1 if self.prefs["theme"] == "dark" else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
        except Exception:
            pass

    def _build_all(self):
        self._apply_theme()
        self._build_menu()
        self._build_ui()
        self.after(10, self._dark_title_bar)

    def _rebuild_ui(self):
        """Destroy and rebuild the whole UI (theme / mode / size change)."""
        self._stop_live()
        self._stop_play()
        self._fonts()
        for w in self.winfo_children():
            w.destroy()
        self._build_all()
        if self.elm and self.elm.connected:
            self.connect_btn.config(text="Disconnect")
            self.proto_var.set(
                f"{self.elm.protocol_name}  ·  {self.elm.elm_version}")
        self.status_var.set(self._last_status or "Ready.")

    # ------------------------------------------------------------------
    # Thread-safe UI plumbing
    # ------------------------------------------------------------------

    def ui(self, fn, *args):
        self.ui_queue.put((fn, args))

    def _drain_ui_queue(self):
        try:
            while True:
                fn, args = self.ui_queue.get_nowait()
                try:
                    fn(*args)
                except tk.TclError:
                    pass
        except queue.Empty:
            pass
        self.after(50, self._drain_ui_queue)

    def _set_status(self, text):
        self._last_status = text
        self.status_var.set(text)

    def _run_bg(self, fn, busy_msg=None):
        if busy_msg:
            self._set_status(busy_msg)

        def wrapper():
            try:
                fn()
            except NoDataError as e:
                self.ui(self._set_status, f"No data: {e}")
            except ELM327Error as e:
                self.ui(messagebox.showerror, "Adapter error", str(e))
                self.ui(self._set_status, "Error — see dialog")
            except Exception as e:
                self.ui(messagebox.showerror, "Unexpected error", repr(e))

        threading.Thread(target=wrapper, daemon=True).start()

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self):
        m = tk.Menu(self)
        filem = tk.Menu(m, tearoff=0)
        filem.add_command(label="Choose save folder…",
                          command=self._choose_folder)
        filem.add_command(label="Open save folder",
                          command=lambda: os.startfile(
                              ensure_save_folder(self.prefs)))
        filem.add_separator()
        filem.add_command(label="Export session as text…",
                          command=lambda: self._export_session("txt"))
        filem.add_command(label="Export session as JSON…",
                          command=lambda: self._export_session("json"))
        filem.add_command(label="Export codes as CSV…",
                          command=lambda: self._export_session("csv"))
        filem.add_separator()
        filem.add_command(label="Exit", command=self._on_close)
        m.add_cascade(label="File", menu=filem)

        viewm = tk.Menu(m, tearoff=0)
        self.theme_var = tk.BooleanVar(
            value=self.prefs["theme"] == "light")
        viewm.add_checkbutton(label="Light mode", variable=self.theme_var,
                              command=self._toggle_theme)
        self.large_var = tk.BooleanVar(
            value=self.prefs.get("large_controls", False))
        viewm.add_checkbutton(label="Large controls (in-car use)",
                              variable=self.large_var,
                              command=self._toggle_large)
        self.adv_var = tk.BooleanVar(
            value=self.prefs.get("mode") == "advanced")
        viewm.add_checkbutton(label="Advanced mode (all tabs)",
                              variable=self.adv_var,
                              command=self._toggle_mode)
        m.add_cascade(label="View", menu=viewm)

        helpm = tk.Menu(m, tearoff=0)
        helpm.add_command(label="Getting started guide",
                          command=self._welcome)
        helpm.add_command(label="Connection troubleshooting",
                          command=self._troubleshoot)
        helpm.add_command(label="About CivicDiag", command=self._about)
        m.add_cascade(label="Help", menu=helpm)
        self.config(menu=m)

    def _toggle_theme(self):
        self.prefs["theme"] = "light" if self.theme_var.get() else "dark"
        global P
        P = dict(PALETTES[self.prefs["theme"]])
        save_prefs(self.prefs)
        self._rebuild_ui()

    def _toggle_large(self):
        self.prefs["large_controls"] = self.large_var.get()
        save_prefs(self.prefs)
        self._rebuild_ui()

    def _toggle_mode(self):
        self.prefs["mode"] = "advanced" if self.adv_var.get() else "basic"
        save_prefs(self.prefs)
        self._rebuild_ui()

    def _choose_folder(self):
        folder = filedialog.askdirectory(
            initialdir=ensure_save_folder(self.prefs),
            title="Where should logs and reports be saved?")
        if folder:
            self.prefs["save_folder"] = folder
            save_prefs(self.prefs)
            self._set_status(f"Save folder: {folder}")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        bar = tk.Frame(self, bg=P["bg"])
        bar.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(bar, text="CivicDiag", bg=P["bg"], fg=P["fg"],
                 font=self.F_TITLE).pack(side="left")
        tk.Label(bar, text="  1999 Honda Civic · OBD-II", bg=P["bg"],
                 fg=P["muted"], font=self.F_SM).pack(side="left",
                                                     pady=(6, 0))
        self.mil_label = tk.Label(bar, text="MIL", bg="#3a4048",
                                  fg="white",
                                  font=("Segoe UI Semibold", 9),
                                  padx=10, pady=3)
        self.mil_label.pack(side="right", padx=(8, 0))
        tk.Button(bar, text="📷", command=self._screenshot, bg=P["panel2"],
                  fg=P["fg"], relief="flat", padx=8,
                  activebackground=P["sel"]).pack(side="right", padx=4)
        self.proto_var = tk.StringVar(value="Not connected")
        tk.Label(bar, textvariable=self.proto_var, bg=P["bg"],
                 fg=P["muted"], font=self.F_SM).pack(side="right", padx=8)

        conn = tk.Frame(self, bg=P["bg"])
        conn.pack(fill="x", padx=12, pady=(2, 6))
        tk.Label(conn, text="Port", bg=P["bg"], fg=P["muted"],
                 font=self.F_SM).pack(side="left")
        self.port_var = tk.StringVar(value=self.prefs.get("last_port", ""))
        self.port_combo = ttk.Combobox(conn, textvariable=self.port_var,
                                       width=44, state="readonly")
        self.port_combo.pack(side="left", padx=8)
        ttk.Button(conn, text="↻ Rescan",
                   command=self._refresh_ports).pack(side="left")
        self.connect_btn = ttk.Button(conn, text="Connect",
                                      style="Accent.TButton",
                                      command=self._toggle_connect)
        self.connect_btn.pack(side="left", padx=10)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(0, 4))

        # build every tab; only attach the ones for the current mode
        self.tab_frames = {}
        self._build_dtc_tab()
        self._build_live_tab()
        self._build_charts_tab()
        self._build_guided_tab()
        self._build_reports_tab()
        self._build_freeze_tab()
        self._build_readiness_tab()
        self._build_o2_tab()
        self._build_info_tab()
        self._build_terminal_tab()

        basic = ["dtc", "live", "charts", "guided", "reports"]
        advanced = basic + ["freeze", "ready", "o2", "info", "term"]
        titles = {"dtc": " Trouble Codes ", "live": " Live Data ",
                  "charts": " Charts ", "guided": " Guided Diagnostics ",
                  "reports": " Reports ", "freeze": " Freeze Frame ",
                  "ready": " Readiness ", "o2": " O2 Tests ",
                  "info": " Vehicle Info ", "term": " Terminal "}
        for key in (advanced if self.prefs.get("mode") == "advanced"
                    else basic):
            self.nb.add(self.tab_frames[key], text=titles[key])

        self.status_var = tk.StringVar(
            value="Plug the USB adapter into the car, ignition ON (II), "
                  "pick the COM port and hit Connect — or pick DEMO to "
                  "explore without the car.")
        tk.Label(self, textvariable=self.status_var, bg=P["panel"],
                 fg=P["muted"], anchor="w", font=self.F_SM, padx=12,
                 pady=5).pack(fill="x", side="bottom")
        self._refresh_ports()

    def _tab(self, key):
        outer = tk.Frame(self.nb, bg=P["card"])
        self.tab_frames[key] = outer
        inner = tk.Frame(outer, bg=P["card"])
        inner.pack(fill="both", expand=True, padx=10, pady=10)
        return inner

    def _make_tree(self, parent, columns, widths):
        frame = tk.Frame(parent, bg=P["card"])
        tree = ttk.Treeview(frame, columns=columns, show="headings",
                            selectmode="browse")
        for col, w in zip(columns, widths):
            tree.heading(col, text=col)
            tree.column(col, width=w, anchor="w")
        tree.tag_configure("even", background=P["panel"])
        tree.tag_configure("odd", background=P["card"])
        for sev, color in SEV_FG.items():
            tree.tag_configure(f"sev{sev}", foreground=color)
        tree.tag_configure("alert", foreground="#ff5252")
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return frame, tree

    @staticmethod
    def _restripe(tree, extra=None):
        for i, iid in enumerate(tree.get_children()):
            tags = ["odd" if i % 2 else "even"]
            if extra and iid in extra:
                tags.append(extra[iid])
            tree.item(iid, tags=tuple(tags))

    def _toolbar(self, parent):
        bar = tk.Frame(parent, bg=P["card"])
        bar.pack(fill="x", pady=(0, 8))
        return bar

    def _hint(self, parent, text):
        tk.Label(parent, text=text, bg=P["card"], fg=P["muted"],
                 font=self.F_SM, wraplength=520,
                 justify="left").pack(side="left", padx=12)

    # ---- Trouble codes tab ----

    def _build_dtc_tab(self):
        tab = self._tab("dtc")
        btns = self._toolbar(tab)
        ttk.Button(btns, text="Read Codes", style="Accent.TButton",
                   command=lambda: self._run_bg(self._read_dtcs,
                                                "Reading trouble codes…")
                   ).pack(side="left")
        ttk.Button(btns, text="Clear Codes…",
                   command=self._clear_dtcs_confirm).pack(side="left",
                                                          padx=6)
        ttk.Button(btns, text="Copy Codes",
                   command=self._copy_codes).pack(side="left")
        ttk.Button(btns, text="Save Report",
                   command=lambda: self._make_report("check")
                   ).pack(side="left", padx=6)
        self.dtc_summary = tk.StringVar(value="")
        tk.Label(btns, textvariable=self.dtc_summary, bg=P["card"],
                 fg=P["muted"], font=self.F_SM).pack(side="left", padx=10)

        frame, self.dtc_tree = self._make_tree(
            tab, ("Status", "Code", "Severity", "Description"),
            (90, 80, 90, 600))
        frame.pack(fill="both", expand=True)
        self.dtc_tree.bind("<<TreeviewSelect>>", self._on_dtc_select)

        # detail panel
        det = tk.Frame(tab, bg=P["panel2"])
        det.pack(fill="x", pady=(8, 0))
        self.dtc_detail = tk.Text(det, height=8, wrap="word", bg=P["panel2"],
                                  fg=P["fg"], relief="flat", font=self.F_SM,
                                  padx=10, pady=8, cursor="arrow")
        self.dtc_detail.pack(side="left", fill="both", expand=True)
        self.dtc_detail.tag_configure("h", font=self.F_B)
        self.dtc_detail.tag_configure("m", foreground=P["muted"])
        self.dtc_detail.insert(
            "1.0", "Select a code above to see severity, whether it's safe "
            "to drive, common causes on this car, and what to check first.")
        self.dtc_detail.config(state="disabled")
        self.watch_btn = ttk.Button(det, text="Watch related\nsensors →",
                                    command=self._watch_related,
                                    state="disabled")
        self.watch_btn.pack(side="right", padx=8, pady=8)

    # ---- Live data tab ----

    def _build_live_tab(self):
        tab = self._tab("live")
        cards = tk.Frame(tab, bg=P["card"])
        cards.pack(fill="x", pady=(0, 10))
        self._cards = {}
        for pid, label, unit in ((0x0C, "ENGINE", "rpm"),
                                 (0x0D, "SPEED", "mph"),
                                 (0x05, "COOLANT", "°F"),
                                 (0x11, "THROTTLE", "%")):
            card = tk.Frame(cards, bg=P["panel2"], padx=18, pady=10)
            card.pack(side="left", padx=(0, 10), fill="x", expand=True)
            tk.Label(card, text=label, bg=P["panel2"], fg=P["muted"],
                     font=("Segoe UI Semibold", 8)).pack(anchor="w")
            val = tk.Label(card, text="—", bg=P["panel2"], fg=P["fg"],
                           font=self.F_BIG)
            val.pack(anchor="w")
            tk.Label(card, text=unit, bg=P["panel2"], fg=P["muted"],
                     font=self.F_SM).pack(anchor="w")
            self._cards[pid] = val

        btns = self._toolbar(tab)
        self.live_btn = ttk.Button(btns, text="▶  Start",
                                   style="Accent.TButton",
                                   command=self._toggle_live)
        self.live_btn.pack(side="left")
        ttk.Button(btns, text="Select PIDs…",
                   command=self._select_pids).pack(side="left", padx=6)
        ttk.Button(btns, text="Reset Stats",
                   command=self._reset_stats).pack(side="left")
        self.record_var = tk.BooleanVar(value=False)
        tk.Checkbutton(btns, text="Log session to CSV",
                       variable=self.record_var, bg=P["card"], fg=P["fg"],
                       activebackground=P["card"], activeforeground=P["fg"],
                       selectcolor=P["panel"],
                       font=self.F).pack(side="left", padx=10)
        self.rate_var = tk.StringVar(value="")
        tk.Label(btns, textvariable=self.rate_var, bg=P["card"],
                 fg=P["muted"], font=self.F_SM).pack(side="right")

        # event marking row (visible while logging)
        ev = tk.Frame(tab, bg=P["card"])
        ev.pack(fill="x", pady=(0, 6))
        tk.Label(ev, text="Mark event:", bg=P["card"], fg=P["muted"],
                 font=self.F_SM).pack(side="left")
        self.event_var = tk.StringVar()
        self.event_combo = ttk.Combobox(ev, textvariable=self.event_var,
                                        values=EVENT_PRESETS, width=24)
        self.event_combo.pack(side="left", padx=6)
        ttk.Button(ev, text="⚑ Mark",
                   command=self._mark_event).pack(side="left")
        tk.Label(ev, text="   Note:", bg=P["card"], fg=P["muted"],
                 font=self.F_SM).pack(side="left")
        self.note_entry = ttk.Entry(ev, width=40)
        self.note_entry.pack(side="left", padx=6, fill="x", expand=True)
        ttk.Button(ev, text="Add note",
                   command=self._add_note).pack(side="left")

        frame, self.live_tree = self._make_tree(
            tab, ("Parameter", "Value", "Unit", "Min", "Max", "Avg"),
            (300, 150, 80, 90, 90, 90))
        frame.pack(fill="both", expand=True)

    # ---- Charts tab ----

    def _build_charts_tab(self):
        tab = self._tab("charts")
        btns = self._toolbar(tab)
        ttk.Button(btns, text="Chart Live PIDs", style="Accent.TButton",
                   command=self._chart_live).pack(side="left")
        tk.Label(btns, text="Window:", bg=P["card"], fg=P["muted"],
                 font=self.F_SM).pack(side="left", padx=(10, 2))
        self.chart_win = ttk.Combobox(btns, values=["30", "60", "120",
                                                    "300"],
                                      width=5, state="readonly")
        self.chart_win.set("60")
        self.chart_win.pack(side="left")
        self.chart_win.bind("<<ComboboxSelected>>", self._chart_window)
        self.pause_var = tk.BooleanVar(value=False)
        tk.Checkbutton(btns, text="Pause", variable=self.pause_var,
                       command=self._chart_pause, bg=P["card"], fg=P["fg"],
                       activebackground=P["card"],
                       selectcolor=P["panel"]).pack(side="left", padx=8)
        ttk.Button(btns, text="Load Log…",
                   command=lambda: self._load_log("A")).pack(side="left",
                                                             padx=(16, 2))
        ttk.Button(btns, text="Overlay 2nd Log…",
                   command=lambda: self._load_log("B")).pack(side="left")
        self.play_btn = ttk.Button(btns, text="▶ Play",
                                   command=self._toggle_play)
        self.play_btn.pack(side="left", padx=(16, 2))
        ttk.Button(btns, text="🔍+", width=4,
                   command=lambda: self.chart.zoom(0.7)).pack(side="left")
        ttk.Button(btns, text="🔍−", width=4,
                   command=lambda: self.chart.zoom(1.4)).pack(side="left")
        ttk.Button(btns, text="Reset",
                   command=self.chart_reset).pack(side="left", padx=2)
        ttk.Button(btns, text="Show All",
                   command=lambda: self.chart.show_all()
                   ).pack(side="left", padx=(16, 0))

        self.chart = StripChart(tab, P)
        self.chart.pack(fill="both", expand=True)
        tk.Label(tab, text="Click a legend entry to hide/show that line "
                           "(hidden ones stay listed, dimmed). Live mode: "
                           "pick PIDs in Live Data, press Start, then "
                           "'Chart Live PIDs'. Loaded logs: drag to pan, "
                           "mouse-wheel to zoom, ▶ to replay.",
                 bg=P["card"], fg=P["muted"], font=self.F_SM,
                 anchor="w").pack(fill="x", pady=(6, 0))

    # ---- Guided diagnostics tab ----

    def _build_guided_tab(self):
        tab = self._tab("guided")
        left = tk.Frame(tab, bg=P["card"])
        left.pack(side="left", fill="y", padx=(0, 10))
        tk.Label(left, text="What's the symptom?", bg=P["card"],
                 fg=P["fg"], font=self.F_B).pack(anchor="w", pady=(0, 6))
        self.preset_list = tk.Listbox(
            left, width=32, height=18, bg=P["panel"], fg=P["fg"],
            selectbackground=P["sel"], selectforeground=P["fg"],
            relief="flat", font=self.F, exportselection=False,
            highlightthickness=0)
        self.preset_list.pack(fill="y", expand=True)
        for name in PRESETS:
            self.preset_list.insert("end", f"  {name}")
        self.preset_list.bind("<<ListboxSelect>>", self._show_preset)

        right = tk.Frame(tab, bg=P["card"])
        right.pack(side="left", fill="both", expand=True)
        self.guided_text = tk.Text(right, wrap="word", bg=P["panel"],
                                   fg=P["fg"], relief="flat", font=self.F,
                                   padx=12, pady=10, cursor="arrow")
        self.guided_text.pack(fill="both", expand=True)
        self.guided_text.tag_configure("h", font=("Segoe UI", 13, "bold"))
        self.guided_text.tag_configure("m", foreground=P["muted"])
        self.guided_text.tag_configure("ok", foreground=P["green"])
        self.guided_text.tag_configure("bad", foreground="#ff5252")
        self.guided_text.insert(
            "1.0", "Pick a symptom on the left.\n\nEach preset explains "
            "what to look for, then watches the right sensors and flags "
            "abnormal readings automatically.")
        self.guided_text.config(state="disabled")
        self.preset_btn = ttk.Button(right, text="Start Watching →",
                                     style="Accent.TButton",
                                     command=self._start_preset,
                                     state="disabled")
        self.preset_btn.pack(anchor="e", pady=(8, 0))

    # ---- Reports tab ----

    def _build_reports_tab(self):
        tab = self._tab("reports")
        tk.Label(tab, text="One-click reports", bg=P["card"], fg=P["fg"],
                 font=self.F_B).pack(anchor="w")
        tk.Label(tab, text="Each report reads the codes, freeze frame and "
                           "readiness monitors fresh from the car, then "
                           "opens a clean printable page in your browser "
                           "(Ctrl+P → 'Save as PDF' makes a PDF). Files "
                           "are also saved to your save folder.",
                 bg=P["card"], fg=P["muted"], font=self.F_SM,
                 wraplength=720, justify="left").pack(anchor="w",
                                                      pady=(2, 12))

        grid = tk.Frame(tab, bg=P["card"])
        grid.pack(anchor="w")
        defs = [
            ("Check-Engine Report", "Codes with explanations, freeze frame "
             "and live snapshot — the full picture.", "check"),
            ("Pre-Smog Report", "Readiness verdict: would the car pass the "
             "OBD part of a smog check today?", "presmog"),
            ("Mechanic Report", "Everything, tersely — built for handing "
             "to a professional.", "mechanic"),
            ("Share with Mechanic", "A friendly summary without the "
             "overwhelming raw data; codes are also copied to the "
             "clipboard.", "share"),
        ]
        for i, (name, blurb, kind) in enumerate(defs):
            cell = tk.Frame(grid, bg=P["panel2"], padx=14, pady=12)
            cell.grid(row=i // 2, column=i % 2, padx=(0, 10), pady=(0, 10),
                      sticky="nsew")
            grid.columnconfigure(i % 2, weight=1)
            tk.Label(cell, text=name, bg=P["panel2"], fg=P["fg"],
                     font=self.F_B).pack(anchor="w")
            tk.Label(cell, text=blurb, bg=P["panel2"], fg=P["muted"],
                     font=self.F_SM, wraplength=330,
                     justify="left").pack(anchor="w", pady=(2, 8))
            ttk.Button(cell, text="Generate",
                       command=lambda k=kind: self._make_report(k)
                       ).pack(anchor="w")

        ba = tk.Frame(tab, bg=P["panel2"], padx=14, pady=12)
        ba.pack(fill="x", pady=(4, 0))
        tk.Label(ba, text="Before / After repair", bg=P["panel2"],
                 fg=P["fg"], font=self.F_B).pack(anchor="w")
        tk.Label(ba, text="Save a baseline before you wrench, then compare "
                          "after the repair to prove what got fixed.",
                 bg=P["panel2"], fg=P["muted"],
                 font=self.F_SM).pack(anchor="w", pady=(2, 8))
        row = tk.Frame(ba, bg=P["panel2"])
        row.pack(anchor="w")
        ttk.Button(row, text="1. Save Baseline (before repair)",
                   command=self._save_baseline).pack(side="left")
        ttk.Button(row, text="2. Before/After Report",
                   command=lambda: self._make_report("beforeafter")
                   ).pack(side="left", padx=8)

    # ---- Advanced tabs ----

    def _build_freeze_tab(self):
        tab = self._tab("freeze")
        btns = self._toolbar(tab)
        ttk.Button(btns, text="Read Freeze Frame", style="Accent.TButton",
                   command=lambda: self._run_bg(self._read_freeze,
                                                "Reading freeze frame…")
                   ).pack(side="left")
        self._hint(btns, "Snapshot of sensor values at the moment the code "
                         "that lit the check-engine light was set.")
        frame, self.ff_tree = self._make_tree(
            tab, ("Parameter", "Value", "Unit"), (350, 260, 120))
        frame.pack(fill="both", expand=True)

    def _build_readiness_tab(self):
        tab = self._tab("ready")
        btns = self._toolbar(tab)
        ttk.Button(btns, text="Check Readiness", style="Accent.TButton",
                   command=lambda: self._run_bg(self._read_readiness,
                                                "Reading monitor status…")
                   ).pack(side="left")
        self._hint(btns, "Smog-check readiness. Monitors reset every time "
                         "codes are cleared or the battery is disconnected.")
        frame, self.ready_tree = self._make_tree(
            tab, ("Monitor", "Supported", "Status"), (330, 140, 240))
        frame.pack(fill="both", expand=True)

    def _build_o2_tab(self):
        tab = self._tab("o2")
        btns = self._toolbar(tab)
        ttk.Button(btns, text="Read O2 Test Results", style="Accent.TButton",
                   command=lambda: self._run_bg(self._read_o2_tests,
                                                "Reading Mode 05 results…")
                   ).pack(side="left")
        self._hint(btns, "On-board O2 sensor monitoring results (Mode 05). "
                         "Not all ECUs support every test.")
        frame, self.o2_tree = self._make_tree(
            tab, ("Sensor", "Test", "Result"), (150, 400, 230))
        frame.pack(fill="both", expand=True)

    def _build_info_tab(self):
        tab = self._tab("info")
        btns = self._toolbar(tab)
        ttk.Button(btns, text="Read Vehicle Info", style="Accent.TButton",
                   command=lambda: self._run_bg(self._read_info,
                                                "Reading vehicle info…")
                   ).pack(side="left")
        self.info_text = tk.Text(tab, wrap="word", font=("Consolas", 10),
                                 bg=P["panel"], fg=P["fg"],
                                 insertbackground=P["fg"], relief="flat",
                                 padx=10, pady=8)
        self.info_text.pack(fill="both", expand=True)

    def _build_terminal_tab(self):
        tab = self._tab("term")
        tk.Label(tab, text="Raw adapter access — AT commands (ATRV = "
                           "battery voltage) or OBD requests (010C = RPM). "
                           "↑/↓ recall command history.",
                 bg=P["card"], fg=P["muted"], font=self.F_SM,
                 anchor="w").pack(fill="x")
        self.term_out = tk.Text(tab, wrap="none", font=("Consolas", 9),
                                bg=P["termbg"], fg=P["termfg"], height=20,
                                relief="flat", padx=8, pady=6,
                                insertbackground=P["fg"])
        self.term_out.pack(fill="both", expand=True, pady=6)
        entry_row = tk.Frame(tab, bg=P["card"])
        entry_row.pack(fill="x")
        self.term_entry = ttk.Entry(entry_row, font=("Consolas", 10))
        self.term_entry.pack(side="left", fill="x", expand=True)
        self.term_entry.bind("<Return>", self._term_send)
        self.term_entry.bind("<Up>", self._term_hist_up)
        self.term_entry.bind("<Down>", self._term_hist_down)
        ttk.Button(entry_row, text="Send",
                   command=self._term_send).pack(side="left", padx=6)

    # ------------------------------------------------------------------
    # Dialogs
    # ------------------------------------------------------------------

    def _modal(self, title, w=560, h=460):
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry(f"{w}x{h}")
        win.configure(bg=P["bg"])
        win.transient(self)
        return win

    def _welcome(self):
        self.prefs["first_run_done"] = True
        save_prefs(self.prefs)
        win = self._modal("Welcome to CivicDiag", 600, 480)
        t = tk.Text(win, wrap="word", bg=P["bg"], fg=P["fg"], relief="flat",
                    font=self.F, padx=16, pady=12, cursor="arrow")
        t.pack(fill="both", expand=True)
        t.tag_configure("h", font=("Segoe UI", 14, "bold"))
        t.tag_configure("b", font=self.F_B)
        t.tag_configure("m", foreground=P["muted"])
        t.insert("end", "How to connect to your Civic\n\n", "h")
        t.insert("end", "1.  Plug the ELM327 USB adapter into the car's "
                        "OBD port — it's under the dash on the DRIVER'S "
                        "side, above the pedals.\n\n")
        t.insert("end", "2.  Plug the USB end into this laptop.\n\n")
        t.insert("end", "3.  Turn the ignition to ON (position II). The "
                        "engine can be off or running.\n\n")
        t.insert("end", "4.  Pick the COM port at the top — ports that "
                        "look like an adapter are marked ✱ likely "
                        "adapter.\n\n")
        t.insert("end", "5.  Hit Connect. The first handshake takes about "
                        "10 seconds — your '99 uses a slow ISO 9141 "
                        "protocol. That's normal.\n\n")
        t.insert("end", "No adapter yet? ", "b")
        t.insert("end", "Choose DEMO in the port list to explore every "
                        "feature with a simulated Civic (it even has a "
                        "stored EVAP code to play with).\n\n")
        t.insert("end", "New to car diagnostics? Start with the Guided "
                        "Diagnostics tab — pick a symptom and the app "
                        "watches the right sensors for you.", "m")
        t.config(state="disabled")
        row = tk.Frame(win, bg=P["bg"])
        row.pack(pady=10)
        ttk.Button(row, text="Try Demo Mode", style="Accent.TButton",
                   command=lambda: (win.destroy(), self._connect_demo())
                   ).pack(side="left", padx=6)
        ttk.Button(row, text="Get Started",
                   command=win.destroy).pack(side="left", padx=6)

    def _troubleshoot(self):
        win = self._modal("Connection troubleshooting", 620, 500)
        t = tk.Text(win, wrap="word", bg=P["bg"], fg=P["fg"], relief="flat",
                    font=self.F_SM, padx=16, pady=12, cursor="arrow")
        t.pack(fill="both", expand=True)
        t.tag_configure("b", font=self.F_B)
        items = [
            ("No COM ports listed",
             "Windows hasn't loaded a driver for the adapter. Most cables "
             "use a CH340, CP2102 or FTDI chip — search the chip name + "
             "'driver', install, replug, then Rescan. Device Manager shows "
             "the adapter under 'Ports (COM & LPT)' when it's working."),
            ("Adapter found, but 'car did not respond'",
             "Ignition must be ON (position II) — dash lights lit. Push "
             "the adapter firmly into the OBD socket; worn sockets are "
             "common on 25-year-old cars. Then try again — ISO 9141's "
             "slow init sometimes needs a second attempt."),
            ("Connects, then drops / garbage data",
             "Usually a counterfeit ELM327 ('v2.1' clones are the worst "
             "offenders — many have broken ISO 9141 support and won't "
             "talk to pre-2003 cars). The OBDLink SX USB is the reliable "
             "choice for this Civic."),
            ("Wrong COM port",
             "Unplug the adapter, Rescan, note which port disappears, "
             "replug — that's your port. Ports marked '✱ likely adapter' "
             "matched a known USB-serial chip."),
            ("Everything checks out, still nothing",
             "Check the car's cigarette-lighter fuse — on Hondas it often "
             "feeds OBD-port power. No power = adapter LEDs stay dark."),
        ]
        for head, body in items:
            t.insert("end", f"• {head}\n", "b")
            t.insert("end", f"   {body}\n\n")
        t.config(state="disabled")
        row = tk.Frame(win, bg=P["bg"])
        row.pack(pady=10)
        ttk.Button(row, text="Open Device Manager",
                   command=lambda: os.startfile("devmgmt.msc")
                   ).pack(side="left", padx=6)
        ttk.Button(row, text="Try Demo Mode",
                   command=lambda: (win.destroy(), self._connect_demo())
                   ).pack(side="left", padx=6)
        ttk.Button(row, text="Close", command=win.destroy).pack(side="left",
                                                                padx=6)

    def _about(self):
        messagebox.showinfo(
            "About CivicDiag",
            f"CivicDiag v{VERSION}\n"
            "OBD-II diagnostics for the 1999 Honda Civic\n\n"
            f"Preferences: {os.path.dirname(__file__)}\n"
            f"Save folder: {ensure_save_folder(self.prefs)}\n\n"
            "Engine/transmission data via OBD-II (ISO 9141-2).\n"
            "ABS/SRS on this car use blink codes — see README.")

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _refresh_ports(self):
        ports = find_ports()
        values = []
        for dev, desc in sorted(
                ports, key=lambda p: not LIKELY_ADAPTER.search(p[1] or "")):
            star = " ✱ likely adapter" if LIKELY_ADAPTER.search(desc or "") \
                else ""
            values.append(f"{dev} — {desc}{star}")
        values.append(f"{DEMO_PORT} — Simulated 1999 Civic (no car needed)")
        self.port_combo["values"] = values
        if not self.port_var.get() or self.port_var.get() not in values:
            self.port_var.set(values[0])

    def _connect_demo(self):
        self.port_var.set(
            f"{DEMO_PORT} — Simulated 1999 Civic (no car needed)")
        if not (self.elm and self.elm.connected):
            self._toggle_connect()

    def _toggle_connect(self):
        if self.elm and self.elm.connected:
            self._stop_live()
            self.elm.close()
            self.connect_btn.config(text="Connect")
            self.proto_var.set("Not connected")
            self.mil_label.config(bg="#3a4048")
            self._set_status("Disconnected.")
            return

        sel = self.port_var.get()
        if not sel:
            messagebox.showwarning("No port", "Select a COM port first.")
            return
        port = sel.split(" — ")[0]
        self.prefs["last_port"] = sel
        save_prefs(self.prefs)
        self.connect_btn.config(state="disabled")
        if port == DEMO_PORT:
            self.elm = DemoELM327(log_fn=self._log_traffic)
            self._set_status("Starting demo mode…")
        else:
            self.elm = ELM327(log_fn=self._log_traffic)
            self._set_status(f"Connecting on {port}… (ISO 9141 init can "
                             "take ~10 s)")

        def job():
            try:
                self.elm.connect(port)
                self._discover_pids()
                self.ui(self._on_connected)
            except ELM327Error as e:
                self.ui(messagebox.showerror, "Connection failed", str(e))
                self.ui(self._set_status,
                        "Connection failed — see Help → Connection "
                        "troubleshooting.")
                self.ui(self._troubleshoot)
            finally:
                self.ui(lambda: self.connect_btn.config(state="normal"))

        threading.Thread(target=job, daemon=True).start()

    def _discover_pids(self):
        self.supported_pids = set()
        base = 0x00
        while base <= 0x40:
            try:
                data = self.elm.query_pid(0x01, base)
            except (NoDataError, ELM327Error):
                break
            chunk = od.decode_supported_pids(base, data)
            self.supported_pids |= chunk
            if (base + 0x20) not in chunk:
                break
            base += 0x20
        self.supported_pids.add(od.PID_BATT)  # adapter-provided, always on

    def _on_connected(self):
        self.connect_btn.config(text="Disconnect")
        self.proto_var.set(
            f"{self.elm.protocol_name}  ·  {self.elm.elm_version}")
        n = len(self.supported_pids - {od.PID_BATT})
        self._set_status(f"Connected — vehicle reports {n} supported PIDs. "
                         "Read codes or start live data.")
        self.live_pids = [p for p in self.live_pids
                          if p in self.supported_pids] or \
            sorted(p for p in self.supported_pids if p in od.PIDS)
        self._run_bg(self._read_readiness)

    # ------------------------------------------------------------------
    # Trouble codes
    # ------------------------------------------------------------------

    def _read_dtcs(self):
        mil, count = False, 0
        try:
            status = od.decode_monitor_status(self.elm.query_pid(0x01, 0x01))
            mil, count = status["mil"], status["dtc_count"]
        except (NoDataError, ELM327Error):
            pass

        codes = []
        for mode, label in ((0x03, "STORED"), (0x07, "PENDING")):
            try:
                frames = self.elm.query(f"{mode:02X}")
                for code in od.decode_dtc_frames(frames):
                    info = od.dtc_info(code)
                    info["kind"] = label
                    codes.append(info)
            except (NoDataError, ELM327Error):
                continue
        self.session["codes"] = codes
        self.session["timestamp"] = datetime.now().isoformat(
            timespec="seconds")

        def update():
            self.dtc_tree.delete(*self.dtc_tree.get_children())
            sev_tags = {}
            for c in codes:
                iid = self.dtc_tree.insert(
                    "", "end", values=(c["kind"], c["code"],
                                       c["severity_name"], c["desc"]))
                sev_tags[iid] = f"sev{c['severity']}"
            if not codes:
                self.dtc_tree.insert("", "end",
                                     values=("—", "—", "",
                                             "No trouble codes. ✔"))
            self._restripe(self.dtc_tree, sev_tags)
            self.mil_label.config(bg=P["accent"] if mil else P["green"])
            stored = sum(1 for c in codes if c["kind"] == "STORED")
            pending = sum(1 for c in codes if c["kind"] == "PENDING")
            self.dtc_summary.set(
                f"MIL {'ON' if mil else 'off'} — {stored} stored, "
                f"{pending} pending (ECU reports {count}).")
            self._set_status("Trouble code read complete. Select a code "
                             "for details.")
        self.ui(update)

    def _on_dtc_select(self, _e=None):
        sel = self.dtc_tree.selection()
        self._selected_info = None
        if not sel:
            return
        vals = self.dtc_tree.item(sel[0], "values")
        if len(vals) < 2 or not vals[1] or vals[1] == "—":
            return
        info = next((c for c in self.session["codes"]
                     if c["code"] == vals[1]), od.dtc_info(vals[1]))
        self._selected_info = info
        t = self.dtc_detail
        t.config(state="normal")
        t.delete("1.0", "end")
        t.insert("end", f"{info['code']} — {info['desc']}\n", "h")
        t.insert("end", f"Severity: {info['severity_name']}    ")
        t.insert("end", f"Safe to drive?  {info['drive']}\n\n")
        if info["causes"]:
            t.insert("end", "Common causes on this car:  ", "h")
            t.insert("end", " · ".join(info["causes"]) + "\n")
        if info["check"]:
            t.insert("end", "Check this first:  ", "h")
            t.insert("end", " · ".join(info["check"]) + "\n")
        t.config(state="disabled")
        pids = [p for p in info["pids"] if p in self.supported_pids]
        self.watch_btn.config(state="normal" if pids else "disabled")

    def _watch_related(self):
        info = getattr(self, "_selected_info", None)
        if not info:
            return
        pids = [p for p in info["pids"] if p in self.supported_pids]
        if not pids:
            return
        self._stop_live()
        self.live_pids = pids
        self._reset_stats()
        self.nb.select(self.tab_frames["live"])
        self._set_status(f"Watching sensors related to {info['code']} — "
                         "press Start.")
        self._start_live()

    def _copy_codes(self):
        text = reports.codes_to_clipboard_text(self.session)
        self.clipboard_clear()
        self.clipboard_append(text)
        self._set_status("Codes copied to clipboard.")

    def _clear_dtcs_confirm(self):
        if not (self.elm and self.elm.connected):
            messagebox.showwarning("Not connected", "Connect first.")
            return
        win = self._modal("Clear codes — are you sure?", 560, 420)
        t = tk.Text(win, wrap="word", bg=P["bg"], fg=P["fg"], relief="flat",
                    font=self.F_SM, padx=16, pady=12, cursor="arrow")
        t.pack(fill="both", expand=True)
        t.tag_configure("b", font=self.F_B)
        t.tag_configure("warn", foreground="#ff8c42", font=self.F_B)
        t.insert("end", "Clearing codes erases evidence.\n\n", "warn")
        t.insert("end", "This will permanently erase:\n", "b")
        t.insert("end", " • all stored and pending trouble codes\n"
                        " • the freeze frame (conditions when the fault "
                        "happened)\n"
                        " • all readiness monitors — the car will need "
                        "several days of mixed driving before it can pass "
                        "a smog check\n\n")
        codes = self.session.get("codes", [])
        if codes:
            t.insert("end", "Codes currently on record:\n", "b")
            for c in codes:
                t.insert("end", f" • {c['code']} ({c['kind'].lower()}) — "
                                f"{c['desc']}\n")
        else:
            t.insert("end", "Tip: read the codes first so you have a "
                            "record of them.\n", "b")
        t.config(state="disabled")

        ack = tk.BooleanVar(value=False)
        row = tk.Frame(win, bg=P["bg"])
        row.pack(pady=8)
        tk.Checkbutton(row, text="I've saved or noted the codes and freeze "
                                 "frame", variable=ack, bg=P["bg"],
                       fg=P["fg"], activebackground=P["bg"],
                       selectcolor=P["panel"], font=self.F_SM,
                       command=lambda: clear_btn.config(
                           state="normal" if ack.get() else "disabled")
                       ).pack(side="left")
        row2 = tk.Frame(win, bg=P["bg"])
        row2.pack(pady=(0, 10))
        ttk.Button(row2, text="Save report first",
                   command=lambda: self._make_report("check")
                   ).pack(side="left", padx=4)
        clear_btn = ttk.Button(
            row2, text="Clear codes now", state="disabled",
            command=lambda: (win.destroy(), self._do_clear()))
        clear_btn.pack(side="left", padx=4)
        ttk.Button(row2, text="Cancel",
                   command=win.destroy).pack(side="left", padx=4)

    def _do_clear(self):
        def job():
            self.elm.query("04", timeout=10.0)
            self.ui(self._set_status, "Codes cleared. MIL should be off — "
                                      "readiness monitors are now reset.")
            self._read_dtcs()
        self._run_bg(job, "Clearing codes…")

    # ------------------------------------------------------------------
    # Live data
    # ------------------------------------------------------------------

    def _selectable_pids(self):
        pids = sorted(p for p in self.supported_pids if p in od.PIDS)
        pids.append(od.PID_BATT)
        return pids

    def _select_pids(self):
        if not self.supported_pids:
            messagebox.showwarning("Not connected",
                                   "Connect to the car (or DEMO) first.")
            return
        win = self._modal("Select live parameters", 460, 600)
        tk.Label(win, text="Fewer parameters = faster refresh (ISO 9141 "
                           "manages ~5-8 readings/sec total).",
                 bg=P["bg"], fg=P["muted"], font=self.F_SM, wraplength=420,
                 justify="left", padx=10, pady=6).pack(anchor="w")
        srow = tk.Frame(win, bg=P["bg"])
        srow.pack(fill="x", padx=10)
        tk.Label(srow, text="Search:", bg=P["bg"], fg=P["muted"],
                 font=self.F_SM).pack(side="left")
        search_var = tk.StringVar()
        ttk.Entry(srow, textvariable=search_var).pack(side="left", padx=6,
                                                      fill="x", expand=True)
        list_frame = tk.Frame(win, bg=P["bg"])
        list_frame.pack(fill="both", expand=True, padx=10, pady=6)

        vars_ = {}
        boxes = {}

        def populate(*_):
            q = search_var.get().lower()
            for pid, cb in boxes.items():
                name = od.pid_def(pid)[0].lower()
                cb.pack_forget()
                if not q or q in name:
                    cb.pack(anchor="w")

        for pid in self._selectable_pids():
            name, unit, _, _ = od.pid_def(pid)
            v = tk.BooleanVar(value=pid in self.live_pids)
            vars_[pid] = v
            fav = " ★" if pid in self.prefs.get("favorites", []) else ""
            cb = tk.Checkbutton(
                list_frame, text=f"{name}{fav}", variable=v, bg=P["bg"],
                fg=P["fg"], activebackground=P["bg"],
                activeforeground=P["fg"], selectcolor=P["panel"],
                font=self.F)
            boxes[pid] = cb
            cb.pack(anchor="w")
        search_var.trace_add("write", populate)

        def chosen():
            return [p for p, v in vars_.items() if v.get()]

        row = tk.Frame(win, bg=P["bg"])
        row.pack(pady=8)
        ttk.Button(row, text="★ Save as favorites",
                   command=lambda: (self.prefs.update(
                       favorites=chosen()), save_prefs(self.prefs),
                       self._set_status("Favorites saved."))
                   ).pack(side="left", padx=4)
        ttk.Button(row, text="★ Load favorites",
                   command=lambda: [vars_[p].set(
                       p in self.prefs.get("favorites", []))
                       for p in vars_]).pack(side="left", padx=4)

        def apply():
            sel = chosen()
            if sel:
                self.live_pids = sel
                self.prefs["live_pids"] = sel
                save_prefs(self.prefs)
                self._reset_stats()
            win.destroy()
        ttk.Button(row, text="Apply", style="Accent.TButton",
                   command=apply).pack(side="left", padx=4)

    def _reset_stats(self):
        self.stats = {}
        self.active_alerts = dict(self.active_alerts)  # keep preset alerts

    def _toggle_live(self):
        if self.live_running:
            self._stop_live()
        else:
            self._start_live()

    def _start_live(self):
        if not (self.elm and self.elm.connected):
            messagebox.showwarning("Not connected", "Connect first.")
            return
        if not self.live_pids:
            messagebox.showwarning("No PIDs", "Select parameters first.")
            return
        if self.record_var.get():
            folder = ensure_save_folder(self.prefs)
            self.csv_path = os.path.join(
                folder, reports.auto_name(self.session, "csv"))
            try:
                self.csv_file = open(self.csv_path, "w", newline="",
                                     encoding="utf-8")
            except OSError as e:
                messagebox.showerror("Can't write log", str(e))
                self.record_var.set(False)
                self.csv_file = None
            if self.csv_file:
                self.csv_writer = csv.writer(self.csv_file)
                self.csv_writer.writerow(
                    ["timestamp", "event"]
                    + [od.pid_def(p)[0] for p in self.live_pids])
                self.log_started = time.monotonic()
                self._set_status(f"Logging to {self.csv_path}")

        self.live_tree.delete(*self.live_tree.get_children())
        self._live_items = {}
        for i, pid in enumerate(self.live_pids):
            name, unit, _, _ = od.pid_def(pid)
            iid = self.live_tree.insert(
                "", "end", values=(name, "—", unit, "", "", ""),
                tags=("odd" if i % 2 else "even",))
            self._live_items[pid] = iid

        self.live_running = True
        self.live_btn.config(text="⏸  Stop")
        threading.Thread(target=self._live_loop, daemon=True).start()

    def _stop_live(self):
        self.live_running = False
        try:
            self.live_btn.config(text="▶  Start")
        except tk.TclError:
            pass
        if self.csv_file:
            try:
                self.csv_file.close()
            except OSError:
                pass
            if self.log_started:
                self.session["duration"] = round(
                    time.monotonic() - self.log_started, 1)
            # JSON sidecar with stats + events for the session
            try:
                import json
                side = self.csv_path.replace(".csv", "_summary.json")
                with open(side, "w", encoding="utf-8") as f:
                    json.dump({
                        "log": os.path.basename(self.csv_path),
                        "duration_sec": self.session.get("duration"),
                        "adapter": getattr(self.elm, "elm_version", ""),
                        "protocol": getattr(self.elm, "protocol_name", ""),
                        "events": self.session["events"],
                        "stats": {od.pid_def(p)[0]:
                                  dict(min=s[0], max=s[1],
                                       avg=round(s[2] / s[3], 2))
                                  for p, s in self.stats.items() if s[3]},
                    }, f, indent=2)
            except OSError:
                pass
            self.csv_file = self.csv_writer = None
            self._set_status(f"Log saved: {self.csv_path}")

    def _query_live(self, pid):
        if pid == od.PID_BATT:
            lines = self.elm.command("ATRV", timeout=2.0)
            v = numeric(lines[0]) if lines else None
            if v is None:
                raise NoDataError("ATRV")
            return v
        name, unit, nbytes, decode = od.pid_def(pid)
        data = self.elm.query_pid(0x01, pid, timeout=4.0)
        return decode(data[:nbytes] if nbytes else data)

    def _live_loop(self):
        cycle_times = []
        while self.live_running and self.elm and self.elm.connected:
            t0 = time.monotonic()
            row_vals = []
            for pid in list(self.live_pids):
                if not self.live_running:
                    break
                try:
                    value = self._query_live(pid)
                except NoDataError:
                    value = "n/a"
                except ELM327Error as e:
                    self.ui(self._set_status, f"Live data stopped: {e}")
                    self.ui(self._stop_live)
                    return
                row_vals.append(value)
                self.latest[pid] = value

                num = numeric(value)
                mn = mx = avg = ""
                if num is not None:
                    st = self.stats.setdefault(pid, [num, num, 0.0, 0])
                    st[0] = min(st[0], num)
                    st[1] = max(st[1], num)
                    st[2] += num
                    st[3] += 1
                    mn, mx = fmt(st[0]), fmt(st[1])
                    avg = fmt(st[2] / st[3])
                self.ui(self._update_live_row, pid, value, mn, mx, avg, num)
                time.sleep(POLL_GAP)

            if self.csv_writer and row_vals:
                with self._event_lock:
                    evs = "; ".join(self._pending_events)
                    self._pending_events = []
                try:
                    self.csv_writer.writerow(
                        [datetime.now().isoformat(timespec="milliseconds"),
                         evs] + [str(v) for v in row_vals])
                except (ValueError, OSError):
                    pass

            dt = time.monotonic() - t0
            cycle_times = (cycle_times + [dt])[-5:]
            avg_t = sum(cycle_times) / len(cycle_times)
            if avg_t > 0:
                self.ui(self.rate_var.set,
                        f"{len(self.live_pids) / avg_t:.1f} readings/sec · "
                        f"refresh every {avg_t:.1f}s")

    def _update_live_row(self, pid, value, mn, mx, avg, num):
        iid = getattr(self, "_live_items", {}).get(pid)
        name, unit, _, _ = od.pid_def(pid)
        alert = self.active_alerts.get(pid)
        bad = False
        if alert and num is not None:
            lo, hi, msg = alert
            bad = (lo is not None and num < lo) or \
                  (hi is not None and num > hi)
            if bad and pid not in self._alerting:
                self._alerting.add(pid)
                self._set_status(f"⚠ {msg} ({name}: {fmt(num)} {unit})")
            elif not bad:
                self._alerting.discard(pid)
        if iid:
            try:
                base = self.live_tree.item(iid, "tags")
                stripe = [t for t in base if t in ("odd", "even")]
                tags = tuple(stripe + (["alert"] if bad else []))
                self.live_tree.item(iid, values=(name, value, unit, mn, mx,
                                                 avg), tags=tags)
            except tk.TclError:
                pass
        card = self._cards.get(pid)
        if card and num is not None:
            if pid == 0x0D:
                card.config(text=f"{num * 0.621371:.0f}")
            elif pid == 0x05:
                card.config(text=f"{num * 9 / 5 + 32:.0f}")
            else:
                card.config(text=f"{num:.0f}")
        # feed the live chart
        if num is not None and self.chart.mode == "live":
            self.chart.add_point(pid, time.monotonic(), num)

    def _mark_event(self):
        text = self.event_var.get().strip() or "Event"
        ts = datetime.now().isoformat(timespec="seconds")
        self.session["events"].append((ts, text))
        with self._event_lock:
            self._pending_events.append(text)
        self._set_status(f"⚑ Marked: {text}")
        self.event_var.set("")

    def _add_note(self):
        text = self.note_entry.get().strip()
        if not text:
            return
        self.session["notes"] = (self.session["notes"] + "\n" + text).strip()
        ts = datetime.now().isoformat(timespec="seconds")
        self.session["events"].append((ts, f"NOTE: {text}"))
        with self._event_lock:
            self._pending_events.append(f"NOTE: {text}")
        self.note_entry.delete(0, "end")
        self._set_status("Note added to session.")

    # ------------------------------------------------------------------
    # Charts
    # ------------------------------------------------------------------

    def _chart_live(self):
        self._stop_play()
        self.chart.clear()
        self.chart.set_live(float(self.chart_win.get()))
        for i, pid in enumerate(self.live_pids[:8]):
            name, unit, _, _ = od.pid_def(pid)
            alert = self.active_alerts.get(pid)
            self.chart.add_series(
                pid, f"{name} ({unit})" if unit else name,
                CHART_COLORS[i % len(CHART_COLORS)],
                alert=(alert[0], alert[1]) if alert else None)
        if not self.live_running:
            self._set_status("Chart armed — press Start in Live Data to "
                             "feed it.")

    def _chart_window(self, _e=None):
        self.chart.set_live(float(self.chart_win.get()))

    def _chart_pause(self):
        self.chart.paused = self.pause_var.get()

    def chart_reset(self):
        if self.chart.mode == "static":
            self.chart.reset_view()
        else:
            self._chart_live()

    def _load_log(self, slot):
        path = filedialog.askopenfilename(
            initialdir=ensure_save_folder(self.prefs),
            filetypes=[("CivicDiag logs", "*.csv")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)
                if header[:2] != ["timestamp", "event"]:
                    raise ValueError("Not a CivicDiag session log")
                names = header[2:]
                series = {n: [] for n in names}
                t_start = None
                for row in reader:
                    try:
                        t = datetime.fromisoformat(row[0]).timestamp()
                    except (ValueError, IndexError):
                        continue
                    t_start = t_start or t
                    for name, raw in zip(names, row[2:]):
                        v = numeric(raw)
                        if v is not None:
                            series[name].append((t - t_start, v))
        except (OSError, ValueError, StopIteration) as e:
            messagebox.showerror("Can't load log", str(e))
            return

        self._stop_play()
        if slot == "A":
            self.chart.clear()
        prefix = "" if slot == "A" else "B: "
        offset = 0 if slot == "A" else 4
        added = 0
        for name, pts in series.items():
            if not pts:
                continue
            self.chart.add_series(
                f"{slot}:{name}", prefix + name,
                CHART_COLORS[(added + offset) % len(CHART_COLORS)],
                dash=(slot == "B"))
            for t, v in pts:
                self.chart.series[f"{slot}:{name}"]["points"].append((t, v))
            added += 1
        self.chart.set_static()
        self._set_status(f"Loaded {os.path.basename(path)} — drag to pan, "
                         "wheel to zoom, ▶ to replay.")

    def _toggle_play(self):
        if self._play_job:
            self._stop_play()
        elif self.chart.mode == "static" and self.chart.full:
            self.play_btn.config(text="⏸ Stop")
            self._play_tick()

    def _play_tick(self):
        f0, f1 = self.chart.full
        c = self.chart.cursor if self.chart.cursor is not None else f0
        c += (f1 - f0) / 240
        if c >= f1:
            self._stop_play()
            self.chart.cursor = f1
        else:
            self.chart.cursor = c
            self._play_job = self.after(50, self._play_tick)
        self.chart.schedule()

    def _stop_play(self):
        if self._play_job:
            self.after_cancel(self._play_job)
            self._play_job = None
        try:
            self.play_btn.config(text="▶ Play")
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Guided diagnostics
    # ------------------------------------------------------------------

    def _current_preset(self):
        sel = self.preset_list.curselection()
        if not sel:
            return None, None
        name = self.preset_list.get(sel[0]).strip()
        return name, PRESETS.get(name)

    def _show_preset(self, _e=None):
        name, preset = self._current_preset()
        if not preset:
            return
        t = self.guided_text
        t.config(state="normal")
        t.delete("1.0", "end")
        t.insert("end", name + "\n\n", "h")
        t.insert("end", preset["blurb"] + "\n\n")
        t.insert("end", "What to look for:\n", "h")
        for item in preset["look_for"]:
            t.insert("end", f"  •  {item}\n")
        if preset["pids"]:
            names = ", ".join(od.pid_def(p)[0] for p in preset["pids"]
                              if od.pid_def(p))
            t.insert("end", f"\nWatches: {names}\n", "m")
        t.config(state="disabled")
        self.preset_btn.config(
            state="normal",
            text="Check Readiness →" if preset["action"] == "readiness"
            else "Start Watching →")

    def _start_preset(self):
        name, preset = self._current_preset()
        if not preset:
            return
        if not (self.elm and self.elm.connected):
            messagebox.showwarning("Not connected",
                                   "Connect to the car (or DEMO) first.")
            return
        if preset["action"] == "readiness":
            self._run_bg(self._readiness_verdict,
                         "Checking smog readiness…")
            return
        pids = [p for p in preset["pids"] if p in self.supported_pids]
        if not pids:
            messagebox.showinfo("Not supported", "This car doesn't expose "
                                "the sensors this preset needs.")
            return
        self._stop_live()
        self.live_pids = pids
        self.active_alerts = dict(preset["alerts"])
        self._alerting = set()
        self._reset_stats()
        self.stats = {}
        self.nb.select(self.tab_frames["live"])
        self._start_live()
        self._set_status(f"Guided: {name} — abnormal readings will be "
                         "flagged in red.")

    def _readiness_verdict(self):
        self._read_readiness_data()
        cls, verdict = reports._smog_verdict(self.session)

        def update():
            t = self.guided_text
            t.config(state="normal")
            t.insert("end", "\n\nResult:  ", "h")
            t.insert("end", verdict + "\n", "ok" if cls == "pass" else "bad")
            for nme, sup, comp in self.session["readiness"]:
                if sup:
                    t.insert("end", f"  {'✔' if comp else '✘'} {nme}\n",
                             "ok" if comp else "bad")
            t.config(state="disabled")
            self._set_status("Readiness check complete.")
        self.ui(update)

    # ------------------------------------------------------------------
    # Freeze frame / readiness / O2 / info  (data + UI)
    # ------------------------------------------------------------------

    def _read_freeze(self):
        rows = []
        try:
            frames = self.elm.query("020200")
            data = frames[0][3:]
            code = od.decode_dtc_bytes(data[0], data[1]) \
                if len(data) >= 2 else None
            if code:
                rows.append(("Freeze frame caused by",
                             f"{code} — {od.describe_dtc(code)}", ""))
            else:
                rows.append(("Freeze frame", "Empty (no code stored)", ""))
        except (NoDataError, ELM327Error):
            rows.append(("Freeze frame", "Not available / empty", ""))

        for pid in sorted(od.PIDS):
            name, unit, nbytes, decode = od.PIDS[pid]
            try:
                frames = self.elm.query(f"02{pid:02X}00", timeout=4.0)
                data = frames[0][3:]
                if not data:
                    continue
                rows.append((name,
                             decode(data[:nbytes] if nbytes else data),
                             unit))
            except (NoDataError, ELM327Error):
                continue
        self.session["freeze"] = rows

        def update():
            self.ff_tree.delete(*self.ff_tree.get_children())
            for row in rows:
                self.ff_tree.insert("", "end", values=row)
            self._restripe(self.ff_tree)
            self._set_status("Freeze frame read complete.")
        self.ui(update)

    def _read_readiness_data(self):
        status = od.decode_monitor_status(self.elm.query_pid(0x01, 0x01))
        self.session["readiness"] = status["monitors"]
        return status

    def _read_readiness(self):
        status = self._read_readiness_data()

        def update():
            self.ready_tree.delete(*self.ready_tree.get_children())
            for name, supported, complete in status["monitors"]:
                if not supported:
                    self.ready_tree.insert("", "end",
                                           values=(name, "No", "—"))
                else:
                    self.ready_tree.insert(
                        "", "end",
                        values=(name, "Yes", "✔ Ready" if complete
                                else "✘ Not ready (incomplete)"))
            self._restripe(self.ready_tree)
            self.mil_label.config(
                bg=P["accent"] if status["mil"] else P["green"])
            self._set_status(
                f"Monitor status read. MIL "
                f"{'ON' if status['mil'] else 'off'}, "
                f"{status['dtc_count']} stored code(s).")
        self.ui(update)

    def _read_o2_tests(self):
        rows = []
        for sensor, label in ((0x01, "B1S1 (primary)"),
                              (0x02, "B1S2 (secondary)")):
            for tid, tname in od.MODE05_TIDS.items():
                try:
                    frames = self.elm.query(f"05{tid:02X}{sensor:02X}",
                                            timeout=4.0)
                    data = frames[0][3:]
                    if not data:
                        continue
                    if tid <= 0x04 or tid in (0x07, 0x08):
                        result = f"{data[0] * 0.005:.3f} V"
                    else:
                        result = " ".join(f"{b:02X}" for b in data)
                    rows.append((label, tname, result))
                except (NoDataError, ELM327Error):
                    continue

        def update():
            self.o2_tree.delete(*self.o2_tree.get_children())
            if not rows:
                self.o2_tree.insert("", "end", values=(
                    "—", "Mode 05 not supported by this ECU "
                    "(common on early OBD-II Hondas)", "—"))
            for row in rows:
                self.o2_tree.insert("", "end", values=row)
            self._restripe(self.o2_tree)
            self._set_status("O2 sensor test read complete.")
        self.ui(update)

    def _vehicle_info_quick(self):
        v = {"Adapter": getattr(self.elm, "elm_version", ""),
             "Port": getattr(self.elm, "port", ""),
             "Protocol": getattr(self.elm, "protocol_name", "")}
        try:
            lines = self.elm.command("ATRV", timeout=2.0)
            if lines:
                v["Battery"] = lines[0]
        except ELM327Error:
            pass
        try:
            v["OBD standard"] = od.PIDS[0x1C][3](
                self.elm.query_pid(0x01, 0x1C))
        except (NoDataError, ELM327Error, KeyError):
            pass
        self.session["vehicle"] = v
        return v

    def _read_info(self):
        v = self._vehicle_info_quick()
        lines = [f"{k}:  {val}" for k, val in v.items()]
        for req, label in (("0902", "VIN"), ("0904", "Calibration ID"),
                           ("0906", "Calibration CVN")):
            try:
                frames = self.elm.query(req, timeout=6.0)
                raw = bytes(b for f in frames for b in f[2:])
                text = "".join(chr(b) if 32 <= b < 127 else ""
                               for b in raw).strip()
                lines.append(f"{label}: {text or raw.hex(' ').upper()}")
                if label == "VIN" and text:
                    self.session["vehicle"]["VIN"] = text
            except (NoDataError, ELM327Error):
                lines.append(f"{label}: not supported by this ECU "
                             "(normal for 1999)")
        pids = ", ".join(f"{p:02X}" for p in
                         sorted(self.supported_pids - {od.PID_BATT}))
        lines.append(f"\nSupported Mode-01 PIDs:\n  {pids}")
        lines.append(
            "\nNote: ABS and SRS on a 1999 Civic are NOT on the OBD-II "
            "bus.\nThey report blink codes via the 2-pin service check "
            "connector\n(behind the passenger kick panel) with the "
            "terminals jumpered —\nsee README for the procedure.")
        text = "\n".join(lines)

        def update():
            self.info_text.delete("1.0", "end")
            self.info_text.insert("1.0", text)
            self._set_status("Vehicle info read complete.")
        self.ui(update)

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    def _snapshot_rows(self):
        rows = []
        for pid in self.live_pids:
            d = od.pid_def(pid)
            if not d:
                continue
            name, unit, _, _ = d
            val = self.latest.get(pid, "")
            st = self.stats.get(pid)
            if st and st[3]:
                rows.append((name, fmt(val), unit, fmt(st[0]), fmt(st[1]),
                             fmt(st[2] / st[3])))
            elif val != "":
                rows.append((name, fmt(val), unit, "", "", ""))
        return rows

    def _gather_session(self):
        """Fresh reads of everything a report needs (blocking)."""
        was_live = self.live_running
        if was_live:
            self.ui(self._stop_live)
            time.sleep(0.3)
        self._vehicle_info_quick()
        self._read_dtcs()
        self._read_freeze()
        self._read_readiness()
        self.session["snapshot"] = self._snapshot_rows()
        self.session["timestamp"] = datetime.now().isoformat(
            timespec="seconds")

    def _make_report(self, kind):
        if not (self.elm and self.elm.connected):
            # offline: build from whatever the session already holds
            if not self.session["codes"] and not self.session["readiness"]:
                messagebox.showwarning(
                    "No data", "Connect to the car (or DEMO) first — "
                    "reports read fresh data from the ECU.")
                return

        def job():
            baseline = None
            if kind == "beforeafter":
                path = os.path.join(ensure_save_folder(self.prefs),
                                    "CivicDiag_baseline.json")
                if not os.path.exists(path):
                    self.ui(messagebox.showwarning, "No baseline",
                            "Save a baseline first (button 1) — before "
                            "you make the repair.")
                    return
                import json
                with open(path, encoding="utf-8") as f:
                    baseline = json.load(f)
            if self.elm and self.elm.connected:
                self._gather_session()
            html_text = reports.build_html(self.session, kind, baseline)
            folder = ensure_save_folder(self.prefs)
            fname = reports.auto_name(self.session, "html",
                                      prefix=f"CivicDiag_{kind}")
            path = os.path.join(folder, fname)
            with open(path, "w", encoding="utf-8") as f:
                f.write(html_text)
            if kind == "share":
                text = reports.codes_to_clipboard_text(self.session)
                self.ui(self.clipboard_clear)
                self.ui(self.clipboard_append, text)
            webbrowser.open(f"file:///{path.replace(os.sep, '/')}")
            self.ui(self._set_status,
                    f"Report saved and opened: {path}"
                    + ("  (codes copied to clipboard)"
                       if kind == "share" else ""))
        self._run_bg(job, "Reading data for the report…")

    def _save_baseline(self):
        if not (self.elm and self.elm.connected):
            messagebox.showwarning("Not connected", "Connect first.")
            return

        def job():
            self._gather_session()
            path = os.path.join(ensure_save_folder(self.prefs),
                                "CivicDiag_baseline.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write(reports.session_to_json(self.session))
            self.ui(self._set_status,
                    f"Baseline saved ({path}). Make the repair, then run "
                    "the Before/After report.")
        self._run_bg(job, "Saving baseline…")

    def _export_session(self, ext):
        builders = {"txt": reports.session_to_txt,
                    "json": reports.session_to_json,
                    "csv": reports.codes_to_csv}
        content = builders[ext](self.session)
        path = filedialog.asksaveasfilename(
            initialdir=ensure_save_folder(self.prefs),
            initialfile=reports.auto_name(self.session, ext),
            defaultextension=f".{ext}",
            filetypes=[(ext.upper(), f"*.{ext}")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        self._set_status(f"Exported: {path}")

    def _screenshot(self):
        try:
            from PIL import ImageGrab
            self.update_idletasks()
            x, y = self.winfo_rootx(), self.winfo_rooty()
            w, h = self.winfo_width(), self.winfo_height()
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            folder = ensure_save_folder(self.prefs)
            path = os.path.join(folder,
                                reports.auto_name(self.session, "png",
                                                  prefix="CivicDiag_shot"))
            img.save(path)
            self._set_status(f"Screenshot saved: {path}")
        except Exception as e:
            messagebox.showerror("Screenshot failed", repr(e))

    # ------------------------------------------------------------------
    # Terminal
    # ------------------------------------------------------------------

    def _log_traffic(self, line):
        self.ui(self._append_term, line)

    def _append_term(self, line):
        try:
            self.term_out.insert("end", line.rstrip() + "\n")
            if float(self.term_out.index("end-1c").split(".")[0]) > 2000:
                self.term_out.delete("1.0", "200.0")
            self.term_out.see("end")
        except tk.TclError:
            pass

    def _term_send(self, _event=None):
        cmd = self.term_entry.get().strip()
        if not cmd:
            return
        if not (self.elm and self.elm.connected):
            self._append_term("[not connected]")
            return
        self.term_history.append(cmd)
        self.term_hist_i = len(self.term_history)
        self.term_entry.delete(0, "end")
        self._run_bg(lambda: self.elm.command(cmd, timeout=8.0))

    def _term_hist_up(self, _e=None):
        if self.term_history and self.term_hist_i > 0:
            self.term_hist_i -= 1
            self.term_entry.delete(0, "end")
            self.term_entry.insert(0, self.term_history[self.term_hist_i])
        return "break"

    def _term_hist_down(self, _e=None):
        if self.term_hist_i < len(self.term_history) - 1:
            self.term_hist_i += 1
            self.term_entry.delete(0, "end")
            self.term_entry.insert(0, self.term_history[self.term_hist_i])
        else:
            self.term_hist_i = len(self.term_history)
            self.term_entry.delete(0, "end")
        return "break"

    # ------------------------------------------------------------------

    def _on_close(self):
        self._stop_live()
        self.prefs["live_pids"] = self.live_pids
        save_prefs(self.prefs)
        try:
            if self.elm:
                self.elm.close()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
