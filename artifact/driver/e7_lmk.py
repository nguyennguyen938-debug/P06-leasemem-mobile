#!/usr/bin/env python3
"""E7: does a background memory client survive ordinary app switching? (real emulator, 3 GB AVD)

Per trial: (re)start the client, send it to the background, then open stock apps one after another
(launcher intents, 4 s dwell). After each switch, check whether the client process still exists. On death,
record the switch index and the ApplicationExitInfo reason seen at the next client start. Emulator-specific:
this bounds nothing about real devices; it shows whether the gap occurs without any injected kill.
Usage: e7_lmk.py SERIAL N_TRIALS SWITCHES SEED OUT.jsonl
"""
import json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lmdrv

APPS = ["com.android.chrome/com.google.android.apps.chrome.Main", "com.google.android.apps.maps/com.google.android.maps.MapsActivity",
        "com.google.android.apps.photos/.home.HomeActivity", "com.google.android.youtube/.app.honeycomb.Shell$HomeActivity",
        "com.google.android.apps.youtube.music/.activities.MusicActivity", "com.google.android.gm/.ConversationListActivityGmail",
        "com.google.android.calendar/com.android.calendar.AllInOneActivity", "com.google.android.contacts/com.android.contacts.activities.PeopleActivity",
        "com.google.android.apps.messaging/.ui.ConversationListActivity", "com.google.android.dialer/.extensions.GoogleDialtactsActivity",
        "com.android.camera2/com.android.camera.CameraLauncher", "com.google.android.apps.docs/.app.NewMainProxyActivity",
        "com.android.settings/.Settings", "com.google.android.deskclock/com.android.deskclock.DeskClock"]
serial, n, k, seed, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
d = lmdrv.Dev(serial); rng = random.Random(seed)
with open(out, "a") as fo:
    for t in range(n):
        d.sh("am force-stop %s" % lmdrv.CPKG)
        d.launch(); pid0 = d.pid(); d.home(); time.sleep(2)
        died_at, adj = None, []
        order = APPS[:]; rng.shuffle(order)
        for i in range(k):
            comp = order[i % len(order)]
            d.sh("am start -n '%s' >/dev/null 2>&1" % comp)
            time.sleep(4)
            p = d.pid()
            adj.append(d.sh("cat /proc/%s/oom_score_adj 2>/dev/null" % p).strip() if p else "dead")
            if p != pid0:
                died_at = i + 1
                break
        d.home(); time.sleep(1)
        rec = {"trial": t, "switches": k, "died_at": died_at, "adj": adj}
        if died_at:
            d.launch(); time.sleep(1)
            rec["exit"] = d.cmd("PING")["last_start"].get("exit")
        rec["mem"] = d.sh("cat /proc/meminfo | head -3")
        fo.write(json.dumps(rec) + "\n"); fo.flush()
        print(t, died_at, rec.get("exit"), flush=True)
