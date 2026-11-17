#!/usr/bin/env python3
"""E4: cost of re-observing a remembered fact through the GUI (real apps, real emulator).

A GUI agent that cannot query a provider must re-open the app and read the screen. We measure a best case:
deep-link intent straight to the screen that shows the fact, then uiautomator dumps until the expected value
is visible. No LLM inference is included, so these are lower bounds on an agent's re-observation cost.
Usage: e4_gui_cost.py SERIAL N SEED OUT.jsonl
"""
import json, os, random, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lmdrv

serial, n, seed, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)


def digits(s):
    return re.sub(r"\D", "", s or "")


def visible(xml):
    """Only what is shown: text and content-desc attributes (not bounds or resource ids)."""
    return " ".join(re.findall(r'(?:text|content-desc)="([^"]*)"', xml))


def dump():
    d.sh("uiautomator dump /sdcard/lm_ui.xml >/dev/null 2>&1")
    return d.sh("cat /sdcard/lm_ui.xml")


def contact_id():
    out = d.sh("content query --uri content://com.android.contacts/contacts --projection _id:display_name --where \"display_name='LM Dana'\"")
    m = re.search(r"_id=(\d+)", out)
    return m.group(1)


def event_id():
    out = d.sh("content query --uri content://com.android.calendar/events --projection _id:title --where \"title LIKE 'LM standup%' AND deleted=0\"")
    return re.search(r"_id=(\d+)", out).group(1)


TARGETS = {
    # name: (package, intent builder, fact id, matcher)
    "contacts": ("com.google.android.contacts", lambda: "am start -W -a android.intent.action.VIEW -d content://com.android.contacts/contacts/%s" % contact_id(),
                 "c.dana", lambda xml, v: digits(v)[-7:] in digits(visible(xml))),
    "sms": ("com.google.android.apps.messaging", lambda: "am start -W -a android.intent.action.SENDTO -d sms:+15550001",
            "s.latest", lambda xml, v: v in visible(xml)),
    "calendar": ("com.google.android.calendar", lambda: "am start -W -a android.intent.action.VIEW -d content://com.android.calendar/events/%s" % event_id(),
                 "k.standup", lambda xml, v: "LM standup" in visible(xml)),
    "calllog": ("com.google.android.dialer", lambda: "am start -W -a android.intent.action.VIEW -d content://call_log/calls",
                "l.latest", lambda xml, v: digits(v)[-7:] in " ".join(digits(x) for x in visible(xml).split(" ")) or digits(v)[-7:] in digits(visible(xml))),
}

d.launch()
w.ensure_base()
with open(out, "a") as fo:
    order = [(t, cold) for t in TARGETS for cold in (0, 1)] * n
    rng.shuffle(order)
    for i, (t, cold) in enumerate(order):
        pkg, intent, fid, match = TARGETS[t]
        rec = {"i": i, "target": t, "cold": cold}
        try:
            val = d.cmd("PROBE")["probe"]["facts"][fid]
            if cold:
                d.sh("am force-stop %s" % pkg)
            d.home(); time.sleep(0.8)
            t0 = time.time()
            d.sh(intent())
            t_launch = time.time() - t0
            ok, dumps, tapped = False, 0, False
            while time.time() - t0 < 20:
                xml = dump(); dumps += 1
                if match(xml, val):
                    ok = True; break
                if t == "calllog" and not tapped:      # the call-log deep link opens Favorites; tap the Recents tab
                    m = re.search(r'text="Recents"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
                    if m:
                        x1, y1, x2, y2 = map(int, m.groups())
                        d.sh("input tap %d %d" % ((x1 + x2) // 2, (y1 + y2) // 2)); tapped = True
            rec.update({"tapped": tapped, "ok": ok, "secs": round(time.time() - t0, 3), "launch_s": round(t_launch, 3), "dumps": dumps, "val": val})
            if not ok:
                rec["xml_tail"] = xml[-600:]
        except Exception as e:
            rec["error"] = repr(e)
        fo.write(json.dumps(rec) + "\n"); fo.flush()
        print(i, t, cold, rec.get("ok"), rec.get("secs"), flush=True)
    d.home()
