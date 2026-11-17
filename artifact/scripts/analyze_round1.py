#!/usr/bin/env python3
"""Raw emulator logs (artifact/results/raw/*.jsonl) -> derived CSVs + summary.json.

Standard library only. Deterministic (bootstrap uses a fixed seed). Every number in the paper's results comes
from the files written here, through render.py.
"""
import csv
import glob
import json
import math
import os
import random
import statistics as st
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "results", "raw")
DER = os.path.join(HERE, "..", "results", "derived")
os.makedirs(DER, exist_ok=True)
SUMMARY = {}

SOURCES = ["contacts", "sms", "calllog", "media", "calendar", "settings", "files"]
GAPS = ["none", "freeze", "doze", "unregister", "kill", "forcestop", "perm", "reboot"]
AUTH = {"contacts": "com.android.contacts", "sms": "sms", "calllog": "call_log", "media": "media",
        "calendar": "com.android.calendar", "settings": "settings"}
TTLS = [5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 300]


# ---------------------------------------------------------------- statistics
def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def boot_ci(xs, stat=st.median, B=2000, seed=7):
    if not xs:
        return (float("nan"),) * 3
    rng = random.Random(seed)
    v = [stat([rng.choice(xs) for _ in xs]) for _ in range(B)]
    v.sort()
    return (stat(xs), v[int(0.025 * B)], v[int(0.975 * B) - 1])


def fisher_two_sided(a, b, c, d):
    """2x2 table [[a,b],[c,d]] two-sided Fisher exact p-value."""
    n1, n2, m1 = a + b, c + d, a + c
    N = n1 + n2

    def lp(x):
        return (math.lgamma(n1 + 1) - math.lgamma(x + 1) - math.lgamma(n1 - x + 1) +
                math.lgamma(n2 + 1) - math.lgamma(m1 - x + 1) - math.lgamma(n2 - m1 + x + 1) -
                (math.lgamma(N + 1) - math.lgamma(m1 + 1) - math.lgamma(N - m1 + 1)))
    lo, hi = max(0, m1 - n2), min(n1, m1)
    p0 = lp(a)
    return min(1.0, sum(math.exp(lp(x)) for x in range(lo, hi + 1) if lp(x) <= p0 + 1e-9))


def holm(ps):
    idx = sorted(range(len(ps)), key=lambda i: ps[i])
    out = [0] * len(ps)
    m = len(ps)
    run = 0
    for r, i in enumerate(idx):
        run = max(run, min(1.0, (m - r) * ps[i]))
        out[i] = run
    return out


def load(pattern):
    rows = []
    for p in sorted(glob.glob(os.path.join(RAW, pattern))):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def wcsv(name, rows, fields=None):
    if not rows:
        return
    fields = fields or list(rows[0].keys())
    with open(os.path.join(DER, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- E1 coverage
CANDS = [  # source, probe key, label
    ("contacts", "contacts.max_last_updated", "max last-updated ts"),
    ("contacts", "contacts.max_deleted_ts", "max deleted-contact ts"),
    ("contacts", "contacts.count", "row count"),
    ("calllog", "calllog.max_last_modified", "max \\texttt{LAST\\_MODIFIED}"),
    ("calllog", "calllog.max_id", "max \\texttt{\\_id}"),
    ("sms", "sms.max_id", "max \\texttt{\\_id}"),
    ("sms", "sms.max_date", "max \\texttt{date}"),
    ("sms", "sms.count", "row count"),
    ("media", "media.generation", "\\texttt{getGeneration}"),
    ("media", "media.max_gen_modified", "max \\texttt{generation\\_modified}"),
    ("calendar", "calendar.max_id", "max \\texttt{\\_id}"),
    ("calendar", "calendar.sum_dirty", "sum \\texttt{dirty}"),
    ("files", "files.dir_mtime", "directory mtime"),
    ("files", "files.max_file_mtime", "max file mtime"),
]
ADAPTER = {  # adapter-level detection from candidates (direction-insensitive "moved")
    "contacts": ["contacts.max_last_updated", "contacts.max_deleted_ts"],
    "calllog": ["calllog.max_last_modified"],
    "media": ["media.generation"],
    "files": ["files.dir_mtime", "files.max_file_mtime"],
}


def e1():
    rows = [r for r in load("e1_coverage_*.jsonl") if "error" not in r]
    SUMMARY["e1_trials"] = len(rows)
    cells = defaultdict(lambda: {"n": 0, "chg": 0, "up": 0, "down": 0})
    adapter = defaultdict(lambda: {"n": 0, "det": 0})
    events = defaultdict(lambda: {"n": 0, "ev": 0, "lat": []})
    events_fg = defaultdict(lambda: {"n": 0, "ev": 0, "lat": []})
    for r in rows:
        p0, p1 = r["p0"], r["p1"]
        evs = defaultdict(list)
        for e in r.get("events") or []:
            evs[e["src"]].append(e["t"])
        for m in r["muts"]:
            s, k = m["src"], m["kind"]
            for src, key, lab in CANDS:
                if src != s:
                    continue
                c = cells[(key, k)]
                c["n"] += 1
                a, b = num(p0.get(key)), num(p1.get(key))
                if p0.get(key) != p1.get(key):
                    c["chg"] += 1
                    if a is not None and b is not None:
                        c["up" if b > a else "down"] += 1
            if s in ADAPTER:
                ad = adapter[(s, k)]
                ad["n"] += 1
                ad["det"] += int(any(p0.get(x) != p1.get(x) for x in ADAPTER[s]))
            if k != "none":
                ev = (events_fg if r.get("fg") else events)[s]
                ev["n"] += 1
                if evs[s]:
                    ev["ev"] += 1
                    ev["lat"].append(min(evs[s]) - m["t_pre"])
    out = []
    for src, key, lab in CANDS:
        row = {"source": src, "key": key, "label": lab}
        for k in ["insert", "update", "delete", "none"]:
            c = cells.get((key, k))
            if not c:
                row[k] = ""
                continue
            row[k + "_k"], row[k + "_n"] = c["chg"], c["n"]
            row[k + "_down"] = c["down"]
            row[k] = "%d/%d" % (c["chg"], c["n"])
        out.append(row)
    fields = ["source", "key", "label"] + [k + s for k in ["insert", "update", "delete", "none"] for s in ["", "_k", "_n", "_down"]]
    wcsv("e1_candidates.csv", out, fields)
    ad = []
    for s in ADAPTER:
        row = {"source": s}
        for k in ["insert", "update", "delete", "none"]:
            c = adapter.get((s, k), {"n": 0, "det": 0})
            row[k + "_k"], row[k + "_n"] = c["det"], c["n"]
        ad.append(row)
    wcsv("e1_adapters.csv", ad)
    evrows = []
    for s in SOURCES:
        e = events[s]
        lat = [x for x in e["lat"] if x < 60000]       # drop trials straddling a host sleep
        p, lo, hi = wilson(e["ev"], e["n"])
        evrows.append({"source": s, "n": e["n"], "delivered": e["ev"], "rate": p,
                       "lat_med_ms": st.median(lat) if lat else "", "lat_min_ms": min(lat) if lat else "",
                       "lat_max_ms": max(lat) if lat else "", "n_lat": len(lat), "n_lat_dropped": len(e["lat"]) - len(lat)})
    wcsv("e1_events.csv", evrows)
    lat_rows = [{"source": s, "fg": 0, "lat_ms": x} for s in SOURCES for x in sorted(events[s]["lat"]) if x < 60000]
    lat_rows += [{"source": s, "fg": 1, "lat_ms": x} for s in SOURCES for x in sorted(events_fg[s]["lat"]) if x < 60000]
    fgl = [x for s in SOURCES if s != "files" for x in events_fg[s]["lat"] if x < 60000]
    SUMMARY["e1_fg_trials"] = sum(1 for r in rows if r.get("fg"))
    SUMMARY["e1_fg_provider_lat_med_ms"] = st.median(fgl) if fgl else None
    wcsv("e1_latency.csv", lat_rows)
    pr = [x for x in evrows if x["source"] not in ("files",) and x["lat_med_ms"] != ""]
    SUMMARY["e1_provider_lat_med_ms"] = st.median([x["lat_med_ms"] for x in pr]) if pr else None
    SUMMARY["e1_files_lat_med_ms"] = next((x["lat_med_ms"] for x in evrows if x["source"] == "files"), None)


# ---------------------------------------------------------------- E2 gaps
POL = ["ev", "te", "trig", "lme", "lm", "gl"]


def trig_fired(trial, phase_tdec):
    fired = set()
    reset = None
    for line in (trial.get("trig") or "").splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == "RESET":
            reset = int(p[1])
        elif p[0] == "FIRE" and reset is not None and int(p[1]) <= phase_tdec:
            for s, a in AUTH.items():
                if a in line.split("|")[0].split():
                    fired.add(s)
    return fired


def classify(trial, phase):
    D = trial[phase]
    facts = D["facts"]
    fired = trig_fired(trial, D["t_dec"])
    out = {}
    for fid, v in facts.items():
        src = v["src"]
        stale = v["mem"] != v["truth"]
        lab = {"ev": v["ev"] == "REFRESH", "te": v["te"] == "REFRESH", "gl": True,
               "lm": v["lm"] != "FRESH", "lme": v["lme"] != "FRESH"}
        if src == "derived":
            deps = v["deps"]
            lab["trig"] = any(out.get(d, {}).get("refresh", {}).get("trig", False) for d in deps) or lab["ev"]
            ns = v["refresh_ns"]
        else:
            lab["trig"] = lab["ev"] or (src in fired)
            ns = v["refresh_ns"]
        out[fid] = {"src": src, "changed": stale, "refresh": lab, "lm_label": v["lm"], "refresh_ns": ns,
                    "t_obs": v.get("t_obs") or D["t_obs"]}
    return out


def e2():
    trials = load("e2_*.jsonl")
    ok, bad = [], Counter()
    for t in trials:
        if "error" in t or "early" not in t:
            bad["error"] += 1
            continue
        dur = (t["late"]["t_dec"] - t["t_obs"]) / 1000.0
        limit = 400 if t["gap"] == "reboot" else 120
        if dur > limit:                                   # straddled a host sleep (emulator paused)
            bad["host_sleep"] += 1
            continue
        ok.append(t)
    SUMMARY["e2_trials_raw"] = len(trials)
    SUMMARY["e2_trials_ok"] = len(ok)
    SUMMARY["e2_excluded_error"] = bad["error"]
    SUMMARY["e2_excluded_sleep"] = bad["host_sleep"]
    per_gap = defaultdict(list)
    for t in ok:
        per_gap[t["gap"]].append(t)
    rows, trows, taxo, costrows, ttlrows, unkrows, prec = [], [], [], [], [], [], []
    pvals = []
    for g in GAPS:
        T = per_gap.get(g, [])
        if not T:
            continue
        # ---- gap taxonomy (what the gap does to the process and to notifications)
        survived = sum(1 for t in T if t["pid_obs"] == t["late"]["pid"])
        ev_early = ev_late = trig_any = nchg_src = 0
        reasons = Counter()
        new_exit = 0
        for t in T:
            muts = [m for m in t["muts"]]
            msrc = set(m["src"] for m in muts if m["src"] != "files")
            for phase in ("early", "late"):
                evs = defaultdict(int)
                for e in t[phase].get("events") or []:
                    if e["t"] >= t["t_gap_start"]:
                        evs[e["src"]] += 1
                hit = sum(1 for s in msrc if evs[s] > 0)
                if phase == "early":
                    ev_early += hit
                else:
                    ev_late += hit
            fired = trig_fired(t, t["late"]["t_dec"])
            trig_any += sum(1 for s in msrc if s in fired)
            nchg_src += len(msrc)
            ex = (t["late"].get("last_start") or {}).get("exit") or {}
            if ex.get("ts", 0) > t["t_obs"]:
                new_exit += 1
                reasons[ex.get("reason")] += 1
        taxo.append({"gap": g, "n": len(T), "survived": survived, "n_src_changed": nchg_src,
                     "ev_early": ev_early, "ev_late": ev_late, "trig": trig_any, "exit_new": new_exit,
                     "exit_reasons": ";".join("%s:%d" % (k, v) for k, v in sorted(reasons.items(), key=lambda kv: str(kv[0]))),
                     "boot_s_med": st.median([t["boot_s"] for t in T]) if g == "reboot" else ""})
        for phase in ("early", "late"):
            C = [classify(t, phase) for t in T]
            for p in POL:
                stale_uses = changed = used_stale_trials = refresh = unnec = total = 0
                for t, c in zip(T, C):
                    tr_stale = False
                    for fid, x in c.items():
                        total += 1
                        r = x["refresh"][p]
                        if x["changed"]:
                            changed += 1
                            if not r:
                                stale_uses += 1
                                tr_stale = True
                        if r:
                            refresh += 1
                            if not x["changed"]:
                                unnec += 1
                    used_stale_trials += tr_stale
                pm, lo, hi = wilson(stale_uses, changed)
                pt, tlo, thi = wilson(used_stale_trials, len(T))
                rows.append({"gap": g, "phase": phase, "policy": p, "n_trials": len(T), "changed": changed,
                             "missed": stale_uses, "miss_rate": pm, "miss_lo": lo, "miss_hi": hi,
                             "trials_stale": used_stale_trials, "trial_rate": pt, "trial_lo": tlo, "trial_hi": thi,
                             "uses": total, "refresh": refresh, "refresh_rate": refresh / total, "unnecessary": unnec,
                             "unnec_rate": unnec / max(1, total - changed)})
            # ---- \sys label mix and cost (late phase is the reported one; early kept for completeness)
            lab = Counter()
            for c in C:
                for fid, x in c.items():
                    if x["src"] != "derived":
                        lab[x["lm_label"]] += 1
            n_base = sum(lab.values())
            unkrows.append({"gap": g, "phase": phase, "fresh": lab["FRESH"], "changed": lab["CHANGED"],
                            "unknown": lab["UNKNOWN"], "n": n_base})
            # ttl sweep
            for T_s in TTLS:
                miss = chg = ref = tot = 0
                for t, c in zip(T, C):
                    el = (t[phase]["t_dec"] - t["t_obs"]) / 1000.0
                    for fid, x in c.items():
                        r = el >= T_s
                        tot += 1
                        ref += r
                        if x["changed"]:
                            chg += 1
                            miss += not r
                ttlrows.append({"gap": g, "phase": phase, "ttl_s": T_s, "miss_rate": miss / max(1, chg), "refresh_rate": ref / tot,
                                "changed": chg, "missed": miss})
        # ---- per-trial cost (late decisions): ms of provider work and refresh counts
        for t in T:
            D = t["late"]
            c = classify(t, "late")
            base = {f: x for f, x in c.items() if x["src"] != "derived"}
            gl_ms = sum(x["refresh_ns"] for x in base.values()) / 1e6
            val_ms = sum(v["ns"] for k, v in D["lm_cost"].items() if isinstance(v, dict)) / 1e6 + \
                sum(v for k, v in D["lm_cost"].items() if k.startswith("probe_")) / 1e6
            lm_ref_ms = sum(x["refresh_ns"] for x in base.values() if x["refresh"]["lm"]) / 1e6
            costrows.append({"gap": g, "trial": t["trial"], "gl_ms": gl_ms, "lm_validate_ms": val_ms, "lm_refresh_ms": lm_ref_ms,
                             "lm_total_ms": val_ms + lm_ref_ms,
                             "gl_refreshes": len(base), "lm_refreshes": sum(1 for x in base.values() if x["refresh"]["lm"]),
                             "ev_refreshes": sum(1 for x in base.values() if x["refresh"]["ev"]),
                             "lm_refresh_supported": sum(1 for x in base.values() if x["refresh"]["lm"] and x["src"] in ADAPTER),
                             "n_supported": sum(1 for x in base.values() if x["src"] in ADAPTER),
                             "changed_supported": sum(1 for x in base.values() if x["changed"] and x["src"] in ADAPTER)})
        # ---- significance: event-only vs LeaseMem missed changes (late), Fisher exact
        r_ev = next(r for r in rows if r["gap"] == g and r["phase"] == "late" and r["policy"] == "ev")
        r_lm = next(r for r in rows if r["gap"] == g and r["phase"] == "late" and r["policy"] == "lm")
        p = fisher_two_sided(r_ev["missed"], r_ev["changed"] - r_ev["missed"], r_lm["missed"], r_lm["changed"] - r_lm["missed"])
        pvals.append((g, p))
    adj = holm([p for _, p in pvals])
    sig = [{"gap": g, "p": p, "p_holm": a} for (g, p), a in zip(pvals, adj)]
    wcsv("e2_policy.csv", rows)
    wcsv("e2_taxonomy.csv", taxo)
    wcsv("e2_cost.csv", costrows)
    wcsv("e2_ttl.csv", ttlrows)
    wcsv("e2_labels.csv", unkrows)
    wcsv("e2_sig.csv", sig)
    # headline aggregates
    def agg(policy, gaps, phase="late"):
        R = [r for r in rows if r["policy"] == policy and r["gap"] in gaps and r["phase"] == phase]
        k = sum(r["missed"] for r in R)
        n = sum(r["changed"] for r in R)
        return k, n
    death = ["kill", "forcestop", "perm", "reboot", "unregister"]
    for pol in POL:
        k, n = agg(pol, death)
        p, lo, hi = wilson(k, n)
        SUMMARY["death_miss_%s" % pol] = p
        SUMMARY["death_miss_%s_lo" % pol] = lo
        SUMMARY["death_miss_%s_hi" % pol] = hi
        SUMMARY["death_miss_%s_k" % pol] = k
        SUMMARY["death_changed"] = n
        k2, n2 = agg(pol, GAPS)
        SUMMARY["all_miss_%s_k" % pol] = k2
        SUMMARY["all_changed"] = n2
    SUMMARY["e2_trials_by_gap"] = {g: len(per_gap.get(g, [])) for g in GAPS}
    # durable-evidence resets across reboot: contacts watermark moving backwards, MediaStore version changing
    rb = per_gap.get("reboot", [])
    def back(t):
        a, b = t["late"]["wm_obs"].get("contacts", "0|0"), t["late"]["wm_now"].get("contacts", "0|0")
        try:
            return any(float(y) < float(x) for x, y in zip(a.split("|"), b.split("|")))
        except ValueError:
            return False
    SUMMARY["reboot_contacts_reset"] = sum(1 for t in rb if back(t))
    SUMMARY["reboot_media_version_changed"] = sum(1 for t in rb if t["late"]["wm_obs"].get("media", "|").split("|")[0] != t["late"]["wm_now"].get("media", "|").split("|")[0])
    SUMMARY["reboot_n"] = len(rb)
    SUMMARY["sigkill_fallbacks"] = sum(1 for t in per_gap.get("kill", []) if any(k.startswith("sigkill_fallback") for k in t))
    if costrows:
        gl = [r["gl_ms"] for r in costrows]
        lm = [r["lm_total_ms"] for r in costrows]
        val = [r["lm_validate_ms"] for r in costrows]
        SUMMARY["cost_gl_ms_med"], SUMMARY["cost_gl_ms_lo"], SUMMARY["cost_gl_ms_hi"] = boot_ci(gl)
        SUMMARY["cost_lm_ms_med"], SUMMARY["cost_lm_ms_lo"], SUMMARY["cost_lm_ms_hi"] = boot_ci(lm)
        SUMMARY["cost_val_ms_med"], SUMMARY["cost_val_ms_lo"], SUMMARY["cost_val_ms_hi"] = boot_ci(val)
        SUMMARY["lm_refreshes_mean"] = st.mean(r["lm_refreshes"] for r in costrows)
        SUMMARY["gl_refreshes_mean"] = st.mean(r["gl_refreshes"] for r in costrows)
        SUMMARY["lm_refresh_supported_mean"] = st.mean(r["lm_refresh_supported"] for r in costrows)
        SUMMARY["n_supported_facts"] = costrows[0]["n_supported"]
        SUMMARY["changed_supported_mean"] = st.mean(r["changed_supported"] for r in costrows)
    # per-source refresh/validate latency
    srcrows = []
    per_src_ref = defaultdict(list)
    per_src_val = defaultdict(list)
    for t in ok:
        for fid, v in t["late"]["facts"].items():
            if v["src"] != "derived":
                per_src_ref[v["src"]].append(v["refresh_ns"] / 1e6)
        for s, v in t["late"]["lm_cost"].items():
            if isinstance(v, dict):
                per_src_val[s].append(v["ns"] / 1e6)
    for s in SOURCES:
        a = boot_ci(per_src_ref[s])
        b = boot_ci(per_src_val[s])
        srcrows.append({"source": s, "refresh_ms_med": a[0], "refresh_lo": a[1], "refresh_hi": a[2],
                        "validate_ms_med": b[0], "validate_lo": b[1], "validate_hi": b[2], "n": len(per_src_ref[s])})
    wcsv("e2_source_latency.csv", srcrows)
    # per-source LeaseMem verdicts vs truth (late decisions, all gaps)
    ps = defaultdict(lambda: Counter())
    for t in ok:
        c = classify(t, "late")
        for fid, x in c.items():
            src = x["src"]
            k = ps[src]
            k["uses"] += 1
            k["changed"] += x["changed"]
            lab = x["lm_label"] if src != "derived" else ("FRESH" if not x["refresh"]["lm"] else "REFRESH")
            k["lab_" + lab] += 1
            if not x["changed"]:
                k["unchanged"] += 1
                k["unch_fresh"] += lab == "FRESH"
                k["unch_changed"] += lab == "CHANGED"
            else:
                k["chg_detected"] += lab != "FRESH"
            k["ev_miss"] += x["changed"] and not x["refresh"]["ev"]
    prow = []
    for src in SOURCES + ["derived"]:
        k = ps[src]
        if not k["uses"]:
            continue
        prow.append({"source": src, "uses": k["uses"], "changed": k["changed"], "fresh": k["lab_FRESH"], "changed_lab": k["lab_CHANGED"],
                     "unknown": k["lab_UNKNOWN"], "refresh_derived": k["lab_REFRESH"], "unchanged": k["unchanged"],
                     "unch_fresh": k["unch_fresh"], "unch_false_inval": k["unch_changed"], "chg_detected": k["chg_detected"],
                     "ev_miss": k["ev_miss"]})
    wcsv("e2_per_source.csv", prow)


# ---------------------------------------------------------------- E3 boundary
def e3():
    rows = [r for r in load("e3_*.jsonl") if r.get("res")]
    SUMMARY["e3_trials"] = len(rows)
    cells = defaultdict(list)
    resid = []
    land = Counter()
    for r in rows:
        res = r["res"]
        cells[(r["fact"], r["mode"], r["change"])].append(bool(res.get("stale")))
        if r["mode"] == "bnd" and "resid_ns" in res:
            resid.append(res["resid_ns"] / 1e6)
        if r["change"] and "mut" in r:
            t = r["mut"]["t_dev"]
            land["before_check1" if t < res["check1"] else ("in_window" if t < res["t_act"] else "after_act")] += 1
    out = []
    for (f, m, c), v in sorted(cells.items()):
        k, n = sum(v), len(v)
        p, lo, hi = wilson(k, n)
        out.append({"fact": f, "mode": m, "change": c, "stale": k, "n": n, "rate": p, "lo": lo, "hi": hi})
    wcsv("e3_boundary.csv", out)
    SUMMARY["e3_land"] = dict(land)
    if resid:
        SUMMARY["e3_resid_ms_med"], SUMMARY["e3_resid_lo"], SUMMARY["e3_resid_hi"] = boot_ci(resid)
        SUMMARY["e3_resid_ms_max"] = max(resid)
    # boundary check cost
    c2 = [sum(v["ns"] for v in r["res"]["c2"].values() if isinstance(v, dict)) / 1e6 for r in rows if r["mode"] == "bnd" and "c2" in r["res"]]
    if c2:
        SUMMARY["e3_check2_ms_med"], _, _ = boot_ci(c2)


# ---------------------------------------------------------------- E4 GUI cost
def e4():
    rows = [r for r in load("e4_*.jsonl") if "error" not in r]
    out = []
    for t in ["contacts", "sms", "calendar", "calllog"]:
        for cold in (0, 1):
            R = [r for r in rows if r["target"] == t and r["cold"] == cold]
            okr = [r["secs"] for r in R if r.get("ok")]
            m = boot_ci(okr)
            out.append({"target": t, "cold": cold, "n": len(R), "ok": len(okr), "med_s": m[0], "lo": m[1], "hi": m[2],
                        "p90_s": sorted(okr)[int(0.9 * (len(okr) - 1))] if okr else "",
                        "dumps_med": st.median([r["dumps"] for r in R if r.get("ok")]) if okr else ""})
    wcsv("e4_gui.csv", out)
    allok = [r["secs"] for r in rows if r.get("ok")]
    if allok:
        SUMMARY["e4_gui_s_med"], SUMMARY["e4_gui_s_lo"], SUMMARY["e4_gui_s_hi"] = boot_ci(allok)
        SUMMARY["e4_n"] = len(rows)
        SUMMARY["e4_ok"] = len(allok)


# ---------------------------------------------------------------- E6 pitfalls
def e6():
    rows = load("e6_*.jsonl")
    reuse = [r for r in rows if r["exp"] == "sms_reuse" and r["res"].get("ok")]
    k = sum(1 for r in reuse if r["res"]["did"].split("->")[0] == r["res"]["did"].split("->")[1])
    SUMMARY["e6_sms_reuse_k"], SUMMARY["e6_sms_reuse_n"] = k, len(reuse)
    mt = [r for r in rows if r["exp"] == "mtime"]
    same = 0
    n = 0
    for r in mt:
        a, b = r["res"]
        if not (a.get("ok") and b.get("ok")):
            continue
        m0, m1 = b["did"].split("->")
        n += 1
        same += int(m0 == m1)
    SUMMARY["e6_mtime_same_k"], SUMMARY["e6_mtime_n"] = same, n
    ck = [r for r in rows if r["exp"] == "clock"]
    out = []
    for v in ("transient", "persistent"):
        R = [r for r in ck if r["variant"] == v]
        out.append({"variant": v, "n": len(R),
                    "wm_unchanged": sum(1 for r in R if r["wm_obs"] == r["wm_now"]),
                    "guard": sum(1 for r in R if r["clock_jump"]),
                    "lm_fresh": sum(1 for r in R if r["lm"] == "FRESH"),
                    "stale_accepted": sum(1 for r in R if r["lm"] == "FRESH" and r["stale_if_used"])})
    wcsv("e6_clock.csv", out)
    for o in out:
        for k2, v2 in o.items():
            if k2 != "variant":
                SUMMARY["e6_clock_%s_%s" % (o["variant"], k2)] = v2


def e7():
    rows = load("e7_*.jsonl")
    if not rows:
        return
    died = [r for r in rows if r.get("died_at")]
    SUMMARY["e7_n"] = len(rows)
    SUMMARY["e7_died"] = len(died)
    SUMMARY["e7_switches"] = rows[0]["switches"]
    SUMMARY["e7_died_at_med"] = st.median([r["died_at"] for r in died]) if died else None
    SUMMARY["e7_reasons"] = dict(Counter(str((r.get("exit") or {}).get("reason")) + ":" + str((r.get("exit") or {}).get("desc")) for r in died))


def main():
    for fn in (e1, e2, e3, e4, e6, e7):
        try:
            fn()
        except Exception as e:                          # keep partial runs renderable; record the failure
            SUMMARY["error_" + fn.__name__] = repr(e)
            import traceback
            traceback.print_exc()
    aw = os.path.join(DER, "aw_census_summary.json")
    if os.path.exists(aw):
        SUMMARY["aw"] = json.load(open(aw))
    SUMMARY["note"] = ("All numbers are from real Android 13 emulator runs (P06Avd/P06Avd2, API 33 google_apis arm64) "
                       "driven by a deterministic script; no LLM. AndroidWorld census is code inspection.")
    with open(os.path.join(DER, "summary.json"), "w") as f:
        json.dump(SUMMARY, f, indent=1, sort_keys=True, default=str)
    print(json.dumps({k: v for k, v in SUMMARY.items() if not isinstance(v, dict)}, indent=0, default=str)[:3000])


if __name__ == "__main__":
    main()
