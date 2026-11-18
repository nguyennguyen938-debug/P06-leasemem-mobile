#!/usr/bin/env python3
"""Static check, no phone needed: no command string that a campaign driver can send to a phone lacks --user, and no
banned command appears outside code that runs only on P06's emulators. Also checks, without any device: the runtime
guard (lmdrv.phone_violation) on fixed examples for a personal phone (user 10) and for AWS mode (user 0); that the
user's phone (serial RFCXA0TTMPP) is refused in every mode before any adb call, and when another serial reports it
as ro.serialno; that AWS mode runs in user 0 with SMS and the call log while personal mode still needs P06 Test.
Run: python physical/test_user_scope.py

How the scan works: every string literal (f-strings with their placeholders) in the files that physical/campaign.py
runs is parsed out of the AST, docstrings and lmdrv's own guard definitions excepted. A literal that starts a
user-scoped command (am, pm, appops, content, run-as, cmd) at a shell command position must either be an argument
of Dev.u(...) (which adds --user), be written as campaign's "{u:...}" form (run through Dev.u), carry --user itself,
or be one of the read-only user queries (pm list users, am get-current-user, am get-started-user-state).
"""
import ast, re, sys
from pathlib import Path
A = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(A / "driver"))
import lmdrv

FILES = ["driver/lmdrv.py", "driver/e1_coverage.py", "driver/e2v3_gaps.py", "driver/e3v2_boundary.py",
         "driver/e6_pitfalls.py", "driver/e9_frozen.py", "revision/run.py", "followup/deployment.py",
         "physical/campaign.py", "physical/b0_setup.py", "physical/b0_probe.py", "physical/b7_continuous.py",
         "physical/b11_statelog.py", "physical/b12_battery.py"]
GUARD_NAMES = {"_AT", "SCOPED", "USER_ADMIN", "BANNED", "DUMPSYS_OK", "CLOCK", "PM_CLEAR_AWS_OK", "RUNAS_ID_AWS_OK"}
GUARD_FUNCS = {("driver/lmdrv.py", "u"), ("driver/lmdrv.py", "phone_violation")}
# Literals that would be refused on the phone but sit in code that runs only on P06's emulators (and the runtime
# guard refuses them on any other device). Each entry: (file, literal prefix, why it never reaches the phone).
EMULATOR_ONLY = [
    ("driver/lmdrv.py", "cd /data/data/", "app_sh root path: only if d.rooted and d.emulator"),
    ("driver/lmdrv.py", "/data/data/%s/files", "FILES: used only by the legacy emulator drivers e3, e10, e12"),
    ("driver/lmdrv.py", "pm uninstall %s", "provision (AWS): goes through d.u() and the runtime guard, which allows only org.leasemem.*"),
    ("driver/lmdrv.py", "run-as %s id 2>&1", "runas_diag: the runtime guard allows `run-as org.leasemem.* id` without --user in AWS mode only (user 0 is run-as's default)"),
    ("physical/b0_probe.py", "cmd alarm set-time", "clock_set_back: probed only if d.aws; the runtime guard allows cmd alarm only in AWS mode"),
    ("physical/b0_probe.py", "pm clear com.android.providers.contacts", "pm_clear_contacts: probed only if d.aws, through d.u(); the runtime guard allows exactly `pm clear --user 0 com.android.providers.contacts` in AWS mode only"),
    ("physical/b0_probe.py", "date @", "clock_set_back: probed only if d.aws (AWS mode allows clock commands)"),
    ("physical/b0_probe.py", "settings put global auto_time", "clock_set_back: probed only if d.aws"),
    ("physical/b0_probe.py", "settings get global auto_time", "clock_set_back: probed only if d.aws"),
    ("physical/campaign.py", "pm uninstall %s", "cleanup: goes through d.u() and the runtime guard, which allows only org.leasemem.*"),
    ("driver/e2v3_gaps.py", "appops set root WRITE_SMS allow", "inside `if d.emulator:`"),
    ("driver/e6_pitfalls.py", "settings put global auto_time", "clock part: n_clock = 0 unless (d.emulator and d.rooted) or d.aws; the runtime guard refuses clock commands outside AWS mode"),
    ("driver/e6_pitfalls.py", "date @", "clock part: `date` only off AWS, i.e. on a rooted emulator"),
    ("driver/e6_pitfalls.py", "cmd alarm set-time", "clock part: only if d.aws; the runtime guard refuses cmd alarm outside AWS mode"),
    ("physical/campaign.py", "settings delete global %s", "restore: keys from the fixed tuple (lm_mode, lm_target)"),
    ("physical/campaign.py", "settings put global %s %s", "restore: keys from the fixed tuple (lm_mode, lm_target)"),
    ("physical/campaign.py", "settings put global auto_time 1", "restore: only if d.aws (the runtime guard refuses clock settings outside AWS mode)"),
    ("physical/campaign.py", "settings get global auto_time", "restore read-back: only if d.aws"),
    ("physical/campaign.py", "settings get global ", "snapshot: keys from the fixed tuple (lm_mode, lm_target)"),
]


def literals(rel):
    """(text, lineno, inside_u_call) for every non-docstring literal of a file."""
    tree = ast.parse((A / rel).read_text(encoding="utf-8"))
    parent = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    skip = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            skip.add(id(body[0].value))                                    # docstring
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in GUARD_NAMES for t in node.targets):
            skip.update(id(n) for n in ast.walk(node))
        if isinstance(node, ast.FunctionDef) and (rel, node.name) in GUARD_FUNCS:
            skip.update(id(n) for n in ast.walk(node))
    for node in ast.walk(tree):     # messages: raise ..., print(...), runlog(...) are text, not commands
        if isinstance(node, ast.Raise) or (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in ("print", "runlog")):
            skip.update(id(n) for n in ast.walk(node))
    out = []
    for node in ast.walk(tree):
        if id(node) in skip or isinstance(parent.get(node), ast.JoinedStr):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        elif isinstance(node, ast.JoinedStr):
            text = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
        else:
            continue
        p, in_u = node, False
        while p in parent:
            p = parent[p]
            if isinstance(p, ast.Call) and isinstance(p.func, ast.Attribute) and p.func.attr == "u":
                in_u = True
        out.append((text, node.lineno, in_u))
    return out


def scan():
    problems = []
    for rel in FILES:
        for text, line, in_u in literals(rel):
            for m in lmdrv.SCOPED.finditer(text):
                seg = re.sub(r"%[sd]|\{\}", "10", (m.group(1) + " " + m.group(2)).strip())   # placeholders: any user id
                if in_u or text.startswith("{u:") or "--user" in seg or lmdrv.USER_ADMIN.fullmatch(seg):
                    continue
                if any(rel == f and text.startswith(p) for f, p, _ in EMULATOR_ONLY):
                    continue
                problems.append("%s:%d user-scoped command without --user: %r" % (rel, line, text[:90]))
            b = (lmdrv.BANNED.search(text) or lmdrv.CLOCK.search(text) or re.search(r"\bpm\s+clear\b", text)) \
                if re.search(r"\s", text.strip()) else None   # one-word literals are names or adb() args; pm clear only where exempted
            if b and not any(rel == f and text.startswith(p) for f, p, _ in EMULATOR_ONLY):
                problems.append("%s:%d banned on the phone: %r in %r" % (rel, line, b.group(0), text[:90]))
    return problems


def guard_examples():
    v, u = lmdrv.phone_violation, 10
    allowed = ["am start --user 10 -W -n org.leasemem.client/.Main", "run-as org.leasemem.client --user 10 sh -c 'cat files/x 2>/dev/null'",
               "for p in $(pidof org.leasemem.client); do echo $p $(stat -c %u /proc/$p); done", "pm list users",
               "am get-current-user", "am get-started-user-state 10", "dumpsys battery unplug", "dumpsys activity settings | grep -i freeze",
               "device_config put activity_manager_native_boot freeze_debounce_timeout 2000", "settings delete global lm_mode",
               "cmd role add-role-holder --user 10 android.app.role.ASSISTANT org.leasemem.assist 0", "date +%s%3N",
               "content query --user 10 --uri content://call_log/calls --projection _id", "pm uninstall --user 10 org.leasemem.client",
               "dumpsys user | awk '/UserInfo\\{/{p=index($0,\"UserInfo{10:\")>0} p'", "dumpsys batterystats --charged org.leasemem.client"]
    refused = ["am start -W -n x/.Main", "am start --user 0 -n x/.Main", "run-as org.leasemem.client id", "pm clear com.android.providers.contacts",
               "date @1700000000", "cmd alarm set-time 5", "settings put global auto_time 0", "settings get global adb_wifi_enabled",
               "dumpsys batterystats --reset", "dumpsys batterystats", "dumpsys", "dumpsys voiceinteraction", "cat /sdcard/DCIM/x",
               "cmd deviceidle force-idle deep", "pm uninstall --user 10 com.whatsapp", "am switch-user 10", "svc power stayon true",
               "echo x; pm grant org.leasemem.client android.permission.READ_SMS", "content insert --user 10 --uri content://sms",
               "reboot", "device_config put privacy foo 1", "pm create-user Foo", "setprop persist.x 1", "su -c id"]
    bad = [c for c in allowed if v(c, u)] + [c for c in refused if not v(c, u)]
    return ["guard example misjudged: %r -> %s" % (c, v(c, u)) for c in bad]


def aws_examples():
    v = lambda c: lmdrv.phone_violation(c, 0, aws=True)
    allowed = ["am start --user 0 -W -n org.leasemem.client/.Main", "run-as org.leasemem.client --user 0 sh -c 'cat files/x'",
               "date @1700000000", "settings put global auto_time 0", "cmd alarm set-time 5",
               "cmd role add-role-holder --user 0 android.app.role.SMS org.leasemem.mut 0", "pm uninstall --user 0 org.leasemem.client",
               "content query --user 0 --uri content://sms --projection _id", "pm clear --user 0 com.android.providers.contacts",
               "run-as org.leasemem.mut id 2>&1", "run-as org.leasemem.client id"]
    refused = ["am start -W -n x/.Main", "am start --user 10 -n x/.Main", "pm clear org.leasemem.client", "dumpsys batterystats --reset",
               "pm clear --user 0 org.leasemem.client", "pm clear com.android.providers.contacts",
               "pm clear --user 10 com.android.providers.contacts", "pm clear --user 0 com.android.providers.contacts; pm clear --user 0 com.x",
               "cat /sdcard/x", "pm create-user Foo", "setprop persist.x 1", "reboot", "svc power stayon true",
               "run-as org.leasemem.mut ls files 2>&1", "run-as org.leasemem.mut sh -c 'cat files/x'", "run-as com.android.x id"]
    bad = [c for c in allowed if v(c)] + [c for c in refused if not v(c)]
    # outside AWS mode the Contacts clear stays banned for any user
    personal = [c for c in ("pm clear --user 10 com.android.providers.contacts", "pm clear --user 0 com.android.providers.contacts",
                            "run-as org.leasemem.mut id 2>&1")
                if not lmdrv.phone_violation(c, 10) or not lmdrv.phone_violation(c, 0)]
    return ["AWS guard example misjudged: %r -> %s" % (c, v(c)) for c in bad] + \
           ["pm clear allowed outside AWS mode: %r" % c for c in personal]


class FakeRun:
    """Stands in for subprocess.run inside lmdrv: answers a few adb commands, records every call."""
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, argv, **kw):
        self.calls.append(argv); cmd = " ".join(argv[argv.index("shell") + 1:]) if "shell" in argv else argv[-1]
        out = next((v for k, v in self.answers.items() if cmd.startswith(k)), "")
        return type("R", (), {"stdout": out + "\n", "stderr": "", "returncode": 0})()


def device_checks():
    import os
    problems, real = [], lmdrv.subprocess.run
    saved = (lmdrv.AWS, set(lmdrv.ALLOWED), os.environ.get("P06_CAMPAIGN"), lmdrv.ADB, lmdrv.ADB_CMD)
    os.environ["P06_CAMPAIGN"] = "1"; lmdrv.ADB = sys.executable; lmdrv.ADB_CMD = ["adb"]
    try:
        # 1. the user's phone: refused before any adb call, in every mode, also inside a longer adb serial
        for aws in (False, True):
            lmdrv.AWS = aws; lmdrv.ALLOWED |= {"RFCXA0TTMPP", "adb-RFCXA0TTMPP-x._adb-tls-connect._tcp"}
            for serial in ("RFCXA0TTMPP", "adb-RFCXA0TTMPP-x._adb-tls-connect._tcp"):
                fr = FakeRun({}); lmdrv.subprocess.run = fr
                try:
                    lmdrv.Dev(serial); problems.append("blocked serial %s accepted (aws=%s)" % (serial, aws))
                except lmdrv.GuardError:
                    pass
                except Exception as e:
                    problems.append("blocked serial %s not refused by the guard (aws=%s): %r" % (serial, aws, e))
                if fr.calls:
                    problems.append("adb was called for the blocked serial %s: %s" % (serial, fr.calls))
        # 2. an allowed serial whose ro.serialno is the user's phone: refused right after that one read
        lmdrv.ALLOWED |= {"ALIAS1"}
        fr = FakeRun({"get-state": "device", "getprop ro.serialno": "RFCXA0TTMPP"}); lmdrv.subprocess.run = fr
        try:
            lmdrv.Dev("ALIAS1"); problems.append("device reporting RFCXA0TTMPP accepted")
        except lmdrv.GuardError:
            pass
        except Exception as e:
            problems.append("device reporting RFCXA0TTMPP not refused by the guard: %r" % e)
        if [c for c in fr.calls if "get-state" not in c and "getprop ro.serialno" not in " ".join(c)]:
            problems.append("commands sent after the serial check: %s" % fr.calls)
        # 3. AWS mode: user 0, SMS and call log excluded (B0 run 97a66c65); records carry the Device Farm identity
        lmdrv.AWS = True; lmdrv.ALLOWED |= {"UDID1"}
        os.environ.update(DEVICEFARM_DEVICE_UDID="UDID1", DEVICEFARM_RUN_ARN="arn:run", DEVICEFARM_DEVICE_ARN="arn:dev")
        lmdrv.subprocess.run = FakeRun({"get-state": "device", "getprop ro.serialno": "UDID1", "id -u": "2000", "am get-current-user": "0"})
        d = lmdrv.Dev("UDID1"); m = d.meta()
        if (d.user, d.excluded, d.aws) != (0, {"sms", "calllog"}, True):
            problems.append("AWS mode: user %s, excluded %s, aws %s" % (d.user, d.excluded, d.aws))
        if (m["device_instance"], m["run_arn"], m["device_arn"]) != ("UDID1", "arn:run", "arn:dev"):
            problems.append("AWS meta: %s" % m)
        for c, want in [("am start -n x", "am start --user 0 -n x"), ("run-as p id", "run-as p --user 0 id"),
                        ("pm list packages org.leasemem", "pm list packages --user 0 org.leasemem")]:
            if d.u(c) != want:
                problems.append("AWS u(%r): %r, want %r" % (c, d.u(c), want))
        # 4. personal mode is unchanged: no user named P06 Test -> refused
        lmdrv.AWS = False
        lmdrv.subprocess.run = FakeRun({"get-state": "device", "getprop ro.serialno": "UDID1", "id -u": "2000",
                                        "pm list users": "Users:\n\tUserInfo{0:Owner:c13} running"})
        try:
            lmdrv.Dev("UDID1"); problems.append("personal mode accepted a phone without P06 Test")
        except RuntimeError:
            pass
    finally:
        lmdrv.subprocess.run = real
        lmdrv.AWS, lmdrv.ALLOWED, campaign, lmdrv.ADB, lmdrv.ADB_CMD = saved[0], saved[1], saved[2], saved[3], saved[4]
        if campaign is None:
            os.environ.pop("P06_CAMPAIGN", None)
        for k in ("DEVICEFARM_DEVICE_UDID", "DEVICEFARM_RUN_ARN", "DEVICEFARM_DEVICE_ARN"):
            os.environ.pop(k, None)
    return problems


if __name__ == "__main__":
    problems = scan() + guard_examples() + aws_examples() + device_checks()
    for p in problems:
        print(p)
    print("user-scope check: %d files, %d problems" % (len(FILES), len(problems)))
    sys.exit(1 if problems else 0)
