#!/usr/bin/env python3
"""B0: which commands work in the test user "P06 Test" of the personal phone? One JSONL record per probe: name, ok,
detail, seconds.

Runs through campaign.py after b0_setup.py prepared the test user. Every probe stays inside the test user or changes
a device-wide setting that it restores itself (and campaign.py restores again from its snapshot). Nothing here
clears app data, changes the clock, uses root, or touches another user. The reboot probe runs only with
--allow-reboot (the user's consent for this run); after it the probe waits for the user to switch back to P06 Test.
On AWS Device Farm (lmdrv AWS mode) the same probes run in user 0 and three more run: host (Python and adb versions of
the Device Farm test host), clock_set_back (can the shell set the time without root? the time and auto_time are put
back), sms_role (can org.leasemem.mut hold the SMS role; the role is removed again) and pm_clear_contacts (clear the
Contacts provider of user 0, then write the fixtures again). The reboot probe records `survived: true` when the run
outlives `adb reboot` and `adb wait-for-device`; if not, the probe fails and the reboot gap keeps the emulator result.
Usage: b0_probe.py SERIAL OUT.jsonl [--allow-reboot]
"""
import json, os, re, sys, time, traceback, random
from pathlib import Path
A = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(A / "driver"))
import lmdrv

CPKG, MPKG, APKG = lmdrv.CPKG, lmdrv.MPKG, lmdrv.APKG
serial, out = sys.argv[1], sys.argv[2]
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
    d.sh(d.u("am stopservice -n %s/.FgService" % CPKG)); d.launch(); time.sleep(1); d.home(); time.sleep(2)
    return d.pid()


def granted(pkg, perm):
    m = re.search(re.escape(perm) + r": granted=(true|false)", d.sh("dumpsys package %s" % pkg))
    return m and m.group(1) == "true"


def identity():
    keys = ["ro.product.manufacturer", "ro.product.model", "ro.product.device", "ro.build.fingerprint", "ro.build.type",
            "ro.build.version.release", "ro.build.version.sdk", "ro.build.version.security_patch", "ro.debuggable"]
    return True, {k: d.sh("getprop " + k).strip() for k in keys}


def user_info():
    st = d.sh("am get-started-user-state %d" % d.user).strip()
    return d.current_user() == d.user and "RUNNING_UNLOCKED" in st, {
        "user_id": d.user, "current_user": d.current_user(), "state": st, "restrictions": sorted(d.restrictions),
        "excluded_sources": sorted(d.excluded), "adbd_uid": d.sh("id -u").strip()}


def install_user():
    pk = d.sh(d.u("pm list packages org.leasemem")).split()
    return {"package:" + p for p in (CPKG, MPKG, lmdrv.TPKG, APKG)} <= set(pk), pk


def run_as_user():
    o = d.sh(d.u("run-as %s id" % CPKG)).strip()
    m = re.search(r"uid=(\d+)", o)
    return bool(m) and int(m.group(1)) // 100000 == d.user, o


def read_files():
    d.cmd("PING")                       # client command round trip through run-as --user
    m = d.cat(CPKG, "files/mem.json")
    return m.startswith("{"), {"mem_json_bytes": len(m), "exclusion_file": d.cat(CPKG, "files/p06_exclude").strip()}


def content_user():
    txt = d.sh(d.u("content query --uri content://com.android.contacts/raw_contacts --projection _id --where \"display_name LIKE 'LM %'\""))
    n = len(re.findall(r"^Row: ", txt, re.M))
    return n >= 2, {"fixture_raw_contacts": n}


def appops():
    o = d.sh(d.u("appops get %s MANAGE_EXTERNAL_STORAGE" % MPKG)).strip()
    return "allow" in o, o


def fixtures():
    r = w.ensure_base()
    return bool(r.get("ok")), r


def mutations():
    res = {}
    for src, kinds in w.kinds.items():
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


def process_user():
    p = bg_client(); uid = d.sh("stat -c %%u /proc/%s" % p).strip()
    return uid.isdigit() and int(uid) // 100000 == d.user, {"pid": p, "uid": uid,
                                                           "oom_score_adj": d.sh("cat /proc/%s/oom_score_adj" % p).strip()}


def proc_reads():
    p = bg_client()
    cg = d.sh("cat /proc/%s/cgroup 2>&1" % p).strip()
    path = next((l[3:].strip() for l in cg.splitlines() if l.startswith("0::")), None)
    fr = d.sh("cat /sys/fs/cgroup%s/cgroup.freeze 2>&1" % path).strip() if path else None
    return path is not None and fr in ("0", "1"), {"cgroup": cg[:200], "cgroup.freeze": fr}


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
    p = bg_client(); d.sh(d.u("am kill %s" % CPKG)); time.sleep(1)
    return d.pid() != p, {"pid_before": p, "pid_after": d.pid()}


def force_stop():
    d.launch(); p = d.pid(); d.sh(d.u("am force-stop %s" % CPKG)); time.sleep(1)
    return not d.pid(), {"pid_before": p, "pid_after": d.pid()}


def sigkill():
    d.launch(); p = d.kill9(CPKG); time.sleep(1)
    return p and d.pid() != p, {"pid_before": p, "pid_after": d.pid()}


def revoke_grant():
    perm = "android.permission.READ_CONTACTS"
    d.sh(d.u("pm revoke %s %s" % (CPKG, perm))); off = granted(CPKG, perm)
    d.sh(d.u("pm grant %s %s" % (CPKG, perm))); on = granted(CPKG, perm)
    return off is False and on is True, {"after_revoke": off, "after_grant": on}


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
    d.sh(d.u("am set-standby-bucket %s restricted" % CPKG)); b = d.sh(d.u("am get-standby-bucket %s" % CPKG)).strip()
    d.sh(d.u("am set-standby-bucket %s active" % CPKG))
    return b in ("45", "restricted"), {"bucket": b, "after_restore": d.sh(d.u("am get-standby-bucket %s" % CPKG)).strip()}


def assistant():
    o = d.sh(d.u("cmd role add-role-holder android.app.role.ASSISTANT %s 0" % APKG)); time.sleep(3)
    holders = d.sh(d.u("cmd role get-role-holders android.app.role.ASSISTANT")).strip()
    bound = "mBound=true" in d.sh("dumpsys voiceinteraction | grep -E 'leasemem|mBound'")
    d.sh(d.u("cmd role remove-role-holder android.app.role.ASSISTANT %s 0" % APKG)); d.sh(d.u("am force-stop %s" % APKG))
    return APKG in holders and bound, {"add": o[:150], "holders": holders, "bound": bound}


def charge_counter():
    txt = d.sh("dumpsys battery")
    m = re.search(r"Charge counter: (-?\d+)", txt); lvl = re.search(r"level: (\d+)", txt)
    return bool(m and int(m.group(1)) > 0), {"charge_counter_uAh": m and int(m.group(1)), "level": lvl and int(lvl.group(1))}


def batterystats():
    """Read only the client's own uid lines (no reset: resetting would erase the owner's battery history)."""
    p = bg_client(); uid = d.sh("stat -c %%u /proc/%s" % p).strip()
    tag = "u%da%d" % (int(uid) // 100000, int(uid) % 100000 - 10000) if uid.isdigit() else None
    lines = [l.strip() for l in d.sh("dumpsys batterystats --charged %s" % CPKG).splitlines() if tag and tag in l]
    return bool(lines), {"uid_tag": tag, "lines": lines[:20]}


def screen():
    d.require_fg()
    d.sh("input keyevent KEYCODE_SLEEP"); time.sleep(1); off = d.sh("dumpsys power | grep -m1 mWakefulness=").strip()
    d.sh("input keyevent KEYCODE_WAKEUP"); time.sleep(1); on = d.sh("dumpsys power | grep -m1 mWakefulness=").strip()
    return "Asleep" in off or "Dozing" in off, {"after_sleep": off, "after_wakeup": on}


def wireless():
    devs = lmdrv.subprocess.run(lmdrv.ADB_CMD + ["devices", "-l"], capture_output=True, text=True, timeout=15).stdout
    res = {"tls_port": d.sh("getprop service.adb.tls.port").strip(),
           "transports": [l.split()[0] for l in devs.splitlines()[1:] if l.strip()]}
    return any(":" in t or "_adb-tls-connect" in t for t in res["transports"]), res


def host():
    import platform
    v = lmdrv.subprocess.run(lmdrv.ADB_CMD + ["version"], capture_output=True, text=True, timeout=15).stdout
    return True, {"python": sys.version.split()[0], "platform": platform.platform(), "adb": v.strip().splitlines()[:2]}


def clock_set_back():
    """AWS only. Moves the clock back one hour with `date` (needs root) or `cmd alarm set-time`, then restores it."""
    auto = d.sh("settings get global auto_time").strip(); d.sh("settings put global auto_time 0")
    t0 = d.now_ms(); res = {"auto_time": auto, "date": d.sh("date @%d 2>&1" % (t0 // 1000 - 3600)).strip()[:120]}
    moved = d.now_ms() < t0 - 1800 * 1000
    if not moved:
        res["alarm_set_time"] = d.sh("cmd alarm set-time %d 2>&1" % (t0 - 3600 * 1000)).strip()[:120]
        moved = d.now_ms() < t0 - 1800 * 1000
    res["moved_back"] = moved
    if moved:
        d.sh("cmd alarm set-time %d" % int(time.time() * 1000))
    d.sh("settings put global auto_time %s" % (auto if auto in ("0", "1") else "1"))
    res["skew_after_restore_ms"] = d.now_ms() - int(time.time() * 1000)
    return moved, res


def sms_role():
    """AWS only. Can the mutator hold the SMS role (needed if SMS writes fail with appops WRITE_SMS alone)?"""
    role = "android.app.role.SMS"
    before = d.sh(d.u("cmd role get-role-holders %s" % role)).strip()
    o = d.sh(d.u("cmd role add-role-holder %s %s 0" % (role, lmdrv.MPKG))).strip()
    held = lmdrv.MPKG in d.sh(d.u("cmd role get-role-holders %s" % role))
    d.sh(d.u("cmd role remove-role-holder %s %s 0" % (role, lmdrv.MPKG)))
    return held, {"holders_before": before, "add": o[:150], "held": held}


def pm_clear_contacts():
    """AWS only. Clear the Contacts provider of user 0 on the wiped rented phone, then write the fixtures again."""
    o = d.sh(d.u("pm clear com.android.providers.contacts")).strip(); time.sleep(3)
    r = w.ensure_base()
    n = len(re.findall(r"^Row: ", d.sh(d.u("content query --uri content://com.android.contacts/raw_contacts --projection _id "
                                          "--where \"display_name LIKE 'LM %'\"")), re.M))
    return "Success" in o and bool(r.get("ok")) and n >= 2, {"pm_clear": o, "refixtured": r, "fixture_raw_contacts": n}


def reboot():
    """Needs the user's consent for this run. After boot the phone shows the owner's lock screen; the probe records
    what it sees, then waits (without unlocking or switching anything) until the user switches to P06 Test."""
    t = d.now_ms(); d.adb("reboot"); time.sleep(5); d.adb("wait-for-device", timeout=300)
    s = d.wait_boot()
    seen = {"current_user_after_boot": d.current_user(),
            "test_user_state_after_boot": d.sh("am get-started-user-state %d" % d.user).strip()}
    t0 = time.time(); d.after_reboot()
    # reaching this line means the run survived `adb reboot` and `adb wait-for-device` (otherwise the probe fails)
    return True, {"survived": True, "boot_s": round(s, 1), "t_reboot": t, **seen,
                  "user_back_after_s": round(time.time() - t0, 1), "client_pid_after": d.pid()}


for name, fn in ([("identity", identity), ("user_info", user_info), ("install_user", install_user),
                 ("run_as_user", run_as_user), ("read_app_files", read_files), ("content_user", content_user),
                 ("appops", appops), ("fixtures_ensure_base", fixtures), ("mutations_all_kinds", mutations),
                 ("client_probe_candidates", client_probe), ("process_user", process_user),
                 ("proc_cgroup_read", proc_reads), ("dumpsys_isFrozen", dumpsys_frozen),
                 ("freezer_debounce_2s", freezer), ("am_kill", am_kill), ("am_force_stop", force_stop),
                 ("sigkill_kill9", sigkill), ("pm_revoke_grant", revoke_grant), ("battery_unplug", battery_unplug),
                 ("doze_force_idle_deep", doze), ("standby_bucket", bucket), ("assistant_role", assistant),
                 ("charge_counter", charge_counter), ("batterystats_uid", batterystats),
                 ("screen_sleep_wake", screen), ("wireless_debugging", wireless)]
                + ([("host", host), ("clock_set_back", clock_set_back), ("sms_role", sms_role),
                    ("pm_clear_contacts", pm_clear_contacts)] if d.aws else [])):
    probe(name, fn)
if "--allow-reboot" in sys.argv:
    probe("reboot", reboot)
d.launch()
f.close()
