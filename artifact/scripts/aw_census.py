#!/usr/bin/env python3
"""E5: where does the state behind AndroidWorld tasks live, and what change evidence does each store expose?

Code inspection, not an emulator run. Enumerates the 116-task AndroidWorld family from the pinned checkout
(google-research/android_world @ 55ddaf5e) with the shared venv, maps each task to the store(s) its validator
reads (manual map below, each entry justified by a file in the checkout), and maps each store to an evidence
class measured in E1 (or, for app-private stores, to 'gui-only').
Run with: AW_CHECKOUT=<android_world checkout at the pinned commit> <its venv python> artifact/scripts/aw_census.py
The app->store table (STORE below) is the census input; the mapping is app-level (task.app_names -> store).
"""
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "results", "derived")
AW = os.environ.get("AW_CHECKOUT", os.path.join(HERE, "..", "..", "..", "shared-android", "android_world"))
AW_COMMIT = "55ddaf5edc6f6c25673aed343907d5b9dca66f84"   # pinned google-research/android_world commit

# app/store -> (store, evidence class, justification)
#   watermark  : durable change evidence measured in E1 (contacts TS, call-log LAST_MODIFIED, MediaStore generation, file mtime)
#   api-only   : readable through a public API, but no durable change evidence -> UNKNOWN, refresh via API
#   gui-only   : app-private or transient UI state -> UNKNOWN, refresh needs GUI re-observation
STORE = {
    "contacts": ("ContactsContract", "watermark", "utils/contacts_utils.py (content query)"),
    "dialer": ("CallLog", "watermark", "task_evals/single/phone.py"),
    "camera": ("MediaStore (DCIM)", "watermark", "env/device_constants.py GALLERY_DATA"),
    "simple gallery pro": ("MediaStore (Pictures)", "watermark", "task_evals/single/simple_gallery_pro.py"),
    "simple draw pro": ("Shared files (Pictures)", "watermark", "task_evals/single/simple_draw_pro.py:43 (file)"),
    "markor": ("Shared files (Documents/Markor)", "watermark", "env/device_constants.py MARKOR_DATA"),
    "files": ("Shared files (Download)", "watermark", "task_evals/single/files.py"),
    "simple sms messenger": ("Telephony SMS", "api-only", "task_evals/common_validators/sms_validators.py"),
    "settings": ("Settings / radio state", "api-only", "task_evals/single/system.py (adb settings/toggles)"),
    "clipper": ("Clipboard", "api-only", "task_evals/composite/markor_sms.py"),
    "broccoli app": ("App-private SQLite", "gui-only", "task_evals/single/recipe.py (sqlite_utils)"),
    "pro expense": ("App-private SQLite", "gui-only", "task_evals/single/expense.py (sqlite_utils)"),
    "simple calendar pro": ("App-private SQLite", "gui-only", "task_evals/single/calendar/calendar_utils.py"),
    "retro music": ("App-private SQLite", "gui-only", "task_evals/single/retro_music.py:33"),
    "vlc": ("App-private SQLite", "gui-only", "task_evals/single/vlc.py"),
    "osmand": ("App-specific dir (Android/data)", "gui-only", "env/device_constants.py OSMAND_DATA"),
    "audio recorder": ("App-specific dir (Android/data)", "gui-only", "env/device_constants.py AUDIORECORDER_DATA"),
    "clock": ("Transient UI state", "gui-only", "task_evals/single/clock.py:148 (ui_elements)"),
    "chrome": ("Web/app state", "gui-only", "task_evals/single/browser.py"),
    # information-retrieval tasks (no app_names attribute): Simple Calendar, Tasks.org, OpenTracks, Joplin
    "ir:SimpleCalendar": ("App-private SQLite", "gui-only", "task_evals/information_retrieval"),
    "ir:Tasks": ("App-private SQLite", "gui-only", "task_evals/information_retrieval"),
    "ir:SportsTracker": ("App-private SQLite", "gui-only", "task_evals/information_retrieval"),
    "ir:Notes": ("App-private SQLite", "gui-only", "task_evals/information_retrieval"),
}
RANK = {"watermark": 0, "api-only": 1, "gui-only": 2}

# Rescoping (round-3 review): which tasks need a fact about PRE-EXISTING device state, i.e. something an agent could
# have remembered from an earlier observation? Rule on the task name, applied mechanically: questions about existing
# state (information-retrieval families) and tasks that delete, move, edit, merge, reply to, resend, transcribe, copy
# from, or build on existing items. Tasks that only create content from parameters in the goal, toggle settings,
# take photos/recordings or open apps do not.
import re
READS_STATE = re.compile(r"Delete|Move|Edit|Change|AddNoteHeader|Merge|Transcribe|Reply|Resend|ReceivedAddress|"
                         r"From(Gallery|Markor|Image|Clipboard)|ClipboardContent|SaveCopyOf|PlayingQueue|PlaylistDuration|"
                         r"RetroCreatePlaylist|RetroSavePlaylist|VlcCreate|"
                         r"^Notes(?!.*Create)|^Tasks|^SportsTracker|"
                         r"^SimpleCalendar(AnyEvents|EventOnDate|EventsIn|EventsOn|FirstEvent|LocationOf|NextEvent|NextMeeting)")


def main():
    sys.path.insert(0, AW)
    from android_world import registry
    r = registry.TaskRegistry()
    reg = r.get_registry(r.ANDROID_WORLD_FAMILY)
    rows = []
    for name, cls in sorted(reg.items()):
        apps = list(getattr(cls, "app_names", ()) or ())
        if not apps:
            for p in ("SimpleCalendar", "Tasks", "SportsTracker", "Notes"):
                if name.startswith(p):
                    apps = ["ir:" + p]
        classes = [STORE[a][1] for a in apps]
        worst = max(classes, key=lambda c: RANK[c]) if classes else "gui-only"
        rows.append({"task": name, "apps": "+".join(apps), "stores": "+".join(STORE[a][0] for a in apps),
                     "classes": "+".join(classes), "task_class": worst,
                     "any_watermark": int("watermark" in classes), "reads_state": int(bool(READS_STATE.search(name)))})
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "aw_census_tasks.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    # per-store summary (a task counts once per store it touches)
    per = {}
    for row in rows:
        for a in row["apps"].split("+"):
            s, c, j = STORE[a]
            k = (s, c)
            per.setdefault(k, {"store": s, "class": c, "tasks": 0, "apps": set(), "where": j})
            per[k]["tasks"] += 1
            per[k]["apps"].add(a)
    with open(os.path.join(OUT, "aw_census_stores.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["store", "class", "tasks", "apps", "where"])
        for v in sorted(per.values(), key=lambda v: (RANK[v["class"]], -v["tasks"])):
            w.writerow([v["store"], v["class"], v["tasks"], ";".join(sorted(v["apps"])), v["where"]])
    summ = {c: sum(1 for x in rows if x["task_class"] == c) for c in RANK}
    summ["n_tasks"] = len(rows)
    summ["aw_commit"] = AW_COMMIT
    summ["mapping"] = "app-level"
    summ["any_watermark"] = sum(x["any_watermark"] for x in rows)
    R = [x for x in rows if x["reads_state"]]
    summ["reads_state"] = {c: sum(1 for x in R if x["task_class"] == c) for c in RANK}
    summ["reads_state"]["n_tasks"] = len(R)
    summ["reads_state"]["any_watermark"] = sum(x["any_watermark"] for x in R)
    with open(os.path.join(OUT, "aw_census_summary.json"), "w") as f:
        json.dump(summ, f, indent=1)
    print(json.dumps(summ))


if __name__ == "__main__":
    main()
