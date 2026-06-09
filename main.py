"""
CivicDiag — OBD-II diagnostic suite for the 1999 Honda Civic
(works on any 1996+ OBD-II vehicle via an ELM327 USB adapter).

Run:  python main.py   (or launch CivicDiag.exe)
"""

import csv
import queue
import threading
import time
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from elm327 import ELM327, ELM327Error, NoDataError, find_ports
import obd_data as od

APP_TITLE = "CivicDiag"
POLL_GAP = 0.02  # pause between PID requests (ISO 9141 paces itself)

# ---- dark theme palette ----
BG = "#14171c"       # window background
PANEL = "#1b2026"    # table / input background
PANEL2 = "#242b33"   # headings, buttons
CARD = "#20262e"     # cards, selected tab
FG = "#e8eaed"
MUTED = "#9aa3ad"
ACCENT = "#e23b3b"   # Honda red
GREEN = "#34c759"
SEL = "#2f4156"

FONT = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI Semibold", 10)
FONT_BIG = ("Segoe UI", 24, "bold")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1060x740")
        self.minsize(900, 620)
        self.configure(bg=BG)
        self._apply_theme()

        self.elm = ELM327(log_fn=self._log_traffic)
        self.supported_pids = set()
        self.live_running = False
        self.live_thread = None
        self.csv_file = None
        self.csv_writer = None
        self.minmax = {}  # pid -> [min, max] for numeric values

        self.ui_queue = queue.Queue()
        self._build_ui()
        self.after(50, self._drain_ui_queue)
        self.after(10, self._dark_title_bar)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _apply_theme(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG,
                        fieldbackground=PANEL, font=FONT,
                        bordercolor=PANEL2, lightcolor=BG, darkcolor=BG)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Muted.TLabel", foreground=MUTED, font=FONT_SMALL)

        style.configure("TButton", background=PANEL2, foreground=FG,
                        borderwidth=0, padding=(14, 7), font=FONT)
        style.map("TButton",
                  background=[("disabled", PANEL), ("active", "#2f3a46")],
                  foreground=[("disabled", MUTED)])
        style.configure("Accent.TButton", background=ACCENT,
                        foreground="white", font=FONT_BOLD)
        style.map("Accent.TButton",
                  background=[("disabled", PANEL), ("active", "#f05050")])

        style.configure("TNotebook", background=BG, borderwidth=0,
                        tabmargins=(8, 6, 8, 0))
        style.configure("TNotebook.Tab", background=BG, foreground=MUTED,
                        padding=(16, 9), font=FONT, borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", CARD)],
                  foreground=[("selected", FG)])

        style.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=FG, rowheight=28, borderwidth=0)
        style.configure("Treeview.Heading", background=PANEL2,
                        foreground=MUTED, font=("Segoe UI Semibold", 9),
                        padding=(8, 6), borderwidth=0)
        style.map("Treeview.Heading", background=[("active", PANEL2)])
        style.map("Treeview", background=[("selected", SEL)],
                  foreground=[("selected", FG)])

        style.configure("TCheckbutton", background=BG, foreground=FG,
                        font=FONT)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("TCombobox", fieldbackground=PANEL,
                        background=PANEL2, foreground=FG, arrowcolor=FG,
                        selectbackground=PANEL, selectforeground=FG,
                        padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL)])
        style.configure("TEntry", fieldbackground=PANEL, foreground=FG,
                        insertcolor=FG, padding=6, borderwidth=0)
        style.configure("Vertical.TScrollbar", background=PANEL2,
                        troughcolor=BG, borderwidth=0, arrowcolor=MUTED)
        style.map("Vertical.TScrollbar", background=[("active", "#2f3a46")])

        # combobox dropdown list colors
        self.option_add("*TCombobox*Listbox.background", PANEL)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", SEL)
        self.option_add("*TCombobox*Listbox.selectForeground", FG)
        self.option_add("*TCombobox*Listbox.font", FONT)

    def _dark_title_bar(self):
        """Ask Windows for a dark title bar (Win10 1809+ / Win11)."""
        try:
            import ctypes
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
        except Exception:
            pass

    @staticmethod
    def _restripe(tree):
        for i, iid in enumerate(tree.get_children()):
            tree.item(iid, tags=("odd" if i % 2 else "even",))

    # ------------------------------------------------------------------
    # Thread-safe UI plumbing
    # ------------------------------------------------------------------

    def ui(self, fn, *args):
        """Schedule a callable on the Tk thread."""
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

    def _run_bg(self, fn, busy_msg=None):
        """Run fn on a worker thread; surface errors in a dialog."""
        if busy_msg:
            self.status_var.set(busy_msg)

        def wrapper():
            try:
                fn()
            except NoDataError as e:
                self.ui(self.status_var.set, f"No data: {e}")
            except ELM327Error as e:
                self.ui(messagebox.showerror, "Adapter error", str(e))
                self.ui(self.status_var.set, "Error — see dialog")
            except Exception as e:  # keep the GUI alive no matter what
                self.ui(messagebox.showerror, "Unexpected error", repr(e))

        threading.Thread(target=wrapper, daemon=True).start()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ---- header / connection bar ----
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=12, pady=(10, 4))

        tk.Label(bar, text="CivicDiag", bg=BG, fg=FG,
                 font=("Segoe UI", 15, "bold")).pack(side="left")
        tk.Label(bar, text="  1999 Honda Civic · OBD-II", bg=BG, fg=MUTED,
                 font=FONT_SMALL).pack(side="left", pady=(6, 0))

        self.mil_label = tk.Label(bar, text="MIL", bg="#3a4048", fg="white",
                                  font=("Segoe UI Semibold", 9),
                                  padx=10, pady=3)
        self.mil_label.pack(side="right", padx=(8, 0))
        self.proto_var = tk.StringVar(value="Not connected")
        tk.Label(bar, textvariable=self.proto_var, bg=BG, fg=MUTED,
                 font=FONT_SMALL).pack(side="right", padx=8)

        conn = tk.Frame(self, bg=BG)
        conn.pack(fill="x", padx=12, pady=(2, 6))
        ttk.Label(conn, text="Port", style="Muted.TLabel").pack(side="left")
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(conn, textvariable=self.port_var,
                                       width=36, state="readonly")
        self.port_combo.pack(side="left", padx=8)
        ttk.Button(conn, text="↻ Rescan",
                   command=self._refresh_ports).pack(side="left")
        self.connect_btn = ttk.Button(conn, text="Connect",
                                      style="Accent.TButton",
                                      command=self._toggle_connect)
        self.connect_btn.pack(side="left", padx=10)

        # ---- notebook ----
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        self._build_dtc_tab()
        self._build_live_tab()
        self._build_freeze_tab()
        self._build_readiness_tab()
        self._build_o2_tab()
        self._build_info_tab()
        self._build_terminal_tab()

        # ---- status bar ----
        self.status_var = tk.StringVar(
            value="Plug the USB adapter into the car, turn the ignition to "
                  "ON (II), pick the COM port, and hit Connect.")
        tk.Label(self, textvariable=self.status_var, bg=PANEL, fg=MUTED,
                 anchor="w", font=FONT_SMALL, padx=12,
                 pady=5).pack(fill="x", side="bottom")

        self._refresh_ports()

    def _make_tree(self, parent, columns, widths):
        frame = tk.Frame(parent, bg=CARD)
        tree = ttk.Treeview(frame, columns=columns, show="headings",
                            selectmode="browse")
        for col, w in zip(columns, widths):
            tree.heading(col, text=col)
            tree.column(col, width=w, anchor="w")
        tree.tag_configure("even", background=PANEL)
        tree.tag_configure("odd", background="#20262e")
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return frame, tree

    def _tab(self, title):
        tab = tk.Frame(self.nb, bg=CARD)
        self.nb.add(tab, text=title)
        inner = tk.Frame(tab, bg=CARD)
        inner.pack(fill="both", expand=True, padx=10, pady=10)
        return inner

    def _toolbar(self, parent):
        bar = tk.Frame(parent, bg=CARD)
        bar.pack(fill="x", pady=(0, 8))
        return bar

    @staticmethod
    def _hint(parent, text):
        tk.Label(parent, text=text, bg=CARD, fg=MUTED, font=FONT_SMALL,
                 wraplength=560, justify="left").pack(side="left", padx=12)

    # ---- Trouble codes tab ----

    def _build_dtc_tab(self):
        tab = self._tab("  Trouble Codes  ")
        btns = self._toolbar(tab)
        ttk.Button(btns, text="Read Codes", style="Accent.TButton",
                   command=lambda: self._run_bg(self._read_dtcs,
                                                "Reading trouble codes…")
                   ).pack(side="left")
        ttk.Button(btns, text="Clear Codes / Reset MIL",
                   command=self._clear_dtcs_confirm).pack(side="left",
                                                          padx=8)
        self.dtc_summary = tk.StringVar(value="")
        tk.Label(btns, textvariable=self.dtc_summary, bg=CARD, fg=MUTED,
                 font=FONT_SMALL).pack(side="left", padx=12)

        frame, self.dtc_tree = self._make_tree(
            tab, ("Type", "Code", "Description"), (110, 90, 680))
        frame.pack(fill="both", expand=True)

    # ---- Live data tab ----

    def _build_live_tab(self):
        tab = self._tab("  Live Data  ")

        # big readout cards
        cards = tk.Frame(tab, bg=CARD)
        cards.pack(fill="x", pady=(0, 10))
        self._cards = {}
        for pid, label, unit in ((0x0C, "ENGINE", "rpm"),
                                 (0x0D, "SPEED", "mph"),
                                 (0x05, "COOLANT", "°F"),
                                 (0x11, "THROTTLE", "%")):
            card = tk.Frame(cards, bg=PANEL2, padx=18, pady=10)
            card.pack(side="left", padx=(0, 10), fill="x", expand=True)
            tk.Label(card, text=label, bg=PANEL2, fg=MUTED,
                     font=("Segoe UI Semibold", 8)).pack(anchor="w")
            val = tk.Label(card, text="—", bg=PANEL2, fg=FG, font=FONT_BIG)
            val.pack(anchor="w")
            tk.Label(card, text=unit, bg=PANEL2, fg=MUTED,
                     font=FONT_SMALL).pack(anchor="w")
            self._cards[pid] = val

        btns = self._toolbar(tab)
        self.live_btn = ttk.Button(btns, text="▶  Start",
                                   style="Accent.TButton",
                                   command=self._toggle_live)
        self.live_btn.pack(side="left")
        ttk.Button(btns, text="Select PIDs…",
                   command=self._select_pids).pack(side="left", padx=8)
        ttk.Button(btns, text="Reset Min/Max",
                   command=self._reset_minmax).pack(side="left")
        self.record_var = tk.BooleanVar(value=False)
        rec = tk.Checkbutton(btns, text="Record to CSV",
                             variable=self.record_var, bg=CARD, fg=FG,
                             activebackground=CARD, activeforeground=FG,
                             selectcolor=PANEL, font=FONT)
        rec.pack(side="left", padx=12)
        self.rate_var = tk.StringVar(value="")
        tk.Label(btns, textvariable=self.rate_var, bg=CARD, fg=MUTED,
                 font=FONT_SMALL).pack(side="right")

        frame, self.live_tree = self._make_tree(
            tab, ("Parameter", "Value", "Unit", "Min", "Max"),
            (330, 170, 90, 110, 110))
        frame.pack(fill="both", expand=True)

        self.live_pids = list(od.DEFAULT_LIVE_PIDS)

    # ---- Freeze frame tab ----

    def _build_freeze_tab(self):
        tab = self._tab("  Freeze Frame  ")
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

    # ---- Readiness tab ----

    def _build_readiness_tab(self):
        tab = self._tab("  Readiness  ")
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

    # ---- O2 sensor tests tab ----

    def _build_o2_tab(self):
        tab = self._tab("  O2 Tests  ")
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

    # ---- Vehicle info tab ----

    def _build_info_tab(self):
        tab = self._tab("  Vehicle Info  ")
        btns = self._toolbar(tab)
        ttk.Button(btns, text="Read Vehicle Info", style="Accent.TButton",
                   command=lambda: self._run_bg(self._read_info,
                                                "Reading vehicle info…")
                   ).pack(side="left")
        self.info_text = tk.Text(tab, wrap="word", font=("Consolas", 10),
                                 bg=PANEL, fg=FG, insertbackground=FG,
                                 relief="flat", padx=10, pady=8)
        self.info_text.pack(fill="both", expand=True)

    # ---- Terminal tab ----

    def _build_terminal_tab(self):
        tab = self._tab("  Terminal  ")
        tk.Label(tab, text="Raw adapter access — send AT commands (e.g. "
                           "ATRV = battery voltage) or OBD requests (e.g. "
                           "010C = RPM). All traffic is logged here.",
                 bg=CARD, fg=MUTED, font=FONT_SMALL,
                 anchor="w").pack(fill="x")
        self.term_out = tk.Text(tab, wrap="none", font=("Consolas", 9),
                                bg="#101418", fg="#9fdf9f", height=20,
                                relief="flat", padx=8, pady=6,
                                insertbackground=FG)
        self.term_out.pack(fill="both", expand=True, pady=6)
        entry_row = tk.Frame(tab, bg=CARD)
        entry_row.pack(fill="x")
        self.term_entry = ttk.Entry(entry_row, font=("Consolas", 10))
        self.term_entry.pack(side="left", fill="x", expand=True)
        self.term_entry.bind("<Return>", self._term_send)
        ttk.Button(entry_row, text="Send",
                   command=self._term_send).pack(side="left", padx=6)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _refresh_ports(self):
        ports = find_ports()
        values = [f"{dev} — {desc}" for dev, desc in ports]
        self.port_combo["values"] = values
        if values and not self.port_var.get():
            self.port_var.set(values[0])
        if not values:
            self.status_var.set("No COM ports found. Plug in the USB "
                                "adapter and click Rescan (driver needed? "
                                "see README).")

    def _toggle_connect(self):
        if self.elm.connected:
            self._stop_live()
            self.elm.close()
            self.connect_btn.config(text="Connect")
            self.proto_var.set("Not connected")
            self.mil_label.config(bg="#3a4048")
            self.status_var.set("Disconnected.")
            return

        sel = self.port_var.get()
        if not sel:
            messagebox.showwarning("No port", "Select a COM port first.")
            return
        port = sel.split(" — ")[0]
        self.connect_btn.config(state="disabled")
        self.status_var.set(f"Connecting on {port}… (ISO 9141 init can "
                            "take ~10 s)")

        def job():
            try:
                self.elm.connect(port)
                self._discover_pids()
                self.ui(self._on_connected)
            except ELM327Error as e:
                self.ui(messagebox.showerror, "Connection failed", str(e))
                self.ui(self.status_var.set, "Connection failed.")
            finally:
                self.ui(lambda: self.connect_btn.config(state="normal"))

        threading.Thread(target=job, daemon=True).start()

    def _discover_pids(self):
        """Walk the supported-PID bitmasks (0100, 0120, 0140)."""
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

    def _on_connected(self):
        self.connect_btn.config(text="Disconnect")
        self.proto_var.set(
            f"{self.elm.protocol_name}  ·  {self.elm.elm_version}")
        n = len(self.supported_pids)
        self.status_var.set(
            f"Connected — vehicle reports {n} supported PIDs. "
            "Read codes or start live data.")
        # trim default live list to what the car actually supports
        self.live_pids = [p for p in self.live_pids
                          if p in self.supported_pids] or \
                         sorted(p for p in self.supported_pids if p in od.PIDS)
        self._run_bg(self._read_readiness)

    # ------------------------------------------------------------------
    # Trouble codes
    # ------------------------------------------------------------------

    def _read_dtcs(self):
        rows = []
        # MIL + count from PID 01
        mil, count = False, 0
        try:
            status = od.decode_monitor_status(self.elm.query_pid(0x01, 0x01))
            mil, count = status["mil"], status["dtc_count"]
        except (NoDataError, ELM327Error):
            pass

        for mode, label in ((0x03, "STORED"), (0x07, "PENDING")):
            try:
                frames = self.elm.query(f"{mode:02X}")
                for code in od.decode_dtc_frames(frames):
                    rows.append((label, code, od.describe_dtc(code)))
            except NoDataError:
                continue

        def update():
            self.dtc_tree.delete(*self.dtc_tree.get_children())
            for row in rows:
                self.dtc_tree.insert("", "end", values=row)
            if not rows:
                self.dtc_tree.insert("", "end",
                                     values=("—", "—", "No trouble codes."))
            self._restripe(self.dtc_tree)
            self.mil_label.config(bg=ACCENT if mil else GREEN)
            stored = sum(1 for r in rows if r[0] == "STORED")
            pending = sum(1 for r in rows if r[0] == "PENDING")
            self.dtc_summary.set(
                f"MIL {'ON' if mil else 'off'} — ECU reports {count} stored "
                f"code(s); read {stored} stored, {pending} pending.")
            self.status_var.set("Trouble code read complete.")
        self.ui(update)

    def _clear_dtcs_confirm(self):
        if not self.elm.connected:
            messagebox.showwarning("Not connected", "Connect first.")
            return
        if messagebox.askyesno(
                "Clear codes?",
                "This erases all stored & pending codes, freeze frame data, "
                "and resets every readiness monitor (the car will need a "
                "full drive cycle before it can pass a smog check).\n\n"
                "Tip: read and note the codes and freeze frame first.\n\n"
                "Clear everything now?",
                icon="warning"):
            def job():
                self.elm.query("04", timeout=10.0)
                self.ui(self.status_var.set,
                        "Codes cleared. MIL should be off.")
                self._read_dtcs()
            self._run_bg(job, "Clearing codes…")

    # ------------------------------------------------------------------
    # Live data
    # ------------------------------------------------------------------

    def _select_pids(self):
        if not self.supported_pids:
            messagebox.showwarning("Not connected",
                                   "Connect to the car first.")
            return
        win = tk.Toplevel(self)
        win.title("Select live parameters")
        win.geometry("440x540")
        win.configure(bg=BG)
        win.transient(self)
        tk.Label(win, text="Fewer parameters = faster refresh "
                           "(ISO 9141 manages ~5-8 readings/sec total).",
                 bg=BG, fg=MUTED, font=FONT_SMALL, wraplength=400,
                 justify="left", padx=10, pady=8).pack(anchor="w")
        list_frame = tk.Frame(win, bg=BG)
        list_frame.pack(fill="both", expand=True, padx=10)
        vars_ = {}
        for pid in sorted(self.supported_pids):
            if pid not in od.PIDS:
                continue
            name, unit, _, _ = od.PIDS[pid]
            v = tk.BooleanVar(value=pid in self.live_pids)
            vars_[pid] = v
            tk.Checkbutton(list_frame, text=f"{name}  [{pid:02X}]",
                           variable=v, bg=BG, fg=FG, activebackground=BG,
                           activeforeground=FG, selectcolor=PANEL,
                           font=FONT).pack(anchor="w")

        def apply():
            chosen = [p for p, v in vars_.items() if v.get()]
            if chosen:
                self.live_pids = chosen
                self._reset_minmax()
            win.destroy()
        ttk.Button(win, text="Apply", style="Accent.TButton",
                   command=apply).pack(pady=10)

    def _reset_minmax(self):
        self.minmax = {}

    def _toggle_live(self):
        if self.live_running:
            self._stop_live()
        else:
            self._start_live()

    def _start_live(self):
        if not self.elm.connected:
            messagebox.showwarning("Not connected", "Connect first.")
            return
        if not self.live_pids:
            messagebox.showwarning("No PIDs", "Select parameters first.")
            return
        if self.record_var.get():
            path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                initialfile=f"civic_log_{datetime.now():%Y%m%d_%H%M%S}.csv",
                filetypes=[("CSV files", "*.csv")])
            if not path:
                self.record_var.set(False)
            else:
                self.csv_file = open(path, "w", newline="",
                                     encoding="utf-8")
                self.csv_writer = csv.writer(self.csv_file)
                header = ["timestamp"] + [
                    od.PIDS[p][0] for p in self.live_pids]
                self.csv_writer.writerow(header)

        # build table rows
        self.live_tree.delete(*self.live_tree.get_children())
        self._live_items = {}
        for i, pid in enumerate(self.live_pids):
            name, unit, _, _ = od.PIDS[pid]
            iid = self.live_tree.insert(
                "", "end", values=(name, "—", unit, "", ""),
                tags=("odd" if i % 2 else "even",))
            self._live_items[pid] = iid

        self.live_running = True
        self.live_btn.config(text="⏸  Stop")
        self.live_thread = threading.Thread(target=self._live_loop,
                                            daemon=True)
        self.live_thread.start()

    def _stop_live(self):
        self.live_running = False
        self.live_btn.config(text="▶  Start")
        if self.csv_file:
            try:
                self.csv_file.close()
            except OSError:
                pass
            self.csv_file = None
            self.csv_writer = None
            self.status_var.set("Recording saved.")

    def _live_loop(self):
        cycle_times = []
        while self.live_running and self.elm.connected:
            t0 = time.monotonic()
            row_vals = []
            for pid in list(self.live_pids):
                if not self.live_running:
                    break
                name, unit, nbytes, decode = od.PIDS[pid]
                try:
                    data = self.elm.query_pid(0x01, pid, timeout=4.0)
                    value = decode(data[:nbytes] if nbytes else data)
                except NoDataError:
                    value = "n/a"
                except ELM327Error as e:
                    self.ui(self.status_var.set, f"Live data stopped: {e}")
                    self.ui(self._stop_live)
                    return
                row_vals.append(value)

                if isinstance(value, (int, float)):
                    mm = self.minmax.setdefault(pid, [value, value])
                    mm[0] = min(mm[0], value)
                    mm[1] = max(mm[1], value)
                    mn, mx = mm
                else:
                    mn = mx = ""
                self.ui(self._update_live_row, pid, value, mn, mx)
                time.sleep(POLL_GAP)

            if self.csv_writer and row_vals:
                try:
                    self.csv_writer.writerow(
                        [datetime.now().isoformat(timespec="milliseconds")]
                        + row_vals)
                except (ValueError, OSError):
                    pass

            dt = time.monotonic() - t0
            cycle_times.append(dt)
            cycle_times = cycle_times[-5:]
            avg = sum(cycle_times) / len(cycle_times)
            if avg > 0:
                self.ui(self.rate_var.set,
                        f"{len(self.live_pids) / avg:.1f} readings/sec · "
                        f"full refresh every {avg:.1f}s")

    def _update_live_row(self, pid, value, mn, mx):
        iid = self._live_items.get(pid)
        if iid:
            name, unit, _, _ = od.PIDS[pid]
            self.live_tree.item(
                iid, values=(name, value, unit, mn, mx),
                tags=self.live_tree.item(iid, "tags"))
        # big cards (US units)
        card = self._cards.get(pid)
        if card and isinstance(value, (int, float)):
            if pid == 0x0D:                      # km/h -> mph
                card.config(text=f"{value * 0.621371:.0f}")
            elif pid == 0x05:                    # °C -> °F
                card.config(text=f"{value * 9 / 5 + 32:.0f}")
            elif pid == 0x0C:
                card.config(text=f"{value:,.0f}".replace(",", " "))
            else:
                card.config(text=f"{value:.0f}")

    # ------------------------------------------------------------------
    # Freeze frame / readiness / O2 / info
    # ------------------------------------------------------------------

    def _read_freeze(self):
        rows = []
        # PID 02 of mode 02 = the DTC that triggered the freeze frame
        try:
            frames = self.elm.query("020200")
            data = frames[0][3:]  # 42 02 00 <b1> <b2>
            code = od.decode_dtc_bytes(data[0], data[1]) if len(data) >= 2 \
                else None
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
                data = frames[0][3:]  # drop 42 <pid> <frame#>
                if not data:
                    continue
                rows.append((name, decode(data[:nbytes] if nbytes else data),
                             unit))
            except (NoDataError, ELM327Error):
                continue

        def update():
            self.ff_tree.delete(*self.ff_tree.get_children())
            for row in rows:
                self.ff_tree.insert("", "end", values=row)
            self._restripe(self.ff_tree)
            self.status_var.set("Freeze frame read complete.")
        self.ui(update)

    def _read_readiness(self):
        status = od.decode_monitor_status(self.elm.query_pid(0x01, 0x01))

        def update():
            self.ready_tree.delete(*self.ready_tree.get_children())
            for name, supported, complete in status["monitors"]:
                if not supported:
                    self.ready_tree.insert(
                        "", "end", values=(name, "No", "—"))
                else:
                    self.ready_tree.insert(
                        "", "end",
                        values=(name, "Yes",
                                "✔ Ready" if complete
                                else "✘ Not ready (incomplete)"))
            self._restripe(self.ready_tree)
            self.mil_label.config(bg=ACCENT if status["mil"] else GREEN)
            self.status_var.set(
                f"Monitor status read. MIL is "
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
            self.status_var.set("O2 sensor test read complete.")
        self.ui(update)

    def _read_info(self):
        lines = []
        lines.append(f"Adapter:    {self.elm.elm_version}")
        lines.append(f"Port:       {self.elm.port}")
        lines.append(f"Protocol:   {self.elm.protocol_name}")
        try:
            v = self.elm.command("ATRV", timeout=2.0)
            lines.append(f"Battery:    {v[0] if v else '?'}")
        except ELM327Error:
            pass
        try:
            std = od.PIDS[0x1C][3](self.elm.query_pid(0x01, 0x1C))
            lines.append(f"OBD standard: {std}")
        except (NoDataError, ELM327Error, KeyError):
            pass

        # Mode 09 (VIN etc.) — usually not supported on a 1999, try anyway
        for req, label in (("0902", "VIN"), ("0904", "Calibration ID"),
                           ("0906", "Calibration CVN")):
            try:
                frames = self.elm.query(req, timeout=6.0)
                raw = bytes(b for f in frames for b in f[2:])
                text = "".join(chr(b) if 32 <= b < 127 else ""
                               for b in raw).strip()
                lines.append(f"{label}: {text or raw.hex(' ').upper()}")
            except (NoDataError, ELM327Error):
                lines.append(f"{label}: not supported by this ECU "
                             "(normal for 1999)")

        pids = ", ".join(f"{p:02X}" for p in sorted(self.supported_pids))
        lines.append(f"\nSupported Mode-01 PIDs ({len(self.supported_pids)}):"
                     f"\n  {pids}")
        lines.append(
            "\nNote: ABS and SRS on a 1999 Civic are NOT on the OBD-II bus."
            "\nThey report blink codes via the 2-pin service check connector"
            "\n(behind the passenger kick panel / under the dash) with the"
            "\nterminals jumpered — see README for the procedure.")

        text = "\n".join(lines)

        def update():
            self.info_text.delete("1.0", "end")
            self.info_text.insert("1.0", text)
            self.status_var.set("Vehicle info read complete.")
        self.ui(update)

    # ------------------------------------------------------------------
    # Terminal
    # ------------------------------------------------------------------

    def _log_traffic(self, line):
        self.ui(self._append_term, line)

    def _append_term(self, line):
        self.term_out.insert("end", line.rstrip() + "\n")
        # keep last ~2000 lines
        if float(self.term_out.index("end-1c").split(".")[0]) > 2000:
            self.term_out.delete("1.0", "200.0")
        self.term_out.see("end")

    def _term_send(self, _event=None):
        cmd = self.term_entry.get().strip()
        if not cmd:
            return
        if not self.elm.connected:
            self._append_term("[not connected]")
            return
        self.term_entry.delete(0, "end")
        self._run_bg(lambda: self.elm.command(cmd, timeout=8.0))

    # ------------------------------------------------------------------

    def _on_close(self):
        self._stop_live()
        try:
            self.elm.close()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
