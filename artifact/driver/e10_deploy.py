#!/usr/bin/env python3
"""E10: which lifecycle gaps apply to the deployment the paper names? (real emulator)

For each deployment of the same memory client -- ordinary background app (bg), app with a foreground service (fg),
default assistant (assist: package org.leasemem.assist holding the ASSISTANT role, its VoiceInteractionService bound
by system_server), persistent system app (persist: org.leasemem.persist in /system/app with android:persistent) --
we record the process state and oom_score_adj while the device shows the home screen, the delay from a provider
mutation to the first ContentObserver callback (K trials), whether the cached-app freezer freezes it (2 s debounce),
whether `am kill` ends it, and what force-stop does.
Usage: e10_deploy.py SERIAL MODE K SEED OUT.jsonl
"""
import json, os, random, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lmdrv

serial, mode, K, seed, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
PKG = {"bg": "org.leasemem.client", "fg": "org.leasemem.client", "assist": "org.leasemem.assist", "persist": "org.leasemem.persist"}[mode]
CMP = "org.leasemem.client" if PKG == "org.leasemem.client" else "org.leasemem.client"   # Java package of components
lmdrv.FILES = "/data/data/%s/files" % PKG
d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)
MUT = [("contacts", "update"), ("sms", "insert"), ("calllog", "insert"), ("media", "insert"), ("calendar", "update"), ("settings", "update")]


def comp(c):
    return "%s/%s.%s" % (PKG, CMP, c)


def cmd(c, extra=""):
    d.seq += 1
    rid = "%s_%d" % (mode, d.seq)
    d.sh("rm -f %s/res_%s.json" % (lmdrv.FILES, rid))
    d.sh("am broadcast -n %s --es cmd %s --es id %s %s" % (comp("Cmd"), c, rid, extra))
    t0 = time.time()
    while time.time() - t0 < 40:
        s = d.sh("cat %s/res_%s.json 2>/dev/null" % (lmdrv.FILES, rid))
        if s.startswith("{"):
            return json.loads(s)
        time.sleep(0.15)
    raise TimeoutError(c)


def pid():
    return d.sh("pidof %s" % PKG).strip()


def proc_state():
    txt = d.sh("dumpsys activity processes %s" % PKG)
    m1 = re.search(r"curProcState=(\d+)", txt); m2 = re.search(r"oom adj: max=\S+ curRaw=(-?\d+) setRaw=(-?\d+) cur=(-?\d+) set=(-?\d+)", txt)
    m3 = re.search(r"\b(PER|PERS|FGS|FG|TOP|BFGS|IMPF|IMPB|TRNB|SVC|CEM|CACC|CAC|CRE|BTOP)\b", txt)
    p = pid()
    return {"pid": p, "curProcState": int(m1.group(1)) if m1 else None, "oom_cur": int(m2.group(3)) if m2 else None,
            "oom_score_adj": d.sh("cat /proc/%s/oom_score_adj" % p).strip() if p else None}


def frozen():
    p = pid()
    if not p:
        return "dead"
    path = None
    for line in d.sh("cat /proc/%s/cgroup" % p).splitlines():
        if line.startswith("0::"):
            path = line[3:].strip()
    return (d.sh("cat /sys/fs/cgroup%s/cgroup.freeze 2>/dev/null" % path).strip() or "?") if path else "?"


def ensure_running():
    if not pid():
        d.sh("am start -W -n %s" % comp("Main"))
        time.sleep(1.5)
    if mode == "fg":
        d.sh("am start-foreground-service -n %s" % comp("FgService")); time.sleep(0.8)


rec = {"mode": mode, "pkg": PKG, "serial": serial, "sdk": d.sh("getprop ro.build.version.sdk").strip(), "seed": seed,
       "freeze_debounce": (d.sh("dumpsys activity settings | grep freeze_debounce").strip().split("=") + [""])[1]}
if mode == "bg":
    d.sh("am stopservice -n %s" % comp("FgService"))
if mode == "assist":
    rec["voiceinteraction"] = d.sh("dumpsys voiceinteraction | grep -iE 'leasemem|mComponent|ServiceInfo' | head -5")
    rec["role"] = d.sh("cmd role get-role-holders android.app.role.ASSISTANT 2>/dev/null; dumpsys role | grep -A2 ASSISTANT | head -4")
ensure_running()
w.ensure_base(); time.sleep(14)
d.sh("input keyevent KEYCODE_HOME"); time.sleep(8)
rec["state_home"] = proc_state()
lat = []
for k in range(K):
    ensure_running()
    cmd("OBSERVE")
    src, kind = MUT[k % len(MUT)]
    m = w.mutate(src, kind)
    time.sleep(35)
    D = cmd("DECIDE")
    after = [e["t"] for e in (D.get("events") or []) if e["src"] == src and e["t"] >= m["t_pre"]]
    lat.append({"src": src, "lat_ms": (min(after) - m["t_pre"]) if after else None, "pid": D["pid"], "fg": D.get("fg")})
    w.ensure_base()
rec["latency"] = lat
rec["state_after"] = proc_state()
# freezer eligibility (debounce must be set live to 2 s by the caller)
d.sh("input keyevent KEYCODE_HOME"); time.sleep(10)
rec["frozen_after_10s"] = frozen()
# am kill
p0 = pid(); d.sh("am kill %s" % PKG); time.sleep(1.5); p1 = pid()
rec["am_kill"] = {"pid_before": p0, "pid_after": p1, "killed": bool(p0) and p0 != p1}
ensure_running(); time.sleep(2)
# force-stop
p0 = pid(); fs = d.sh("am force-stop %s 2>&1" % PKG); time.sleep(3); p1 = pid()
rec["force_stop"] = {"pid_before": p0, "pid_after": p1, "output": fs.strip()[:200], "restarted_by_system": bool(p1) and p1 != p0}
with open(out, "a") as f:
    f.write(json.dumps(rec) + "\n")
print(json.dumps({k: v for k, v in rec.items() if k != "latency"})[:1500])
print("latencies", [x["lat_ms"] for x in lat])
