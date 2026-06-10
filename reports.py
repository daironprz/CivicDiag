"""
Report & export generation.

A "session" is a plain dict assembled by the app:
  vehicle   — dict: adapter, protocol, port, battery, obd_standard, vin, ...
  codes     — list of dicts from obd_data.dtc_info() + "kind" stored/pending
  freeze    — list of (parameter, value, unit)
  readiness — list of (monitor, supported, complete)
  snapshot  — list of (parameter, value, unit, min, max, avg)
  events    — list of (iso_time, text)
  notes     — free text
  timestamp — iso string
  duration  — seconds of live logging, optional

HTML reports are self-contained, print-friendly, and open in the
default browser (Ctrl+P → "Save as PDF" gives a PDF).
"""

import html
import json
from datetime import datetime

SEV_COLORS = {1: "#2a9d2a", 2: "#d99a00", 3: "#e06000", 4: "#cc2222"}

REPORT_TITLES = {
    "check": "Check-Engine Diagnostic Report",
    "presmog": "Pre-Smog Readiness Report",
    "mechanic": "Mechanic Diagnostic Report",
    "beforeafter": "Before / After Repair Report",
    "share": "Diagnostic Summary",
}


def auto_name(session, ext, prefix="CivicDiag"):
    """CivicDiag_2026-06-09_P1456.csv style file names."""
    date = datetime.now().strftime("%Y-%m-%d_%H%M")
    tag = ""
    stored = [c["code"] for c in session.get("codes", [])
              if c.get("kind") == "STORED"]
    if stored:
        tag = "_" + stored[0]
    return f"{prefix}_{date}{tag}.{ext}"


def empty_session():
    return {"vehicle": {}, "codes": [], "freeze": [], "readiness": [],
            "snapshot": [], "events": [], "notes": "",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "duration": None}


# ---------------------------------------------------------------------
# Plain text / CSV / JSON
# ---------------------------------------------------------------------

def session_to_txt(s):
    L = ["=" * 64, "CivicDiag — Diagnostic Session",
         f"Saved: {s['timestamp']}", "=" * 64, ""]
    if s["vehicle"]:
        L.append("VEHICLE / CONNECTION")
        for k, v in s["vehicle"].items():
            L.append(f"  {k:14} {v}")
        L.append("")
    L.append("TROUBLE CODES")
    if s["codes"]:
        for c in s["codes"]:
            L.append(f"  [{c.get('kind', '?'):7}] {c['code']}  "
                     f"({c['severity_name']})  {c['desc']}")
            if c.get("drive"):
                L.append(f"            Drive: {c['drive']}")
    else:
        L.append("  none read / no codes")
    L.append("")
    if s["freeze"]:
        L.append("FREEZE FRAME")
        for name, val, unit in s["freeze"]:
            L.append(f"  {name:38} {val} {unit}")
        L.append("")
    if s["readiness"]:
        L.append("READINESS MONITORS")
        for name, sup, comp in s["readiness"]:
            state = "not supported" if not sup else \
                ("READY" if comp else "NOT READY")
            L.append(f"  {name:32} {state}")
        L.append("")
    if s["snapshot"]:
        L.append("LIVE DATA SNAPSHOT (value / min / max / avg)")
        for name, val, unit, mn, mx, avg in s["snapshot"]:
            L.append(f"  {name:34} {val} {unit}   "
                     f"[{mn} … {mx}, avg {avg}]")
        L.append("")
    if s["events"]:
        L.append("EVENTS")
        for t, txt in s["events"]:
            L.append(f"  {t}  {txt}")
        L.append("")
    if s["notes"]:
        L.append("NOTES")
        L.append("  " + s["notes"].replace("\n", "\n  "))
    return "\n".join(L)


def codes_to_csv(s):
    rows = ["type,code,severity,description"]
    for c in s["codes"]:
        desc = c["desc"].replace('"', "'")
        rows.append(f"{c.get('kind', '')},{c['code']},"
                    f"{c['severity_name']},\"{desc}\"")
    return "\n".join(rows)


def session_to_json(s):
    return json.dumps(s, indent=2, default=str)


def codes_to_clipboard_text(s):
    if not s["codes"]:
        return "No trouble codes."
    return "\n".join(f"{c['code']} ({c.get('kind', '?').lower()}) — "
                     f"{c['desc']}" for c in s["codes"])


# ---------------------------------------------------------------------
# HTML reports
# ---------------------------------------------------------------------

_CSS = """
body{font-family:'Segoe UI',Arial,sans-serif;color:#1a1d21;margin:32px;
     max-width:880px}
h1{font-size:22px;border-bottom:3px solid #cc2222;padding-bottom:6px}
h2{font-size:15px;margin-top:26px;color:#333}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px}
th{background:#f0f2f5;text-align:left;padding:6px 8px;font-size:12px;
   color:#555}
td{padding:6px 8px;border-bottom:1px solid #e4e8ee;vertical-align:top}
.sev{font-weight:600;padding:1px 8px;border-radius:9px;color:#fff;
     font-size:11px;white-space:nowrap}
.muted{color:#777;font-size:12px}
.ok{color:#2a9d2a;font-weight:600}.bad{color:#cc2222;font-weight:600}
.verdict{padding:12px 16px;border-radius:8px;font-size:15px;
         font-weight:600;margin:14px 0}
.pass{background:#e7f6e7;color:#1e7e1e}.fail{background:#fdecea;
      color:#b3261e}
ul{margin:4px 0 4px 18px;padding:0}li{margin:2px 0}
@media print{.noprint{display:none}}
"""


def _esc(x):
    return html.escape(str(x))


def _codes_table(codes, detail=True):
    if not codes:
        return "<p class='ok'>No trouble codes stored. ✔</p>"
    rows = []
    for c in codes:
        sev = (f"<span class='sev' style='background:"
               f"{SEV_COLORS.get(c['severity'], '#888')}'>"
               f"{_esc(c['severity_name'])}</span>")
        extra = ""
        if detail:
            cells = []
            if c.get("drive"):
                cells.append(f"<b>Safe to drive?</b> {_esc(c['drive'])}")
            if c.get("causes"):
                cells.append("<b>Common causes:</b><ul>" + "".join(
                    f"<li>{_esc(x)}</li>" for x in c["causes"]) + "</ul>")
            if c.get("check"):
                cells.append("<b>Check first:</b><ul>" + "".join(
                    f"<li>{_esc(x)}</li>" for x in c["check"]) + "</ul>")
            if cells:
                extra = ("<tr><td></td><td colspan='3' class='muted'>"
                         + "<br>".join(cells) + "</td></tr>")
        rows.append(
            f"<tr><td><b>{_esc(c['code'])}</b></td>"
            f"<td>{_esc(c.get('kind', ''))}</td><td>{sev}</td>"
            f"<td>{_esc(c['desc'])}</td></tr>{extra}")
    return ("<table><tr><th>Code</th><th>Status</th><th>Severity</th>"
            "<th>Description</th></tr>" + "".join(rows) + "</table>")


def _kv_table(rows, headers):
    if not rows:
        return "<p class='muted'>No data captured.</p>"
    out = ["<table><tr>" + "".join(f"<th>{_esc(h)}</th>" for h in headers)
           + "</tr>"]
    for r in rows:
        out.append("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r)
                   + "</tr>")
    return "".join(out) + "</table>"


def _readiness_html(readiness):
    rows = []
    for name, sup, comp in readiness:
        if not sup:
            state = "<span class='muted'>not supported</span>"
        elif comp:
            state = "<span class='ok'>✔ Ready</span>"
        else:
            state = "<span class='bad'>✘ Not ready</span>"
        rows.append((name, state))
    out = ["<table><tr><th>Monitor</th><th>Status</th></tr>"]
    for name, state in rows:
        out.append(f"<tr><td>{_esc(name)}</td><td>{state}</td></tr>")
    return "".join(out) + "</table>"


def _smog_verdict(s):
    stored = [c for c in s["codes"] if c.get("kind") == "STORED"]
    not_ready = [n for n, sup, comp in s["readiness"] if sup and not comp]
    if stored:
        return ("fail", "LIKELY FAIL — stored trouble codes present: "
                + ", ".join(c["code"] for c in stored))
    if len(not_ready) > 1:
        return ("fail", "NOT READY — monitors incomplete: "
                + ", ".join(not_ready)
                + ". (1996-1999 vehicles are typically allowed ONE "
                  "incomplete monitor.)")
    if len(not_ready) == 1:
        return ("pass", f"LIKELY PASS — one incomplete monitor "
                f"({not_ready[0]}), which is typically allowed for a 1999 "
                "vehicle. No stored codes.")
    if not s["readiness"]:
        return ("fail", "UNKNOWN — readiness was not read.")
    return ("pass", "LIKELY PASS — no stored codes, all supported monitors "
                    "ready.")


def build_html(s, kind, baseline=None):
    title = REPORT_TITLES.get(kind, "Diagnostic Report")
    B = [f"<!doctype html><html><head><meta charset='utf-8'>"
         f"<title>{_esc(title)}</title><style>{_CSS}</style></head><body>",
         "<div class='noprint' style='text-align:right'>"
         "<button onclick='window.print()'>🖨 Print / Save as PDF</button>"
         "</div>",
         f"<h1>{_esc(title)}</h1>",
         f"<p class='muted'>1999 Honda Civic · generated by CivicDiag · "
         f"{_esc(s['timestamp'])}</p>"]

    if kind == "share":
        B.append("<p>Hi — I scanned my 1999 Honda Civic with an OBD-II "
                 "reader. Here's what it found, so you have a head start "
                 "before I bring it in.</p>")

    if s["vehicle"]:
        B.append("<h2>Vehicle / connection</h2>")
        B.append(_kv_table([(k, v) for k, v in s["vehicle"].items()],
                           ("Item", "Value")))

    if kind == "presmog":
        cls, verdict = _smog_verdict(s)
        B.append(f"<div class='verdict {cls}'>{_esc(verdict)}</div>")
        B.append("<h2>Readiness monitors</h2>")
        B.append(_readiness_html(s["readiness"]))
        B.append("<h2>Trouble codes</h2>")
        B.append(_codes_table(s["codes"], detail=False))
    elif kind == "beforeafter" and baseline is not None:
        b_codes = {c["code"] for c in baseline["codes"]}
        a_codes = {c["code"] for c in s["codes"]}
        fixed = sorted(b_codes - a_codes)
        remaining = sorted(b_codes & a_codes)
        new = sorted(a_codes - b_codes)
        B.append(f"<p class='muted'>Baseline (before): "
                 f"{_esc(baseline['timestamp'])} — Current (after): "
                 f"{_esc(s['timestamp'])}</p>")
        B.append("<h2>Result</h2><table>"
                 "<tr><th>Codes fixed</th><th>Still present</th>"
                 "<th>New codes</th></tr><tr>"
                 f"<td class='ok'>{_esc(', '.join(fixed) or '—')}</td>"
                 f"<td class='bad'>{_esc(', '.join(remaining) or '—')}</td>"
                 f"<td class='bad'>{_esc(', '.join(new) or '—')}</td>"
                 "</tr></table>")
        B.append("<h2>Codes before repair</h2>")
        B.append(_codes_table(baseline["codes"], detail=False))
        B.append("<h2>Codes after repair</h2>")
        B.append(_codes_table(s["codes"], detail=False))
        B.append("<h2>Readiness now</h2>")
        B.append(_readiness_html(s["readiness"]))
    else:
        B.append("<h2>Trouble codes</h2>")
        B.append(_codes_table(s["codes"], detail=(kind != "mechanic")))
        if s["freeze"]:
            B.append("<h2>Freeze frame (conditions when the code set)</h2>")
            B.append(_kv_table(s["freeze"],
                               ("Parameter", "Value", "Unit")))
        if s["readiness"]:
            B.append("<h2>Readiness monitors</h2>")
            B.append(_readiness_html(s["readiness"]))
        if s["snapshot"]:
            B.append("<h2>Live data snapshot</h2>")
            B.append(_kv_table(s["snapshot"],
                               ("Parameter", "Value", "Unit", "Min", "Max",
                                "Avg")))

    if s["events"]:
        B.append("<h2>Logged events</h2>")
        B.append(_kv_table(s["events"], ("Time", "Event")))
    if s["notes"]:
        B.append("<h2>Notes</h2><p>" + _esc(s["notes"]).replace("\n", "<br>")
                 + "</p>")
    B.append("<p class='muted'>Engine/transmission data only — ABS and SRS "
             "on a 1999 Civic are read via blink codes at the service "
             "connector, not OBD-II.</p>")
    B.append("</body></html>")
    return "".join(B)
