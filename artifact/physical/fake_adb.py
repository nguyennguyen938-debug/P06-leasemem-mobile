#!/usr/bin/env python3
"""E7: a fake `adb` for dry runs of physical/campaign.py without a phone. Not a model of Android: it answers the
commands the drivers send with fixed, plausible values, keeps a little device state (users, installed apps, running
processes, app files, settings, battery and Doze overrides) in $FAKE_ADB_STATE, and logs every command to
$FAKE_ADB_LOG together with the verdict of the guard (lmdrv.phone_violation) for user 10 (user 0 with FAKE_MODE=aws), so a dry
run shows exactly what would reach the phone. `adb forward` starts a small TCP server (this file with --serve) that
answers the client's loopback ops used by revision/run.py and b7_continuous.py. Failure injection for the restore
checks: a shell command matching $FAKE_FAIL exits 1 with an error and changes nothing; one matching $FAKE_IGNORE
exits 0 and changes nothing (a silent failure). $FAKE_RUNAS_FAIL=<message> makes every run-as fail with that message,
visible only through 2>&1 (as on a phone, where run-as reports on stderr).
Use through physical/e7_dryrun.py (it sets ADB to this file, so lmdrv runs it with the Python interpreter).
"""
import json, os, re, socket, socketserver, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "driver"))
os.environ.pop("P06_FAKE_TIME", None)     # the fake device keeps real time (plus its own clock offset)
import lmdrv

# FAKE_MODE=aws: a wiped Device Farm phone (only user 0, no restrictions); otherwise a personal phone with user 10.
AWS = os.environ.get("FAKE_MODE") in ("aws", "lab")        # lab: a wiped lab phone, user 0, nothing preinstalled
DF = os.environ.get("FAKE_MODE") == "aws"
SERIAL, USER, APPID = os.environ.get("FAKE_SERIAL", "FAKE0001"), 0 if AWS else 10, 10123
UID = USER * 100000 + APPID
STATE = Path(os.environ.get("FAKE_ADB_STATE", "fake-adb-state.json"))
LOG = Path(os.environ.get("FAKE_ADB_LOG", "fake-adb-log.jsonl"))
LOCK = STATE.with_suffix(".lock")
PKGS = {"LeaseMemClient-v4": "org.leasemem.client", "LeaseMemMut": "org.leasemem.mut",
        "LeaseMemTrig": "org.leasemem.trig", "LeaseMemAssist": "org.leasemem.assist"}
PROPS = {"ro.serialno": os.environ.get("FAKE_SERIALNO", SERIAL), "ro.product.manufacturer": "Fake", "ro.product.model": "P06Phone", "ro.product.device": "p06",
         "ro.build.fingerprint": "fake/p06/p06:14/FAKE.1/1:user/release-keys", "ro.build.version.sdk": "34",
         "ro.build.version.release": "14", "ro.build.type": "user", "ro.debuggable": "0",
         "ro.build.version.security_patch": "2026-10-01", "sys.boot_completed": "1", "service.adb.tls.port": "37000"}
FACTS = ["c.dana", "c.omar", "c.set", "l.latest", "l.missed", "m.latest", "m.tracked", "k.standup", "k.set", "g.mode", "g.target", "f.todo", "f.list"]


def lock():
    for _ in range(4000):
        try:
            os.mkdir(LOCK); return
        except FileExistsError:
            time.sleep(0.005)
    raise RuntimeError("fake adb lock timeout")


def load():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    # AWS: Device Farm has already installed its re-signed copy of the app under test (B0 run e035a924, 2026-11-18)
    return {"cur": USER, "running": {}, "next_pid": 4000, "files": {}, "installed": [PKGS["LeaseMemClient-v4"]] if DF else [],
            "resigned": [PKGS["LeaseMemClient-v4"]] if DF else [], "fgs": False, "fg_app": False,
            "frozen": False, "dc": {}, "sync": "none", "settings": {}, "bucket": {}, "grants": {}, "role": None,
            "battery_override": None, "battery_calls": 0, "deep": "ACTIVE", "awake": True, "clock_ms": 0, "back_after": 0}


def save(s):
    tmp = STATE.with_suffix(".tmp"); tmp.write_text(json.dumps(s), encoding="utf-8"); os.replace(tmp, STATE)


def now(s):
    return int(time.time() * 1000) + s["clock_ms"]


def start(s, pkg):
    if pkg not in s["running"]:
        s["running"][pkg] = s["next_pid"]; s["next_pid"] += 1
    return s["running"][pkg]


def plugged(s):
    if s["battery_override"] is not None:
        return False
    at = os.environ.get("FAKE_UNPLUG_AT")
    return not (at and s["battery_calls"] >= int(at))


def client_reply(s, cmd, rid, extras):
    t = now(s); pid = start(s, "org.leasemem.client")
    r = {"cmd": cmd, "id": rid, "t_recv": t, "epoch": "fakeep01", "pid": pid, "observers": True}
    if cmd == "DECIDE":
        r.update(facts={f: {"lm": "FRESH", "ev": "FRESH", "gl": "FRESH", "mem": "v", "truth": "v", "lm_hist": "FRESH", "lmts_hist": "FRESH"} for f in FACTS},
                 lm_hist_cost={"contacts": {"ns": 1000, "reason": "wm_equal"}}, lmts_hist_cost={"contacts": {"ns": 1000, "reason": "wm_equal"}},
                 wm_obs={"contacts": "V1", "contacts@VER": "V1"}, wm_now={"contacts": "V1", "contacts@VER": "V1"},
                 # client v4 on a phone: strict EvCheck, lm_cost keyed by fact with a verdict (B2 part 2, B10 run 7ffc578c)
                 lm_cost={f: {"verdict": "UNKNOWN", "reason": "strict_epoch_and_snapshot_unavailable", "fact": f} for f in FACTS},
                 events=[], fg=s["fgs"], clock_jump=False, broken=False)
    elif cmd == "PROBE":
        r["probe"] = {"contacts.count": "2", "calllog.max_id": "3", "media.generation": "7", "facts": {}}
    elif cmd == "PING":
        r.update(last_start={"pid": pid, "epoch": "fakeep01"}, n_events=0)
    elif cmd == "ACT":
        r.update(check2_start=t + 2480, check2_end=t + 2490,      # as LmApp.act() reports them (G15 reads check-to-effect)
                 effect_start=t + 2500, effect_end=t + 2510, used="+15551110000", stale=False, mode=extras.get("mode"),
                 validator="hist" if extras.get("validator") == "hist" else "strict",
                 effect_store=extras.get("effect", "calllog"))
        if extras.get("effect") == "contacts":           # the effect row of "P06 Effect Log", as the client writes it
            s.setdefault("effects", {})[rid] = ["+15551110000", t + 2510]
    return r


def mut_reply(s, op, a, b):
    t = now(s); excl = s["files"].get("org.leasemem.mut/files/p06_exclude", "").split()
    if op in ("mutate", "mutate_at") and a in excl or op == "sms_reuse" and "sms" in excl:
        return {"ok": False, "error": "source excluded on this device: %s" % (a or "sms"), "t_pre": t, "t_post": t}
    r = {"ok": True, "t_pre": t, "t_post": t + 5, "did": "upd n=1" if op != "ensure" else None}
    if op == "ensure":
        r["made"] = 0; s["settings"].setdefault("lm_mode", "v0"); s["settings"].setdefault("lm_target", "v0")
    if op == "mutate_at":
        r.update(mut_start=t, mut_end=t + 5)
    return r


def extras_of(cmd):
    return {k: v.strip("'") for k, v in re.findall(r"--e[sl] (\S+) ('[^']*'|\S+)", cmd)}


def one(s, c):
    """Answer one simple shell command."""
    c = c.strip()
    m = re.fullmatch(r"getprop (\S+)", c)
    if m:
        return PROPS.get(m.group(1), "")
    if c in ("id -u",):
        return "2000"
    if c == "cat /proc/sys/kernel/random/boot_id":       # changes on every `adb reboot`
        return "fake-boot-%d" % s.get("boots", 0)
    if c == "pm list users":
        return "Users:\n\tUserInfo{0:Owner:c13} running" + ("" if AWS else "\n\tUserInfo{10:P06 Test:410} running")
    if c == "am get-current-user":
        if s["cur"] != USER and s["back_after"] > 0:
            s["back_after"] -= 1
            if s["back_after"] == 0:
                s["cur"] = USER                       # the "user" switched back to P06 Test after the reboot
        return str(s["cur"])
    if c.startswith("am get-started-user-state"):
        return "RUNNING_UNLOCKED" if s["cur"] == USER else "RUNNING_LOCKED"
    if c == "date +%s%3N":
        s["clock_ms"] += 10000; return str(now(s))
    m = re.fullmatch(r"pidof (\S+)", c)
    if m:
        return str(s["running"].get(m.group(1), ""))
    m = re.fullmatch(r"stat -c %u /proc/(\d+)", c)
    if m:
        return str(UID)
    if re.fullmatch(r"cat /proc/\d+/oom_score_adj.*", c):
        return "0" if s["fg_app"] or s["fgs"] else "905"
    if c.startswith("cat /proc/") or c.startswith("cat /sys/"):
        return "cat: Permission denied" if "2>&1" in c else ""
    m = re.fullmatch(r"dumpsys activity processes (\S+)", c)
    if m:
        p = m.group(1); pid = s["running"].get(p)
        return "  *APP* UID %d ProcessRecord{a1 %s:%s/u10a123}\n    isFreezeExempt=false isPendingFreeze=false isFrozen=%s\n" % (
            UID, pid, p, "true" if s["frozen"] else "false") if pid else ""
    if c.startswith("dumpsys activity settings"):        # a unit with the freezer off until cached_apps_freezer=enabled
        on = s["settings"].get("cached_apps_freezer") == "enabled"
        if "grep use_freezer" in c:
            return "  use_freezer=%s" % ("true" if on else "false")
        return "  use_freezer=%s\n  freeze_debounce_timeout=%s" % ("true" if on else "false",
                                                                 s["dc"].get("activity_manager_native_boot/freeze_debounce_timeout", "600000"))
    if c.startswith("dumpsys activity services"):
        return "  isForeground=true" if s["fgs"] else ""
    if c.startswith("dumpsys -t "):                     # lmdrv.DUMP_PKG: dumpsys's own timeout, stderr folded in
        c = re.sub(r"^dumpsys -t \d+ ", "dumpsys ", c); c = c[:-5] if c.endswith(" 2>&1") else c
    if c.startswith("dumpsys package"):
        g = s["grants"].get(c.split()[-1] + "/android.permission.READ_CONTACTS", True)
        return "    runtime permissions:\n      android.permission.READ_CONTACTS: granted=%s" % ("true" if g else "false")
    if c.startswith("dumpsys batterystats --charged"):  # before "dumpsys battery", which is its prefix
        return "    Uid u%da123: 0.42 ( cpu=0.40 )" % USER
    if c.startswith("dumpsys battery"):
        if c == "dumpsys battery unplug":
            s["battery_override"] = "unplug"; return ""
        if c == "dumpsys battery reset":
            s["battery_override"] = None; return ""
        s["battery_calls"] += 1; pl = plugged(s)
        return ("  AC powered: false\n  USB powered: %s\n  Wireless powered: false\n  level: 80\n  Charge counter: 3000000\n"
                "  voltage: 4000\n  temperature: 300" % ("true" if pl else "false"))
    if c.startswith("dumpsys deviceidle"):
        if "force-idle" in c or "step" in c:
            s["deep"] = "IDLE"; return "Now forced in to deep idle mode"
        if "unforce" in c:
            s["deep"] = "ACTIVE"; return ""
        if "get" in c:
            return s["deep"]
        return ""
    if c.startswith("dumpsys power"):
        return "  mWakefulness=%s" % ("Awake" if s["awake"] else "Asleep")
    if c.startswith("dumpsys voiceinteraction"):
        return "    mBound=true\n    mComponent=org.leasemem.assist/.Svc" if s["role"] else ""
    if c.startswith("dumpsys batterystats --charged"):
        return "    Uid u%da123: 0.42 ( cpu=0.40 )" % USER
    if re.match(r"date @\d+", c):                     # an unrooted phone: the shell may not set the clock
        return "date: cannot set date: Operation not permitted"
    if c.startswith("cmd alarm set-time"):           # allowed on Device Farm's Pixel 8 (B0 run 1c18f498)
        if not AWS:
            return "Security exception: Caller is not allowed to set the time"
        s["clock_ms"] = int(c.split()[-1]) - int(time.time() * 1000); return ""
    m = re.fullmatch(r"device_config (get|put|delete) (\S+) (\S+)(?: (\S+))?", c)
    if m:
        k = m.group(2) + "/" + m.group(3)
        if m.group(1) == "get":
            return s["dc"].get(k, "null")
        if m.group(1) == "put":
            s["dc"][k] = m.group(4)
        else:
            s["dc"].pop(k, None)
        return ""
    m = re.fullmatch(r"device_config (set|get)_sync_disabled_for_tests ?(\S*)", c)
    if m:
        if m.group(1) == "get":
            return s["sync"]
        s["sync"] = m.group(2); return ""
    m = re.fullmatch(r"settings (get|put|delete) global (\S+) ?(.*)", c)
    if m:
        if m.group(1) == "get":
            return s["settings"].get(m.group(2), "null")
        if m.group(1) == "put":
            s["settings"][m.group(2)] = m.group(3)
        else:
            s["settings"].pop(m.group(2), None)
        return ""
    m = re.fullmatch(r"input keyevent (\S+)", c)
    if m:
        k = m.group(1)
        if k == "KEYCODE_HOME":
            s["fg_app"] = False
            s["frozen"] = s["dc"].get("activity_manager_native_boot/freeze_debounce_timeout") == "2000" and not s["fgs"]
        s["awake"] = {"KEYCODE_SLEEP": False, "KEYCODE_WAKEUP": True}.get(k, s["awake"])
        return ""
    m = re.match(r"am (\S+) --user %d (.*)" % USER, c)
    if m:
        sub, rest = m.groups(); pkg = re.search(r"(org\.leasemem\.\w+)", rest); pkg = pkg and pkg.group(1)
        if sub == "start":
            start(s, pkg); s["fg_app"] = True; s["frozen"] = False; return "Status: ok"
        if sub == "start-foreground-service":
            start(s, "org.leasemem.client"); s["fgs"] = True; s["frozen"] = False; return ""
        if sub == "stopservice":
            s["fgs"] = False; return ""
        if sub in ("force-stop", "kill"):
            if sub == "force-stop" or not s["fgs"]:
                s["running"].pop(pkg, None)
                if sub == "force-stop":
                    s["fgs"] = False if pkg == "org.leasemem.client" else s["fgs"]
            return ""
        if sub == "set-standby-bucket":
            s["bucket"][pkg] = {"active": "10", "restricted": "45", "working_set": "20", "frequent": "30", "rare": "40"}.get(rest.split()[-1], rest.split()[-1]); return ""
        if sub == "get-standby-bucket":
            return s["bucket"].get(pkg, "10")
        if sub == "broadcast":
            e = extras_of(rest)
            if pkg == "org.leasemem.client":
                s["files"]["%s/files/res_%s.json" % (pkg, e.get("id"))] = json.dumps(client_reply(s, e.get("cmd"), e.get("id"), e))
            elif pkg == "org.leasemem.mut":
                s["files"]["%s/files/done_%s" % (pkg, e.get("id"))] = "R:" + json.dumps(mut_reply(s, e.get("op"), e.get("a"), e.get("b")))
            return "Broadcast completed: result=0"
        return ""
    # run-as as on Android 15: `run-as <pkg> [--user <id>] <cmd>`; `run-as --user 0 <pkg>` reads "--user" as the
    # package (B0 run 19ba952e). Errors go to stderr, seen only with 2>&1.
    m = re.match(r"run-as (\S+)(?: --user (\d+))? (.*?)( 2>&1)?$", c)
    if m:
        pkg, uid_, inner, merged = m.groups()
        err = os.environ.get("FAKE_RUNAS_FAIL") or ("unknown package: --user" if pkg == "--user" else None) \
            or (None if uid_ in (None, str(USER)) else "user %s has no package %s" % (uid_, pkg))
        if err:
            return "run-as: " + err if merged else ""
        if inner == "id":
            return "uid=%d(u10_a123) gid=%d" % (UID, UID)
        if inner == "ls -la files":
            return "\n".join(k.split("/", 1)[1] for k in s["files"] if k.startswith(pkg + "/files/"))
        inner = re.sub(r"^sh -c '(.*)'$", r"\1", inner)
        out = []
        for part in [x.strip() for x in inner.split("&&")]:
            mm = re.fullmatch(r"cat (\S+)( 2>/dev/null)?", part)
            if mm:
                out.append(s["files"].get(pkg + "/" + mm.group(1), "")); continue
            mm = re.fullmatch(r"rm -f (\S+)", part)
            if mm:
                s["files"].pop(pkg + "/" + mm.group(1), None); continue
            mm = re.fullmatch(r": > (\S+)", part)
            if mm:
                s["files"][pkg + "/" + mm.group(1)] = ""; continue
            mm = re.fullmatch(r"mkdir -p (\S+)", part)
            if mm:
                continue
            mm = re.fullmatch(r"echo ([A-Za-z0-9+/=]+) \| base64 -d > (\S+)", part)   # L4: the draft, written as base64
            if mm:
                s["files"][pkg + "/" + mm.group(2)] = __import__("base64").b64decode(mm.group(1)).decode(); continue
            mm = re.fullmatch(r"echo (.*) > (\S+)", part)
            if mm:
                s["files"][pkg + "/" + mm.group(2)] = mm.group(1) + "\n"; continue
            mm = re.fullmatch(r"kill -9 (\d+)", part)
            if mm:
                s["running"] = {k: v for k, v in s["running"].items() if str(v) != mm.group(1)}; continue
        if pkg + "/files/mem.json" not in s["files"] and inner.startswith("cat files/mem.json"):
            return json.dumps({"events": [{"src": "contacts", "t": now(s), "flags": 0}], "last_start": {}})
        return "".join(out)
    if re.match(r"pm list --user ", c):         # as on Android 15: --user goes after `pm list packages` (run 97a66c65)
        return "Error: unknown list type '--user'"
    m = re.match(r"pm (list packages|\S+) --user %d (.*)" % USER, c)
    if m:
        sub, rest = m.groups()
        if sub == "list packages":
            return "\n".join("package:" + p for p in s["installed"])
        if sub in ("grant", "revoke"):
            pkg, perm = rest.split()[:2]; s["grants"][pkg + "/" + perm] = sub == "grant"; return ""
        if sub == "clear":
            return "Success"
        if sub == "uninstall":
            s["installed"] = [p for p in s["installed"] if p != rest.strip()]
            s["resigned"] = [p for p in s.get("resigned", []) if p != rest.strip()]; return "Success"
        return ""
    m = re.match(r"appops (set|get) --user %d (\S+) (\S+)" % USER, c)
    if m:
        return "%s: allow" % m.group(3) if m.group(1) == "get" else ""
    m = re.match(r"cmd role (\S+) --user %d (.*)" % USER, c)
    if m:
        sub, rest = m.groups()
        if sub == "add-role-holder":
            s["role"] = rest.split()[1]
        elif sub == "remove-role-holder":
            s["role"] = None
        return s["role"] or "" if sub == "get-role-holders" else ""
    if c.startswith("content query --user %d" % USER):
        m = re.search(r"leasemem\.effect' AND data2='([^']+)'", c)
        if m:
            e = s.get("effects", {}).get(m.group(1))
            return "Row: 0 data1=%s, data2=%s, data3=%d, raw_contact_id=9" % (e[0], m.group(1), e[1]) if e else "No result found."
        if "raw_contacts --projection _id:version" in c:
            return "Row: 0 _id=1, version=%d" % s.get("dana_version", 3)
        if "phone_v2' AND raw_contact_id IN" in c:
            return "Row: 0 data1=+15551110000"
        if os.environ.get("FAKE_PERSONAL") and "NOT LIKE" in c:     # lab preflight: a phone with someone's data
            return "Row: 0 _id=77"
        return "No result found." if ("NOT LIKE" in c or "IS NOT" in c) else "Row: 0 _id=1\nRow: 1 _id=2"
    return None


def shell(s, cmd):
    if cmd.startswith("for p in $(pidof "):
        pkg = cmd.split()[4].rstrip(");"); pid = s["running"].get(pkg)
        return "%s %d" % (pid, UID) if pid else ""
    if cmd.startswith("p=; for q in $(pidof "):        # B11 sample
        pid = s["running"].get("org.leasemem.client", ""); bat = one(s, "dumpsys battery").splitlines()
        return "\n".join(["pid=%s" % pid, "adj=905", "bucket=10", "cur=%d" % s["cur"], "deep=%s" % s["deep"], "light=ACTIVE"]
                         + [l for l in bat if re.search("powered:|level:|Charge counter:", l)] + ["  mWakefulness=Asleep"])
    if cmd.startswith("dumpsys user | awk"):
        r = os.environ.get("FAKE_RESTRICTIONS", "no_sms,no_outgoing_calls").split(",")
        return "  UserInfo{10:P06 Test:410} serialNo=11\n    Restrictions:\n" + "".join("      %s\n" % x for x in r if x)
    outs = []
    for part in cmd.split(";"):
        r = one(s, part)
        if r is None:
            return None
        outs.append(r)
    return "\n".join(x for x in outs if x)


def ensure_server(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close(); return
    except OSError:
        pass
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([sys.executable, __file__, "--serve", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags, env=os.environ)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close(); return
        except OSError:
            time.sleep(0.05)


def serve(port):
    class H(socketserver.StreamRequestHandler):
        def handle(self):
            for line in self.rfile:
                q = json.loads(line); op = q["op"]; t = time.time_ns(); off = int(time.time() * 1000) - t // 1000000
                if op == "__shutdown__":
                    self.wfile.write(b'{"ok":true}\n'); self.wfile.flush(); os._exit(0)
                if op == "batch":
                    r = {"mode": q["mode"], "values": {f: "+15551110000" if f == "c.dana" else "v" for f in FACTS}, "verdicts": {},
                         "refreshes": len(FACTS), "fact_reads": len(FACTS), "start_ns": t, "end_ns": t + 2000000, "epoch": "fakeep01",
                         "reads": {"c.dana": [t + 100000, t + 400000]}, "wall_offset_ms": off}
                    if q["mode"] == "stamp":
                        r.update(stamp={"contacts": "confirmed", "sms": "no_stamp"}, stamp_reads=4)
                elif op == "effect":
                    r = {"value": q.get("value"), "wall_ms": int(time.time() * 1000), "effect_start_ns": t, "effect_end_ns": t + 50000, "wall_offset_ms": off}
                elif op == "stock_evidence":
                    r = {"start_ns": t, "watermark": "W1", "values": {"c.dana": "+15551110000"}, "end_ns": t + 1, "certified": False}
                elif op == "historical_validate":
                    r = {"verdicts": {}, "cost": {}}
                elif op == "validate":
                    r = {"verdict": "UNKNOWN", "reason": "strict_epoch_and_snapshot_unavailable", "fact": q.get("fact")}
                else:
                    r = {"ok": True}
                self.wfile.write((json.dumps(r) + "\n").encode()); self.wfile.flush()
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer(("127.0.0.1", port), H).serve_forever()


def main(argv):
    if argv[:1] == ["--serve"]:
        return serve(int(argv[1]))
    serial = None
    if argv[:1] == ["-s"]:
        serial, argv = argv[1], argv[2:]
    lock()
    try:
        s = load(); entry = {"t": time.time(), "serial": serial, "argv": argv}; out, rc, err = "", 0, ""
        if argv[:1] == ["version"]:
            out = "Android Debug Bridge version 1.0.41 (fake adb of E7)"
        elif argv[:1] == ["devices"]:
            out = "List of devices attached\n%s device product:p06 model:P06Phone\n" % SERIAL
        elif serial != SERIAL:
            out, rc = "error: device '%s' not found" % serial, 1
        elif argv[0] == "get-state":
            out = "device"
        elif argv[0] == "shell":
            cmd = " ".join(argv[1:]); entry["violation"] = lmdrv.phone_violation(cmd, USER, AWS)
            fail, ignore = os.environ.get("FAKE_FAIL"), os.environ.get("FAKE_IGNORE")
            if fail and re.search(fail, cmd):          # loud failure: exit 1, nothing changes
                rc, err, entry["injected"] = 1, "Error: injected failure for %s\n" % cmd, "fail"
            elif ignore and re.search(ignore, cmd):    # silent failure: exit 0, nothing changes
                entry["injected"] = "ignore"
            else:
                r = shell(s, cmd)
                if r is None:
                    entry["unknown"] = True; r = ""
                out = r
        elif argv[0] == "install":
            entry["violation"] = None if argv[1:3] == ["--user", str(USER)] else "install without --user %d" % USER
            name = Path(argv[-1]).stem
            if PKGS.get(name) in s.get("resigned", []):   # like Device Farm's adb 1.0.39: the failure goes to stderr
                out, rc = "Performing Streamed Install", 1
                err = ("adb: failed to install %s: Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: Existing package %s "
                       "signatures do not match newer version; ignoring!]\n" % (argv[-1], PKGS[name]))
            else:
                if name in PKGS and PKGS[name] not in s["installed"]:
                    s["installed"].append(PKGS[name])
                out = "Performing Streamed Install\nSuccess"
        elif argv[0] == "forward":
            ensure_server(int(argv[1].split(":")[1]))
        elif argv[0] == "reboot":
            s["cur"], s["back_after"], s["running"], s["fgs"] = 0, 3, {}, False
            s["boots"] = s.get("boots", 0) + 1
            s["dc"].pop("activity_manager_native_boot/freeze_debounce_timeout", None) if s["sync"] != "persistent" else None
            s["sync"] = "none" if s["sync"] == "until_reboot" else s["sync"]
        elif argv[0] in ("wait-for-device", "connect"):
            out = "" if argv[0] == "wait-for-device" else "already connected to %s" % argv[1]
        else:
            entry["unknown"] = True
        save(s)
    finally:
        os.rmdir(LOCK)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    sys.stdout.write(out + ("\n" if out and not out.endswith("\n") else ""))
    sys.stderr.write(err)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
