"""Scripted GUI smoke test: demo-connect, live data, DTC read."""
import sys

import prefs

# avoid the first-run welcome dialog during the scripted test
p = prefs.load_prefs()
p["first_run_done"] = True
prefs.save_prefs(p)

import main  # noqa: E402

app = main.App()
results = {}


def step_connect():
    app._connect_demo()
    app.after(4000, step_check_connected)


def step_check_connected():
    results["connected"] = app.elm is not None and app.elm.connected
    results["pids"] = len(app.supported_pids)
    app._run_bg(app._read_dtcs)
    app._start_live()
    app._chart_live()
    app.after(4000, step_check_live)


def step_check_live():
    results["live"] = app.live_running
    results["codes"] = [c["code"] for c in app.session["codes"]]
    results["latest_rpm"] = app.latest.get(0x0C)
    results["readiness"] = len(app.session["readiness"])
    chart_pts = sum(len(s["points"]) for s in app.chart.series.values())
    results["chart_points"] = chart_pts
    app._stop_live()
    app.after(300, app.destroy)


app.after(800, step_connect)
app.mainloop()

print(results)
ok = (results.get("connected") and results.get("live")
      and results.get("codes") == ["P1456", "P0133"]
      and results.get("latest_rpm") is not None
      and results.get("readiness", 0) >= 10
      and results.get("chart_points", 0) > 0)
print("SMOKE TEST", "PASSED" if ok else "FAILED")
sys.exit(0 if ok else 1)
