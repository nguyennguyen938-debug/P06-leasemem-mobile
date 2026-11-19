#!/usr/bin/env python3
"""G11 (F3 task 14), AWS mode only: where does NOTIFY_NO_DELAY (1 << 15) come from? On the Galaxy S25 every Contacts
callback carried flags 0x8001 and arrived in about 12 ms in the background, while MediaStore (5, 9), Calendar (1) and
Settings (1) callbacks carried no such bit (B13 run 6733ecc3); on the Pixel 8 Contacts carried 1.

The client runs in the background, unfrozen, as in B1 bg_unfrozen (freezer debounce 600 s). Each trial restarts it,
then runs every case once and records the client's first callback for the case's source after the action: its flags
(ContentObserver.onChange(selfChange, uris, flags)), its delay and every flag value seen. Cases:
  mut_contacts        the mutator app updates a P06 Contacts fixture (the B1 mutation)
  shell_contacts      the shell uid updates the fixture "LM Omar" (`content update`, starred), another writer
  notify_contacts_f0  the mutator app calls notifyChange(content://com.android.contacts/raw_contacts, null, 0) with
                      no write: a NO_DELAY bit seen here is added after the provider, by ContentService
  notify_contacts_f1  the same with flags 1 (NOTIFY_SYNC_TO_NETWORK, what the Pixel 8's provider sends)
  notify_calendar_f0  the same on content://com.android.calendar/events (another authority, control)
  mut_calendar, mut_media, mut_settings   the mutator app updates these sources (the other providers)
`dumpsys content` (observer table, lines with contacts or the client's pid) is kept once per trial.
Usage: notify_flags.py SERIAL OUT.jsonl [N=10]
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "revision"))
from run import setup, lmdrv

serial, out = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
c, w = setup(serial, Path(out).parent); d = c.d
if not d.aws:
    raise SystemExit("notify_flags.py writes as the shell uid: AWS mode only (a wiped rented phone)")
P = lmdrv.CPKG
NO_DELAY = 1 << 15
CASES = [("mut_contacts", "contacts"), ("shell_contacts", "contacts"), ("notify_contacts_f0", "contacts"),
         ("notify_contacts_f1", "contacts"), ("notify_calendar_f0", "calendar"), ("mut_calendar", "calendar"),
         ("mut_media", "media"), ("mut_settings", "settings")]
URI = {"contacts": "content://com.android.contacts/raw_contacts", "calendar": "content://com.android.calendar/events"}


def memory():
    return json.loads(d.cat(P, "files/mem.json"))


def act(case, src, i):
    if case.startswith("mut_"):
        m = w.mutate(src, "update"); return m["t_pre"], m
    if case == "shell_contacts":
        t = d.now_ms()
        o = d.sh(d.u("content update --uri %s --bind starred:i:%d --where \"display_name='LM Omar'\"" % (URI["contacts"], (i + 1) % 2)))
        return t, {"out": o.strip()}
    flags = case.rsplit("_f", 1)[1]
    r = d.mut("notify", URI[src], flags); return r["t_pre"], r


d.sh("device_config set_sync_disabled_for_tests until_reboot")
d.sh("device_config put activity_manager_native_boot freeze_debounce_timeout 600000")
with lmdrv.open_new(out) as f:
    for i in range(n):
        try:   # B1 bg_unfrozen: restart, open, fixtures, HOME
            d.sh(d.u("am force-stop " + P)); d.sh(d.u("am start -W -n %s/org.leasemem.client.Main" % P)); time.sleep(.4)
            w.ensure_base(); time.sleep(.5); d.home(); time.sleep(1.5)
            pid = d.pid(P)
            table = d.sh("dumpsys content | grep -m60 -E 'contacts|pid=%s '" % pid) if pid else None
            start_err = None
        except Exception as e:
            pid, table, start_err = None, None, repr(e)
        for case, src in CASES:
            r = {**d.meta(), "serial": serial, "exp": "notify_flags", "trial": i, "case": case, "source": src,
                 "writer": case.split("_")[0], "client_pid": pid}
            if case == CASES[0][0]:
                r["observer_table"] = table
            try:
                if start_err:
                    raise RuntimeError("client start: " + start_err)
                r["frozen_before"] = d.frozen(P)
                t_pre, r["action"] = act(case, src, i); r["t_pre"] = t_pre
                t0, ev = time.monotonic(), []
                while time.monotonic() - t0 < 13:      # a background observer may wait about 10 s (Pixel 8)
                    ev = [e for e in memory().get("events", []) if e.get("src") == src and e["t"] >= t_pre]
                    if ev:
                        time.sleep(1); ev = [e for e in memory().get("events", []) if e.get("src") == src and e["t"] >= t_pre]
                        break
                    time.sleep(.8)
                r["n_events"] = len(ev); r["flags_all"] = sorted({e.get("flags", 0) for e in ev})
                if ev:
                    first = min(ev, key=lambda e: e["t"])
                    r.update(first_delay_ms=first["t"] - t_pre, first_flags=first.get("flags", 0),
                             first_no_delay=bool(first.get("flags", 0) & NO_DELAY), first_uris=first.get("uris", [])[:4])
                r["pid_after"] = d.pid(P)
            except Exception as e:
                r["error"] = repr(e)
            f.write(json.dumps(r) + "\n"); f.flush()
            print(i, case, r.get("first_flags"), r.get("first_delay_ms"), r.get("error", "")[:100], flush=True)
d.sh(d.u("am force-stop " + P))
