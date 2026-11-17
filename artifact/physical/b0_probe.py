#!/usr/bin/env python3
"""B0: which commands work on this test phone? One JSONL record per probe: name, ok, detail, seconds.

Run only on the confirmed test phone, after `campaign.py setup` installed the P06 apps. Every probe restores what it
changed (battery, Doze, bucket, permissions, DeviceConfig, assistant role, clock). It writes test fixtures (contacts,
SMS, call log, images, calendar, a Settings key, files) through org.leasemem.mut and, with --destructive, clears the
Contacts provider (all contacts on the phone) and reboots the phone; those two run last.
Usage: b0_probe.py SERIAL OUT.jsonl [--destructive]
"""
import json, os, re, sys, time, traceback, random
from pathlib import Path
A = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(A / "driver"))
import lmdrv

CPKG, MPKG, APKG = lmdrv.CPKG, lmdrv.MPKG, "org.leasemem.assist"
serial, out = sys.argv[1], sys.argv[2]
destructive = "--destructive" in sys.argv
d = lmdrv.Dev(serial)
w = lmdrv.World(d, random.Random(20261119))
f = lmdrv.open_new(out)


def probe(name, fn):
    t0 = time.time(); rec = {**d.meta(), "probe": name}
    try:
        ok, detail = fn()
        rec.update(ok=bool(ok), detail=detail)
    except Exception as e:
        rec.update(ok=False, detail=repr(e), trace=traceback.format_exc())
    rec["seconds"] = round(time.time() - t0, 2)
    f.write(json.dumps(rec) + "\n"); f.flush()
    print("%-28s %s  %s" % (name, "OK " if rec["ok"] else "NO ", str(rec["detail"])[:110]), flush=True)
    return rec["ok"]


def bg_client():
    d.sh("am stopservice -n %s/.FgService" % CPKG); d.launch(); time.sleep(1); d.home(); time.sleep(2)
    return d.pid()


def granted(pkg, perm):
    m = re.search(re.escape(perm) + r": granted=(true|false)", d.sh("dumpsys package %s" % pkg))
    return m and m.group(1) == "true"


def identity():
    g = lambda k: d.sh("getprop " + k).strip()
    keys = ["ro.product.manufacturer", "ro.product.model", "ro.product.device", "ro.build.fingerprint", "ro.build.type",
            "ro.build.version.release", "ro.build.version.sdk", "ro.build.version.security_patch", "ro.debuggable", "ro.serialno"]
    return True, {k: g(k) for k in keys}


def adb_root():
    o = d.adb("root"); time.sleep(3); d.adb("wait-for-device"); d.wait_boot()
    return d.rooted, {"adb_root": o.strip(), "id": d.sh("id").strip()}


def run_as():
    o = d.sh("run-as %s id" % CPKG).strip()
    return "uid=" in o and "uid=0" not in o, o


def read_files():
    d.cmd("PING")                       # needs the client's files/res_<id>.json round trip: run-as or root
    m = d.cat(CPKG, "files/mem.json")
    return m.startswith("{"), {"mem_json_bytes": len(m), "via": "root" if d.rooted else "run-as"}


def proc_reads():
    p = bg_client()
    cg = d.sh("cat /proc/%s/cgroup 2>&1" % p).strip()
    adj = d.sh("cat /proc/%s/oom_score_adj 2>&1" % p).strip()
    path = next((l[3:].strip() for l in cg.splitlines() if l.startswith("0::")), None)
    fr = d.sh("cat /sys/fs/cgroup%s/cgroup.freeze 2>&1" % path).strip() if path else None
    return path is not None and fr in ("0", "1"), {"cgroup": cg[:200], "oom_score_adj": adj, "cgroup.freeze": fr}


def dumpsys_frozen():
    p = bg_client(); txt = d.sh("dumpsys activity processes %s" % CPKG)
    m = re.search(r"isFrozen=(true|false)", txt[txt.find("%s:%s/" % (p, CPKG)):])
    return m is not None, {"isFrozen": m and m.group(1), "pid": p}


def freezer():
    d.sh("device_config set_sync_disabled_for_tests until_reboot")
    d.sh("device_config put activity_manager_native_boot freeze_debounce_timeout 2000")
    got = d.sh("device_config get activity_manager_native_boot freeze_debounce_timeout").strip()
    bg_client(); t0 = time.time(); st = d.frozen()
    while time.time() - t0 < 25 and st != "1":
        time.sleep(0.5); st = d.frozen()
    res = {"debounce_get": got, "frozen": st, "method": d.frozen_method, "after_s": round(time.time() - t0, 1)}
    d.sh("device_config put activity_manager_native_boot freeze_debounce_timeout 600000"); d.launch()
    return got == "2000" and st == "1", res


def am_kill():
    p = bg_client(); d.sh("am kill %s" % CPKG); time.sleep(1)
    return d.pid() != p, {"pid_before": p, "pid_after": d.pid()}


def force_stop():
    d.launch(); p = d.pid(); d.sh("am force-stop %s" % CPKG); time.sleep(1)
    return not d.pid(), {"pid_before": p, "pid_after": d.pid()}


def sigkill():
    d.launch(); p = d.kill9(CPKG); time.sleep(1)
    return p and d.pid() != p, {"pid_before": p, "pid_after": d.pid(), "via": "root" if d.rooted else "run-as"}


def revoke_grant():
    perm = "android.permission.READ_CONTACTS"
    d.sh("pm revoke %s %s" % (CPKG, perm)); off = granted(CPKG, perm)
    d.sh("pm grant %s %s" % (CPKG, perm)); on = granted(CPKG, perm)
    return off is False and on is True, {"after_revoke": off, "after_grant": on}


def appops():
    out = {}
    for pkg in (CPKG, MPKG):
        d.sh("appops set %s MANAGE_EXTERNAL_STORAGE allow" % pkg); d.sh("appops set %s WRITE_SMS allow" % pkg)
        out[pkg] = d.sh("appops get %s MANAGE_EXTERNAL_STORAGE; appops get %s WRITE_SMS" % (pkg, pkg)).strip()
    return all("allow" in v for v in out.values()), out


def fixtures():
    r = w.ensure_base()
    return bool(r.get("ok")), r


def mutations():
    res = {}
    for src, kinds in lmdrv.World.KINDS.items():
        for k in kinds:
            try:
                res["%s.%s" % (src, k)] = w.mutate(src, k)["did"]
            except Exception as e:
                res["%s.%s" % (src, k)] = "ERR " + repr(e)[:150]
        w.ensure_base()
    return not any(str(v).startswith("ERR") for v in res.values()), res


def client_probe():
    r = d.cmd("PROBE", timeout=60)["probe"]
    bad = sorted(k for k, v in r.items() if "ERR" in str(v))
    return not bad, {"candidates": sorted(r), "err": bad}


def battery_unplug():
    d.sh("dumpsys battery unplug"); un = d.plugged()
    d.sh("dumpsys battery reset"); back = d.plugged()
    return un is False, {"plugged_after_unplug": un, "plugged_after_reset": back}


def doze():
    d.home(); d.sh("dumpsys battery unplug"); o = d.sh("dumpsys deviceidle force-idle deep").strip()
    st = d.sh("dumpsys deviceidle get deep").strip()
    d.sh("dumpsys deviceidle unforce"); d.sh("dumpsys battery reset")
    return st == "IDLE", {"force_idle": o[:150], "deep_state": st}


def bucket():
    d.sh("am set-standby-bucket %s restricted" % CPKG); b = d.sh("am get-standby-bucket %s" % CPKG).strip()
    d.sh("am set-standby-bucket %s active" % CPKG)
    return b in ("45", "restricted"), {"bucket": b, "after_restore": d.sh("am get-standby-bucket %s" % CPKG).strip()}


def assistant():
    r = d.adb("install", "-r", "-g", str(A / "app/assist/build/LeaseMemAssist.apk"))
    o = d.sh("cmd role add-role-holder android.app.role.ASSISTANT %s 0" % APKG); time.sleep(3)
    holders = d.sh("cmd role get-role-holders android.app.role.ASSISTANT").strip()
    bound = "mBound=true" in d.sh("dumpsys voiceinteraction")
    d.sh("cmd role remove-role-holder android.app.role.ASSISTANT %s 0" % APKG); d.sh("am force-stop %s" % APKG)
    return APKG in holders and bound, {"install": r.strip()[-60:], "add": o[:150], "holders": holders, "bound": bound}


def clock():
    """`date` needs root; `cmd alarm set-time` is tried as the non-root route. Restores the time and auto_time."""
    auto = d.sh("settings get global auto_time").strip(); d.sh("settings put global auto_time 0")
    t0 = d.now_ms(); res = {"auto_time": auto}
    res["date"] = d.sh("date @%d 2>&1" % (t0 // 1000 - 3600)).strip()[:120]
    moved = d.now_ms() < t0 - 1800 * 1000
    if not moved:
        res["alarm_set_time"] = d.sh("cmd alarm set-time %d 2>&1" % (t0 - 3600 * 1000)).strip()[:120]
        moved = d.now_ms() < t0 - 1800 * 1000
    res["moved_back"] = moved
    if moved:                  # restore from the host clock; auto_time then resyncs from the network
        target = int(time.time() * 1000)
        d.sh("date @%d" % (target // 1000)) if d.rooted else d.sh("cmd alarm set-time %d" % target)
    d.sh("settings put global auto_time %s" % (auto if auto in ("0", "1") else "1"))
    res["skew_after_restore_ms"] = d.now_ms() - int(time.time() * 1000)
    return moved, res


def charge_counter():
    txt = d.sh("dumpsys battery")
    m = re.search(r"Charge counter: (-?\d+)", txt); lvl = re.search(r"level: (\d+)", txt)
    sysfs = d.sh("cat /sys/class/power_supply/battery/charge_counter 2>&1").strip()
    ok = bool(m and int(m.group(1)) > 0)
    return ok, {"charge_counter_uAh": m and int(m.group(1)), "level": lvl and int(lvl.group(1)), "sysfs": sysfs[:80]}


def batterystats():
    o = d.sh("dumpsys batterystats --reset").strip()
    s = d.sh("dumpsys batterystats --charged %s" % CPKG)
    return "reset" in o.lower() or bool(s), {"reset": o[:120], "charged_bytes": len(s)}


def screen():
    d.sh("input keyevent KEYCODE_SLEEP"); time.sleep(1); off = d.sh("dumpsys power | grep -m1 mWakefulness=").strip()
    d.sh("input keyevent KEYCODE_WAKEUP"); time.sleep(1); on = d.sh("dumpsys power | grep -m1 mWakefulness=").strip()
    return "Asleep" in off or "Dozing" in off, {"after_sleep": off, "after_wakeup": on}


def wireless():
    devs = lmdrv.subprocess.run([lmdrv.ADB, "devices", "-l"], capture_output=True, text=True, timeout=15).stdout
    res = {"adb_wifi_enabled": d.sh("settings get global adb_wifi_enabled").strip(),
           "tls_port": d.sh("getprop service.adb.tls.port").strip(),
           "transports": [l for l in devs.splitlines()[1:] if l.strip()]}
    return any(":" in l.split()[0] or "_adb-tls-connect" in l for l in res["transports"]), res


def pm_clear_contacts():
    o = d.sh("pm clear com.android.providers.contacts").strip(); time.sleep(3)
    r = w.ensure_base()
    return "Success" in o and r.get("ok"), {"pm_clear": o, "refixtured": r}


def reboot():
    t = d.now_ms(); d.adb("reboot"); time.sleep(5); d.adb("wait-for-device", timeout=300)
    s = d.wait_boot(); d.adb("root"); time.sleep(3); d.adb("wait-for-device"); d.wait_boot()
    return True, {"boot_s": round(s, 1), "t_reboot": t, "rooted_after": d.rooted, "client_pid_after": d.pid()}


for name, fn in [("identity", identity), ("adb_root", adb_root), ("run_as", run_as), ("read_app_files", read_files),
                 ("appops", appops), ("fixtures_ensure_base", fixtures), ("mutations_all_kinds", mutations),
                 ("client_probe_candidates", client_probe), ("proc_cgroup_read", proc_reads),
                 ("dumpsys_isFrozen", dumpsys_frozen), ("freezer_debounce_2s", freezer), ("am_kill", am_kill),
                 ("am_force_stop", force_stop), ("sigkill_kill9", sigkill), ("pm_revoke_grant", revoke_grant),
                 ("battery_unplug", battery_unplug), ("doze_force_idle_deep", doze), ("standby_bucket", bucket),
                 ("assistant_role", assistant), ("clock_set_back", clock), ("charge_counter", charge_counter),
                 ("batterystats", batterystats), ("screen_sleep_wake", screen), ("wireless_debugging", wireless)]:
    probe(name, fn)
if destructive:
    probe("pm_clear_contacts", pm_clear_contacts)
    probe("reboot", reboot)
d.launch()
f.close()
