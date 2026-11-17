#!/usr/bin/env python3
"""One-time setup before E4: dismiss first-run onboarding screens of the stock Google apps, as an agent's phone
would already have done. Taps buttons whose text/content-desc matches a fixed list; logs every tap.
Usage: onboard.py SERIAL LOG.jsonl
"""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lmdrv

serial, log = sys.argv[1], sys.argv[2]
d = lmdrv.Dev(serial)
WORDS = ["next page", "got it", "skip", "allow", "ok", "continue", "accept", "done", "next", "no thanks", "not now",
         "dismiss", "close", "start", "agree", "while using the app", "only this time", "later", "cancel"]
APPS = {"calendar": "com.google.android.calendar/com.android.calendar.AllInOneActivity",
        "dialer": "com.google.android.dialer/.extensions.GoogleDialtactsActivity",
        "contacts": "com.google.android.contacts/com.android.contacts.activities.PeopleActivity",
        "messages": "com.google.android.apps.messaging/.ui.ConversationListActivity"}
NODE = re.compile(r'<node [^>]*?text="([^"]*)"[^>]*?content-desc="([^"]*)"[^>]*?clickable="(true|false)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')


def dump():
    d.sh("uiautomator dump /sdcard/lm_ui.xml >/dev/null 2>&1")
    return d.sh("cat /sdcard/lm_ui.xml")


with open(log, "a") as fo:
    for name, comp in APPS.items():
        d.sh("am start -W -n '%s'" % comp)
        time.sleep(2.5)
        for step in range(15):
            xml = dump()
            hit = None
            for m in NODE.finditer(xml):
                text, desc = m.group(1).strip().lower(), m.group(2).strip().lower()
                for w in WORDS:
                    if text == w or desc == w:
                        hit = (w, text, desc, [int(m.group(i)) for i in range(4, 8)])
                        break
                if hit:
                    break
            if not hit:
                fo.write(json.dumps({"app": name, "step": step, "action": "none"}) + "\n")
                break
            x = (hit[3][0] + hit[3][2]) // 2
            y = (hit[3][1] + hit[3][3]) // 2
            d.sh("input tap %d %d" % (x, y))
            fo.write(json.dumps({"app": name, "step": step, "tap": hit[0], "text": hit[1], "desc": hit[2], "xy": [x, y]}) + "\n")
            print(name, step, hit[0], hit[1], hit[2], flush=True)
            time.sleep(1.5)
        d.home()
