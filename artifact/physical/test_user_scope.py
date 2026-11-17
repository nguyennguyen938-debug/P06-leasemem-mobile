#!/usr/bin/env python3
"""Static check, no phone needed: no command string that a campaign driver can send to the personal phone lacks
--user, and no banned command appears outside code that runs only on P06's emulators. Also checks the runtime guard
(lmdrv.phone_violation) on fixed examples. Run: python physical/test_user_scope.py

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
GUARD_NAMES = {"_AT", "SCOPED", "USER_ADMIN", "BANNED", "DUMPSYS_OK"}
GUARD_FUNCS = {("driver/lmdrv.py", "u"), ("driver/lmdrv.py", "phone_violation")}
# Literals that would be refused on the phone but sit in code that runs only on P06's emulators (and the runtime
# guard refuses them on any other device). Each entry: (file, literal prefix, why it never reaches the phone).
EMULATOR_ONLY = [
    ("driver/lmdrv.py", "cd /data/data/", "app_sh root path: only if d.rooted and d.emulator"),
    ("driver/lmdrv.py", "/data/data/%s/files", "FILES: used only by the legacy emulator drivers e3, e10, e12"),
    ("physical/campaign.py", "pm uninstall %s", "cleanup: goes through d.u() and the runtime guard, which allows only org.leasemem.*"),
    ("driver/e2v3_gaps.py", "appops set root WRITE_SMS allow", "inside `if d.emulator:`"),
    ("driver/e6_pitfalls.py", "settings put global auto_time", "clock part: n_clock = 0 unless d.emulator and d.rooted"),
    ("driver/e6_pitfalls.py", "date @", "clock part: n_clock = 0 unless d.emulator and d.rooted"),
    ("physical/campaign.py", "settings delete global %s", "restore: keys from the fixed tuple (lm_mode, lm_target)"),
    ("physical/campaign.py", "settings put global %s %s", "restore: keys from the fixed tuple (lm_mode, lm_target)"),
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
            b = lmdrv.BANNED.search(text) if re.search(r"\s", text.strip()) else None   # one-word literals are names or adb() args
            if b and not any(rel == f and text.startswith(p) for f, p, _ in EMULATOR_ONLY):
                problems.append("%s:%d banned on the phone: %r in %r" % (rel, line, b.group(0), text[:90]))
    return problems


def guard_examples():
    v, u = lmdrv.phone_violation, 10
    allowed = ["am start --user 10 -W -n org.leasemem.client/.Main", "run-as --user 10 org.leasemem.client sh -c 'cat files/x 2>/dev/null'",
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


if __name__ == "__main__":
    problems = scan() + guard_examples()
    for p in problems:
        print(p)
    print("user-scope check: %d files, %d problems" % (len(FILES), len(problems)))
    sys.exit(1 if problems else 0)
