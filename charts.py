"""
StripChart — a dependency-free tkinter Canvas chart.

Two modes:
  live    — trailing time window, points appended in real time
  static  — a loaded log: zoom (mouse wheel / buttons), pan (drag),
            playback cursor, optional overlay of a second log (dashed)

Each series is auto-scaled to its own range (so RPM and O2 volts can
share the chart); the legend shows the live numeric values. Segments
outside a series' alert range are drawn in red. Click a legend entry
to hide/show that series.
"""

import time
import tkinter as tk

CHART_COLORS = ["#4fa3ff", "#ffc145", "#3ddc84", "#ff7eb6", "#c792ea",
                "#4dd0e1", "#ff8a65", "#a8e063"]
ALERT_COLOR = "#ff4444"


class StripChart(tk.Canvas):
    def __init__(self, master, palette, **kw):
        super().__init__(master, highlightthickness=0,
                         bg=palette["chartbg"], **kw)
        self.P = palette
        self.mode = "live"
        self.window = 60.0          # live trailing window (seconds)
        self.series = {}            # key -> dict
        self.order = []
        self._keymap = {}           # str(key) -> key, for legend clicks
        self.view = None            # (t0, t1) in static mode
        self.full = None            # (tmin, tmax) of loaded data
        self.cursor = None          # playback cursor time
        self.paused = False
        self._pending = False
        self._drag = None
        self.bind("<Configure>", lambda e: self.schedule())
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)

    # ---------------- series management ----------------

    def clear(self):
        self.series = {}
        self.order = []
        self._keymap = {}
        self.view = self.full = self.cursor = None
        self.schedule()

    def add_series(self, key, label, color, alert=None, dash=False):
        self.series[key] = dict(label=label, color=color, points=[],
                                alert=alert, dash=dash, visible=True)
        if key not in self.order:
            self.order.append(key)
        self._keymap = {str(k): k for k in self.order}

    def show_all(self):
        for s in self.series.values():
            s["visible"] = True
        self.schedule()

    def add_point(self, key, t, v):
        s = self.series.get(key)
        if s is None:
            return
        s["points"].append((t, v))
        if self.mode == "live" and len(s["points"]) > 6000:
            del s["points"][:2000]
        if not self.paused:
            self.schedule()

    def set_static(self):
        """Switch to static mode, framing all loaded data."""
        ts = [p[0] for s in self.series.values() for p in s["points"]]
        if not ts:
            return
        self.mode = "static"
        self.full = (min(ts), max(ts))
        self.view = self.full
        self.cursor = self.full[0]
        self.schedule()

    def set_live(self, window=None):
        self.mode = "live"
        if window:
            self.window = window
        self.cursor = None
        self.schedule()

    # ---------------- interaction ----------------

    def _span(self):
        if self.mode == "live":
            now = time.monotonic()
            return now - self.window, now
        return self.view or (0, 1)

    def zoom(self, factor, around=None):
        if self.mode != "static" or not self.view:
            return
        t0, t1 = self.view
        c = around if around is not None else (t0 + t1) / 2
        t0 = c - (c - t0) * factor
        t1 = c + (t1 - c) * factor
        f0, f1 = self.full
        self.view = (max(f0, t0), min(f1, t1))
        self.schedule()

    def reset_view(self):
        if self.full:
            self.view = self.full
            self.schedule()

    def _on_wheel(self, e):
        if self.mode != "static":
            return
        t0, t1 = self._span()
        frac = e.x / max(1, self.winfo_width())
        around = t0 + frac * (t1 - t0)
        self.zoom(0.8 if e.delta > 0 else 1.25, around)

    def _legend_hit(self, x, y):
        """Return the series key whose legend row was clicked, or None."""
        for item in self.find_overlapping(x - 2, y - 2, x + 2, y + 2):
            for tag in self.gettags(item):
                if tag.startswith("leg:"):
                    return self._keymap.get(tag[4:])
        return None

    def _on_press(self, e):
        key = self._legend_hit(e.x, e.y)
        if key is not None:
            s = self.series[key]
            s["visible"] = not s["visible"]
            self.schedule()
            return
        if self.mode == "static":
            self._drag = (e.x, self.view)

    def _on_drag(self, e):
        if self.mode != "static" or not self._drag:
            return
        x0, (t0, t1) = self._drag
        dt = (x0 - e.x) / max(1, self.winfo_width()) * (t1 - t0)
        f0, f1 = self.full
        dt = max(f0 - t0, min(f1 - t1, dt))
        self.view = (t0 + dt, t1 + dt)
        self.schedule()

    # ---------------- drawing ----------------

    def schedule(self):
        if not self._pending:
            self._pending = True
            self.after(80, self._redraw)

    def _redraw(self):
        self._pending = False
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 60 or h < 60:
            return
        t0, t1 = self._span()
        span = max(0.001, t1 - t0)
        pad_top, pad_bot = 8, 22
        plot_h = h - pad_top - pad_bot

        # grid
        for i in range(1, 4):
            y = pad_top + plot_h * i / 4
            self.create_line(0, y, w, y, fill=self.P["grid"])
        for i in range(1, 6):
            x = w * i / 6
            self.create_line(x, pad_top, x, h - pad_bot,
                             fill=self.P["grid"])
            label = f"-{span * (1 - i / 6):.0f}s" if self.mode == "live" \
                else f"{t0 + span * i / 6 - (self.full or (0,))[0]:.0f}s"
            self.create_text(x, h - 10, text=label, fill=self.P["muted"],
                             font=("Segoe UI", 8))

        # pass 1: data lines (visible series only)
        curs = {}
        for key in self.order:
            s = self.series[key]
            pts = [(t, v) for t, v in s["points"] if t0 <= t <= t1]
            cur = s["points"][-1][1] if s["points"] else None
            if self.cursor is not None and s["points"]:
                cur = min(s["points"],
                          key=lambda p: abs(p[0] - self.cursor))[1]
            curs[key] = cur
            if s["visible"] and len(pts) >= 2:
                vs = [v for _, v in pts]
                vmin, vmax = min(vs), max(vs)
                alert = s["alert"]
                if alert:
                    if alert[0] is not None:
                        vmin = min(vmin, alert[0])
                    if alert[1] is not None:
                        vmax = max(vmax, alert[1])
                vpad = (vmax - vmin) * 0.08 or 0.5
                vmin, vmax = vmin - vpad, vmax + vpad

                def xy(p):
                    return ((p[0] - t0) / span * w,
                            pad_top + plot_h
                            * (1 - (p[1] - vmin) / (vmax - vmin)))

                # draw in chunks so abnormal segments can be red
                prev = pts[0]
                for p in pts[1:]:
                    bad = False
                    if alert:
                        lo, hi = alert
                        for v in (prev[1], p[1]):
                            if (lo is not None and v < lo) or \
                               (hi is not None and v > hi):
                                bad = True
                    x1, y1 = xy(prev)
                    x2, y2 = xy(p)
                    self.create_line(
                        x1, y1, x2, y2, width=2,
                        fill=ALERT_COLOR if bad else s["color"],
                        dash=(4, 3) if s["dash"] else None)
                    prev = p

        # pass 2: legend, drawn on top (clickable: toggles visibility)
        legend_y = pad_top + 4
        for key in self.order:
            s = self.series[key]
            cur = curs.get(key)
            tag = f"leg:{key}"
            cur_txt = f"{cur:,.1f}".rstrip("0").rstrip(".") \
                if isinstance(cur, (int, float)) else "—"
            label = f"{s['label']}: {cur_txt}" if s["visible"] \
                else f"{s['label']}  (hidden)"
            # invisible-ish backing strip so the whole row is clickable
            self.create_rectangle(
                6, legend_y - 2, 30 + 7 * len(label), legend_y + 12,
                fill=self.P["chartbg"], outline="", tags=(tag,))
            if s["visible"]:
                self.create_rectangle(8, legend_y, 20, legend_y + 10,
                                      fill=s["color"], outline="",
                                      tags=(tag,))
            else:
                self.create_rectangle(8, legend_y, 20, legend_y + 10,
                                      fill="", outline=s["color"],
                                      tags=(tag,))
            self.create_text(
                26, legend_y + 5, anchor="w", text=label,
                fill=self.P["fg"] if s["visible"] else self.P["muted"],
                font=("Segoe UI", 9), tags=(tag,))
            legend_y += 16

        # playback cursor
        if self.cursor is not None and self.mode == "static":
            x = (self.cursor - t0) / span * w
            if 0 <= x <= w:
                self.create_line(x, pad_top, x, h - pad_bot,
                                 fill="#ffffff", width=1, dash=(2, 2))
