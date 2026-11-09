"""Stub runner for the window's checks: plays the runner's event contract, reads the window's commands from stdin.

Not the real runner. Made-up project and block names only.

    python stub_runner.py --scenario ok|fail|cancel|ask-safety|ask-umc|crash|hang [--speed 0.2] [--record DIR]
                          run --before A --after B [--git REPO] [--title T] [--compile] [--safety] [--hmi] [--no-cache]

--record DIR: writes DIR/commands.jsonl (commands as received, passwords replaced by their length), DIR/argv.json,
DIR/tia_pid.txt (hang), and the report of an ok run (DIR/run/report.html).
"""
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time

commands = queue.Queue()
cancelled = False


def emit(**event):
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def read_stdin(record):
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except ValueError:
            print("stub: not JSON on stdin: %r" % line, file=sys.stderr)
            continue
        if record:
            shown = dict(cmd)
            if "password" in shown:   # the check gives the expected one in STUB_EXPECT_PASSWORD
                shown["password"] = "<%d chars>" % len(cmd["password"])
                shown["password_matches"] = cmd["password"] == os.environ.get("STUB_EXPECT_PASSWORD")
            with open(os.path.join(record, "commands.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(shown) + "\n")
        commands.put(cmd)


def poll_cancel():
    global cancelled
    while not cancelled:
        try:
            cmd = commands.get_nowait()
        except queue.Empty:
            break
        if cmd.get("t") == "cancel":
            cancelled = True
    return cancelled


def wait_answer(ask_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        try:
            cmd = commands.get(timeout=0.1)
        except queue.Empty:
            continue
        if cmd.get("t") == "cancel":
            global cancelled
            cancelled = True
            return None
        if cmd.get("t") == "answer" and cmd.get("id") == ask_id:
            return cmd
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="ok")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--record")
    ap.add_argument("cmd")
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--git")
    ap.add_argument("--title")
    ap.add_argument("--compile", action="store_true")
    ap.add_argument("--safety", action="store_true")
    ap.add_argument("--hmi", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()
    if a.record:
        os.makedirs(a.record, exist_ok=True)
        with open(os.path.join(a.record, "argv.json"), "w", encoding="utf-8") as f:
            json.dump(sys.argv[1:], f)
    threading.Thread(target=read_stdin, args=(a.record,), daemon=True).start()

    def nap(seconds):
        time.sleep(seconds * a.speed)

    sides = [("A", a.before), ("B", a.after)]
    plan = [("check", "Check this PC")]
    for side, _ in sides:
        plan += [("cache" + side, "Look up the cache (%s)" % side), ("start" + side, "Start TIA in the background (%s)" % side),
                 ("open" + side, "Unpack and open archive %s" % side)]
        if a.compile:
            plan.append(("compile" + side, "Compile the copy %s" % side))
        plan += [("export" + side, "Export project %s%s" % (side, " and its HMI" if a.hmi else "")),
                 ("close" + side, "Close TIA (%s)" % side)]
    plan.append(("report", "Compare and write the report"))
    emit(t="plan", steps=[{"id": i, "text": t} for i, t in plan])

    sleeper = None
    prompts = 0
    done_steps = set()
    failed = None

    for sid, text in plan:
        if failed or poll_cancel():
            emit(t="step", id=sid, state="skipped")
            continue
        last = {"open": 41000, "start": 9800, "close": 8000, "report": 14000}.get(sid.rstrip("AB"))
        ev = dict(t="step", id=sid, state="running")
        if last:
            ev["last_ms"] = last
        emit(**ev)
        t0 = time.time()
        kind = sid.rstrip("AB") if sid != "report" else "report"
        if kind == "check":
            emit(t="log", level="info", text="TIA Portal V20 found; member of the Openness group; 212 GB free")
            nap(0.4)
        elif kind == "cache":
            emit(t="log", level="info", text="No export kept for this archive; exporting it")
            nap(0.2)
        elif kind == "start":
            # as the runner passes TiaBridge's diagnostics on: hidden unless "Show details"
            print("bridge: [tiabridge 12:00:00] background start: 8048 ms, TIA working set 1450 MB", file=sys.stderr)
            sys.stderr.flush()
            if sleeper is None:
                sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"],
                                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if a.record:
                    with open(os.path.join(a.record, "tia_pid.txt"), "w") as f:
                        f.write(str(sleeper.pid))
            emit(t="tia", pid=sleeper.pid)
            nap(1.5)
        elif kind == "open":
            if a.scenario == "ask-umc" and sid == "openA":
                emit(t="ask", id="umc-1", kind="umc_login", project="Line7_Conveyor")
                ans = wait_answer("umc-1")
                if ans is None or ans.get("skip"):
                    failed = "The project is protected (UMC) and no login was given."
                else:
                    emit(t="log", level="info", text="Logged in to the project as %s" % ans.get("user"))
            if a.scenario == "fail" and sid == "openA":
                nap(1.0)
                emit(t="log", level="error", text="Siemens.Engineering.EngineeringSecurityException: Access denied (sample text)")
                failed = "Your Windows user may not use TIA Openness. Ask IT to add you to the group 'Siemens TIA Openness', then sign out and in again."
            elif a.scenario == "hang" and sid == "openA":
                emit(t="log", level="info", text="Opening (this stub ignores cancel now)")
                time.sleep(600)
            else:
                nap(2.5)
            if not failed and sid == "openB":
                emit(t="prompt", text="The project was created with an older library version. Upgrade?", answer="No")
                prompts += 1
        elif kind == "compile":
            if a.safety and sid == "compileA" and a.scenario == "ask-safety":
                emit(t="ask", id="safety-1", kind="safety_password", project="Line7_Conveyor",
                     hint="Fake TIA: the sample password is safe-1.")
                ans = wait_answer("safety-1")
                emit(t="log", level="info", text="Safety program: " + ("skipped" if ans is None or ans.get("skip") else "logged in"))
            nap(1.0)
        elif kind == "export":
            total = 40
            for i in range(1, total + 1):
                if poll_cancel():
                    break
                nap(0.06)
                emit(t="progress", id=sid, done=i, total=total, item="blocks: FB_Conveyor_%03d" % i)
                if i % 10 == 0:
                    emit(t="log", level="info", text="exported %d of %d" % (i, total))
            for i in range(1, (24 if a.hmi else 0) + 1):
                if poll_cancel():
                    break
                nap(0.12)
                emit(t="progress", id=sid, done=i, total=24, item="HMI screens of Panel_1: Conveyor_%02d" % i)
            if a.scenario == "crash" and sid == "exportA":
                print("Traceback (most recent call last):", file=sys.stderr)
                print("  File \"stub_runner.py\", line 1, in <module>", file=sys.stderr)
                print("RuntimeError: stub crash", file=sys.stderr)
                sys.stderr.flush()
                if sleeper:
                    sleeper.kill()
                os._exit(3)
        elif kind == "close":
            nap(0.6)
        elif kind == "report":
            nap(1.2)
        ms = int((time.time() - t0) * 1000)
        if failed:
            emit(t="step", id=sid, state="failed", ms=ms, error=failed)
        elif cancelled:
            emit(t="step", id=sid, state="cancelled", ms=ms)
            emit(t="log", level="warn", text="Cancelled after the current TIA call; closing TIA and deleting the copy")
        else:
            emit(t="step", id=sid, state="done", ms=ms)
            done_steps.add(sid)

    if sleeper:
        sleeper.kill()
    if cancelled:
        emit(t="end", ok=False, cancelled=True)
    elif failed:
        emit(t="end", ok=False, error="The comparison stopped at a step that failed.")
    else:
        folder = os.path.join(a.record or os.environ.get("TEMP", "."), "run")
        os.makedirs(folder, exist_ok=True)
        report = os.path.join(folder, "report.html")
        with open(report, "w", encoding="utf-8") as f:
            f.write("<!doctype html><title>stub report</title><p>stub</p>")
        not_exported = [{"name": "FB_Recipe_Secret", "why": "know-how protected"},
                        {"name": "FB_Dosing_03", "why": "not compiled"},
                        {"name": "F_Main_Safety", "why": "F-system block"}]
        if a.hmi:
            not_exported.append({"name": "Conveyor_Diag (HMI screen, Panel_1)",
                                 "why": "A: TIA did not export it (sample text)"})
        emit(t="end", ok=True, report=report, folder=folder, changed=10 if a.hmi else 7, not_exported=not_exported)


if __name__ == "__main__":
    main()
