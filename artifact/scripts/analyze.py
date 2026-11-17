#!/usr/bin/env python3
"""Raw emulator logs -> derived CSVs + summary.json (round-2 revision).

Standard library only; deterministic (fixed bootstrap seed). Every number in the paper comes from files written here
(via render.py). Inputs:
  results/raw/e1_coverage_*.jsonl          E1 evidence coverage, API 33 (round 1)
  results/raw/e1api35_*.jsonl              E1 replication on Android 15 (API 35)
  results/raw/e2v3_{bg,fg}_<gap>.jsonl     E2 v3 gap trials, API 33 (main condition; holds 0-30 s)
  results/raw/e2v3_api35_<gap>.jsonl       E2 v3 subset on API 35
  results/raw/round1/e2_<gap>.jsonl        E2 round 1 (holds 0-4 s): reported as the short-hold condition
  results/raw/e3v2_*.jsonl                 E3 v2 boundary experiment
  results/raw/e4_gui.jsonl, e6_*.jsonl, e6v2_*.jsonl, e7_*.jsonl, e8_*.jsonl
Validity rules (outcome-independent): drop trials with an error or `invalid`; freezer trials need frozen == "1"
(round-1 trials included); span (observe -> late decision) above the per-gap limit means the host slept.
"""
import csv
import glob
import json
import math
import os
import sys
import random
import statistics as st
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "results", "raw")
DER = os.path.join(HERE, "..", "results", "derived")
os.makedirs(DER, exist_ok=True)
SUMMARY = {}

SOURCES = ["contacts", "sms", "calllog", "media", "calendar", "settings", "files"]
SUPPORTED = ["contacts", "calllog", "media", "files"]
AUTH = {"contacts": "com.android.contacts", "sms": "sms", "calllog": "call_log", "media": "media",
        "calendar": "com.android.calendar", "settings": "settings"}
POL = ["ev", "te", "evr", "trig", "lme", "lmts", "lm", "gl"]
LIMIT = {"reboot": 400, "longfreeze": 1500, "longdoze": 1200, "longdoze2": 1500}


# ---------------------------------------------------------------- statistics
def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"),) * 3
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def boot_ci(xs, stat=st.median, B=2000, seed=7):
    if not xs:
        return (float("nan"),) * 3
    rng = random.Random(seed)
    v = sorted(stat([rng.choice(xs) for _ in xs]) for _ in range(B))
    return (stat(xs), v[int(0.025 * B)], v[int(0.975 * B) - 1])


def fisher_two_sided(a, b, c, d):
    n1, n2, m1 = a + b, c + d, a + c
    N = n1 + n2

    def lp(x):
        return (math.lgamma(n1 + 1) - math.lgamma(x + 1) - math.lgamma(n1 - x + 1) + math.lgamma(n2 + 1) -
                math.lgamma(m1 - x + 1) - math.lgamma(n2 - m1 + x + 1) - (math.lgamma(N + 1) - math.lgamma(m1 + 1) - math.lgamma(N - m1 + 1)))
    lo, hi = max(0, m1 - n2), min(n1, m1)
    p0 = lp(a)
    return min(1.0, sum(math.exp(lp(x)) for x in range(lo, hi + 1) if lp(x) <= p0 + 1e-9))


def holm(ps):
    idx = sorted(range(len(ps)), key=lambda i: ps[i])
    out, run, m = [0] * len(ps), 0, len(ps)
    for r, i in enumerate(idx):
        run = max(run, min(1.0, (m - r) * ps[i]))
        out[i] = run
    return out


def load(pattern):
    rows = []
    for p in sorted(glob.glob(os.path.join(RAW, pattern))):
        with open(p) as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    r["_file"] = os.path.basename(p)
                    rows.append(r)
    return rows


def wcsv(name, rows, fields=None):
    if not rows:
        return
    fields = fields or list(rows[0].keys())
    with open(os.path.join(DER, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- E1 coverage
ALLCANDS = [
    ("contacts", "contacts.max_last_updated", "max last-updated ts"),
    ("contacts", "contacts.max_deleted_ts", "max deleted-contact ts"),
    ("contacts", "contacts.sum_raw_version", "sum RawContacts \\texttt{VERSION}"),
    ("contacts", "contacts.max_raw_version", "max RawContacts \\texttt{VERSION}"),
    ("contacts", "contacts.count", "row count"),
    ("contacts", "contacts.max_id", "max \\texttt{\\_id}"),
    ("calllog", "calllog.max_last_modified", "max \\texttt{LAST\\_MODIFIED}"),
    ("calllog", "calllog.max_id", "max \\texttt{\\_id}"),
    ("calllog", "calllog.max_date", "max \\texttt{date}"),
    ("calllog", "calllog.count", "row count"),
    ("sms", "sms.max_id", "max \\texttt{\\_id}"),
    ("sms", "sms.max_date", "max \\texttt{date}"),
    ("sms", "sms.count", "row count"),
    ("sms", "sms.sum_read", "sum \\texttt{read}"),
    ("media", "media.generation", "\\texttt{getGeneration}"),
    ("media", "media.max_gen_modified", "max \\texttt{generation\\_modified}"),
    ("media", "media.max_id", "max \\texttt{\\_id}"),
    ("media", "media.count", "row count"),
    ("calendar", "calendar.max_id", "max \\texttt{\\_id}"),
    ("calendar", "calendar.sum_dirty", "sum \\texttt{dirty}"),
    ("calendar", "calendar.count_deleted", "sum \\texttt{deleted}"),
    ("calendar", "calendar.count", "row count (rejected: ERR)"),
    ("files", "files.dir_mtime", "directory mtime"),
    ("files", "files.max_file_mtime", "max file mtime"),
    ("files", "files.media_count", "MediaStore rows (rejected: ERR)"),
    ("files", "files.media_max_gen", "MediaStore max generation (rejected: ERR)"),
]
MAIN_KEYS = ["contacts.max_last_updated", "contacts.max_deleted_ts", "contacts.sum_raw_version", "calllog.max_last_modified",
             "calllog.max_id", "sms.max_id", "sms.max_date", "sms.count", "media.generation", "media.max_gen_modified",
             "calendar.max_id", "calendar.sum_dirty", "files.dir_mtime", "files.max_file_mtime"]


def coverage(rows, tag):
    cells = defaultdict(lambda: {"n": 0, "chg": 0, "up": 0, "down": 0, "err": 0})
    events = defaultdict(lambda: {"n": 0, "ev": 0, "lat": [], "dropped": 0})
    for r in rows:
        p0, p1 = r["p0"], r["p1"]
        evs = defaultdict(list)
        for e in r.get("events") or []:
            evs[e["src"]].append(e["t"])
        for m in r["muts"]:
            s, k = m["src"], m["kind"]
            for src, key, lab in ALLCANDS:
                if src != s or key not in p0:
                    continue
                c = cells[(key, k)]
                c["n"] += 1
                if str(p0.get(key)).startswith("ERR"):
                    c["err"] += 1
                if p0.get(key) != p1.get(key):
                    c["chg"] += 1
                    a, b = num(p0.get(key)), num(p1.get(key))
                    if a is not None and b is not None:
                        c["up" if b > a else "down"] += 1
            if k != "none":
                ev = events[(s, bool(r.get("fg")))]
                ev["n"] += 1
                after = [t for t in evs[s] if t >= m["t_pre"]]   # callbacks caused by this mutation, not leftovers from setup
                if after:
                    lat = min(after) - m["t_pre"]
                    if lat < 60000:
                        ev["ev"] += 1
                        ev["lat"].append(lat)
                    else:
                        ev["dropped"] += 1
    out = []
    for src, key, lab in ALLCANDS:
        row = {"tag": tag, "source": src, "key": key, "label": lab, "main": int(key in MAIN_KEYS)}
        for k in ["insert", "update", "delete", "none"]:
            c = cells.get((key, k))
            if not c:
                continue
            row[k + "_k"], row[k + "_n"], row[k + "_down"], row[k + "_err"] = c["chg"], c["n"], c["down"], c["err"]
        out.append(row)
    evrows = []
    for (s, fg), e in sorted(events.items()):
        evrows.append({"tag": tag, "source": s, "fg": int(fg), "n": e["n"], "delivered": e["ev"], "dropped_over_60s": e["dropped"],
                       "lat_med_ms": st.median(e["lat"]) if e["lat"] else "", "lat_min_ms": min(e["lat"]) if e["lat"] else "",
                       "lat_max_ms": max(e["lat"]) if e["lat"] else ""})
    prov_bg = [x for (s, fg), e in events.items() if s != "files" and not fg for x in e["lat"]]
    prov_fg = [x for (s, fg), e in events.items() if s != "files" and fg for x in e["lat"]]
    files_bg = [x for (s, fg), e in events.items() if s == "files" and not fg for x in e["lat"]]
    SUMMARY["%s_trials" % tag] = len(rows)
    SUMMARY["%s_fg_trials" % tag] = sum(1 for r in rows if r.get("fg"))
    SUMMARY["%s_prov_bg_med_ms" % tag] = st.median(prov_bg) if prov_bg else None
    SUMMARY["%s_prov_bg_min_ms" % tag] = min(prov_bg) if prov_bg else None
    SUMMARY["%s_prov_bg_n" % tag] = len(prov_bg)
    SUMMARY["%s_prov_bg_below10s" % tag] = sum(1 for x in prov_bg if x < 10000)
    SUMMARY["%s_prov_bg_p5_ms" % tag] = sorted(prov_bg)[int(0.05 * len(prov_bg))] if prov_bg else None
    SUMMARY["%s_prov_fg_med_ms" % tag] = st.median(prov_fg) if prov_fg else None
    SUMMARY["%s_files_bg_med_ms" % tag] = st.median(files_bg) if files_bg else None
    SUMMARY["%s_lat_dropped" % tag] = sum(e["dropped"] for e in events.values())
    return out, evrows


def e1():
    r33 = [r for r in load("e1_coverage_*.jsonl") if "error" not in r]
    r35 = [r for r in load("e1api35_*.jsonl") if "error" not in r]
    c33, e33 = coverage(r33, "e1")
    rows, evr = c33, e33
    if r35:
        c35, e35 = coverage(r35, "e1api35")
        rows, evr = c33 + c35, e33 + e35
    wcsv("e1_candidates.csv", rows, ["tag", "source", "key", "label", "main"] +
         [k + s for k in ["insert", "update", "delete", "none"] for s in ["_k", "_n", "_down", "_err"]])
    wcsv("e1_events.csv", evr)


# ---------------------------------------------------------------- E2
def trig_fired(trial, t_dec):
    fired, reset = set(), None
    for line in (trial.get("trig") or "").splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == "RESET":
            reset = int(p[1])
        elif p[0] == "FIRE" and reset is not None and int(p[1]) <= t_dec:
            for s, a in AUTH.items():
                if a in line.split("|")[0].split():
                    fired.add(s)
    return fired


def cond_of(t):
    if t["_file"].startswith("e2v3_api35"):
        return ("api35", "v3", "bg", t["gap"])
    if t.get("protocol") == "v3":
        return ("api33", "v3", "fg" if t.get("fg") else "bg", t["gap"])
    return ("api33", "r1", "bg", t["gap"])


def valid(t):
    if "error" in t or "early" not in t or t.get("invalid"):
        return False, "error_or_invalid"
    if t.get("protocol") == "v3" and bool(t["late"].get("fg")) != bool(t.get("fg")) and t["gap"] not in ("kill", "sigkill", "forcestop", "perm", "reboot"):
        return False, "client_mode_mismatch"
    if t.get("protocol") == "v3" and bool(t["early"].get("fg")) != bool(t.get("fg")):
        return False, "client_mode_mismatch"
    if t["gap"] == "longdoze2" and not (t.get("state_m1") == "IDLE" and t.get("state_m2") == "IDLE"
                                         and t.get("frozen_m1") != "1" and t.get("frozen_m2") != "1"):
        return False, "doze_not_idle_or_frozen"
    if t["gap"] in ("freeze", "longfreeze") and str(t.get("frozen")) != "1":
        return False, "not_frozen"
    span = (t["late"]["t_dec"] - t["t_obs"]) / 1000.0
    limit = LIMIT.get(t["gap"], 120 + (t.get("hold") or 0))
    if span > limit:
        return False, "host_sleep"
    return True, ""


def classify(t, phase):
    D = t[phase]
    fired = trig_fired(t, D["t_dec"])
    r1 = t.get("protocol") != "v3"
    broken_r1 = not D.get("unbroken", True)
    mut_t = {m["src"]: m.get("t_dev") for m in t.get("muts", [])}
    out = {}
    for fid, v in D["facts"].items():
        src = v["src"]
        lab = {"ev": v["ev"] == "REFRESH", "te": v["te"] == "REFRESH", "gl": True,
               "lm": v["lm"] != "FRESH", "lme": v["lme"] != "FRESH"}
        lab["lmts"] = (v.get("lmts", v["lm"]) != "FRESH")
        lab["evr"] = (v["evr"] == "REFRESH") if "evr" in v else (broken_r1 or lab["ev"])
        if src == "derived":
            lab["trig"] = lab["ev"] or any(out.get(d, {}).get("refresh", {}).get("trig", False) for d in v["deps"])
            age = None
        else:
            lab["trig"] = lab["ev"] or (src in fired)
            age = (D["t_dec"] - mut_t[src]) / 1000.0 if mut_t.get(src) else None
        out[fid] = {"src": src, "changed": v["mem"] != v["truth"], "refresh": lab, "lm_label": v["lm"],
                    "refresh_ns": v["refresh_ns"], "age": age, "derived": src == "derived"}
    return out


def decision_cost(t, phase, c):
    D = t[phase]
    base = {f: x for f, x in c.items() if not x["derived"]}
    val_ns = sum(v["ns"] for k, v in D["lm_cost"].items() if isinstance(v, dict)) + sum(v for k, v in D["lm_cost"].items() if k.startswith("probe_"))
    gl = sum(x["refresh_ns"] for x in base.values()) / 1e6
    lm = val_ns / 1e6 + sum(x["refresh_ns"] for x in base.values() if x["refresh"]["lm"]) / 1e6
    evr = sum(x["refresh_ns"] for x in base.values() if x["refresh"]["evr"]) / 1e6
    return {"gl_ms": gl, "lm_ms": lm, "val_ms": val_ns / 1e6, "evr_ms": evr,
            "lm_ref": sum(1 for x in base.values() if x["refresh"]["lm"]), "evr_ref": sum(1 for x in base.values() if x["refresh"]["evr"]),
            "gl_ref": len(base), "lm_ref_sup": sum(1 for x in base.values() if x["refresh"]["lm"] and x["src"] in SUPPORTED),
            "chg_sup": sum(1 for x in base.values() if x["changed"] and x["src"] in SUPPORTED),
            "n_sup": sum(1 for x in base.values() if x["src"] in SUPPORTED)}


def gap_effects(T):
    """Gap taxonomy of valid trials of one condition; also used by physical/analyze_phys.py."""
    survived = sum(1 for t in T if t["pid_obs"] == t["late"]["pid"])
    nsrc = ev_e = ev_l = trg = new_exit = 0
    reasons = Counter()
    for t in T:
        msrc = set(m["src"] for m in t.get("muts", []) if m["src"] != "files")
        for phase in ("early", "late"):
            evs = Counter(e["src"] for e in (t[phase].get("events") or []) if e["t"] >= t["t_gap_start"])
            hit = sum(1 for s in msrc if evs[s] > 0)
            if phase == "early":
                ev_e += hit
            else:
                ev_l += hit
        trg += sum(1 for s in msrc if s in trig_fired(t, t["late"]["t_dec"]))
        nsrc += len(msrc)
        ex = (t["late"].get("last_start") or {}).get("exit") or {}
        if ex.get("ts", 0) > t["t_obs"]:
            new_exit += 1
            reasons[ex.get("reason")] += 1
    fcl = []          # first-callback latency per mutated provider source (s), from the last decision's event list
    for t in T:
        last = t.get("vlate") or t["late"]
        for m in t.get("muts", []):
            if m["src"] == "files":
                continue
            after = [e["t"] for e in (last.get("events") or []) if e["src"] == m["src"] and e["t"] >= m["t_pre"]]
            if after:
                fcl.append((min(after) - m["t_pre"]) / 1000.0)
    fcl.sort()
    return survived, nsrc, ev_e, ev_l, trg, new_exit, reasons, fcl


def e2():
    trials = load("e2v3_*.jsonl") + load("round1/e2_*.jsonl")
    ok, why = [], Counter()
    by = defaultdict(list)
    for t in trials:
        good, reason = valid(t)
        why[(cond_of(t), reason or "ok")] += 1
        if good:
            by[cond_of(t)].append(t)
    excl = [{"platform": c[0], "protocol": c[1], "client": c[2], "gap": c[3], "reason": r, "n": n} for (c, r), n in sorted(why.items())]
    wcsv("e2_validity.csv", excl)
    rows, trows, taxo, costrows, ages, labels = [], [], [], [], [], []
    for cond, T in sorted(by.items()):
        plat, proto, client, gap = cond
        survived, nsrc, ev_e, ev_l, trg, new_exit, reasons, fcl = gap_effects(T)
        doze_idle2 = sum(1 for t in T if t.get("state_m2") == "IDLE") if gap in ("longdoze", "longdoze2") else ""
        taxo.append({"platform": plat, "protocol": proto, "client": client, "gap": gap, "n": len(T), "survived": survived,
                     "fcl_med_s": st.median(fcl) if fcl else "", "fcl_max_s": max(fcl) if fcl else "", "fcl_n": len(fcl),
                     "doze_idle_at_batch2": doze_idle2,
                     "n_src_changed": nsrc, "ev_early": ev_e, "ev_late": ev_l, "trig": trg, "exit_new": new_exit,
                     "exit_reasons": ";".join("%s:%d" % kv for kv in sorted(reasons.items(), key=lambda kv: str(kv[0]))),
                     "hold_med": st.median([t.get("hold") or 0 for t in T]),
                     "span_med_s": st.median([(t["late"]["t_dec"] - t["t_obs"]) / 1000 for t in T]),
                     "oom_adj": Counter(t.get("oom_adj_obs") for t in T).most_common(1)[0][0] if T[0].get("oom_adj_obs") else ""})
        for phase in ("early", "late"):
            C = [classify(t, phase) for t in T]
            for p in POL:
                k = n = kt = refresh = uses = unnec = kb = nb = 0
                for t, c in zip(T, C):
                    stale_trial = False
                    for fid, x in c.items():
                        uses += 1
                        r = x["refresh"][p]
                        refresh += r
                        if x["changed"]:
                            n += 1
                            nb += not x["derived"]
                            if not r:
                                k += 1; kb += not x["derived"]; stale_trial = True
                        elif r:
                            unnec += 1
                    kt += stale_trial
                pm = wilson(k, n); pt = wilson(kt, len(T)); pb = wilson(kb, nb)
                rows.append({"platform": plat, "protocol": proto, "client": client, "gap": gap, "phase": phase, "policy": p,
                             "n_trials": len(T), "changed": n, "missed": k, "miss_rate": pm[0], "miss_lo": pm[1], "miss_hi": pm[2],
                             "changed_base": nb, "missed_base": kb, "miss_base_rate": pb[0],
                             "trials_stale": kt, "trial_rate": pt[0], "trial_lo": pt[1], "trial_hi": pt[2],
                             "uses": uses, "refresh": refresh, "refresh_rate": refresh / max(1, uses),
                             "unnecessary": unnec, "unnec_rate": unnec / max(1, uses - n)})
            # change-age analysis (base facts only)
            for t, c in zip(T, C):
                for fid, x in c.items():
                    if x["changed"] and x["age"] is not None:
                        ages.append({"platform": plat, "protocol": proto, "client": client, "gap": gap, "phase": phase,
                                     "age_s": round(x["age"], 2), "ev_miss": int(not x["refresh"]["ev"]),
                                     "evr_miss": int(not x["refresh"]["evr"]), "lm_miss": int(not x["refresh"]["lm"])})
            lab = Counter(x["lm_label"] for c in C for x in c.values() if not x["derived"])
            labels.append({"platform": plat, "protocol": proto, "client": client, "gap": gap, "phase": phase,
                           "fresh": lab["FRESH"], "changed": lab["CHANGED"], "unknown": lab["UNKNOWN"], "n": sum(lab.values())})
        for t in T:
            c = classify(t, "late")
            row = decision_cost(t, "late", c)
            row.update({"platform": plat, "protocol": proto, "client": client, "gap": gap, "trial": t["trial"]})
            costrows.append(row)
    wcsv("e2_policy.csv", rows)
    wcsv("e2_taxonomy.csv", taxo)
    wcsv("e2_ages.csv", ages)
    inep = [a for a in ages if a["protocol"] == "v3" and a["gap"] in ("none", "freeze", "dozeidle", "bucket")]
    for plat, client in (("api33", "bg"), ("api35", "bg"), ("api33", "fg")):
        A = [a for a in inep if a["platform"] == plat and a["client"] == client]
        lt = [a for a in A if a["age_s"] < 10]; ge = [a for a in A if a["age_s"] >= 10]
        tag = "%s_%s" % (plat, client)
        SUMMARY["age_%s_lt10_k" % tag], SUMMARY["age_%s_lt10_n" % tag] = sum(a["ev_miss"] for a in lt), len(lt)
        SUMMARY["age_%s_ge10_k" % tag], SUMMARY["age_%s_ge10_n" % tag] = sum(a["ev_miss"] for a in ge), len(ge)
        missed = [a["age_s"] for a in A if a["ev_miss"]]
        SUMMARY["age_%s_max_missed" % tag] = max(missed) if missed else None
    wcsv("e2_labels.csv", labels)
    wcsv("e2_cost.csv", costrows)
    # trial-level tests (trials with >=1 stale decision), restart-aware vs LeaseMem at the early decision, v3 cells
    # in which restart-aware has stale trials (LeaseMem has zero observed stale trials in these cells); platform reported explicitly
    sig, ps = [], []
    R = {(r["platform"], r["protocol"], r["client"], r["gap"], r["phase"], r["policy"]): r for r in rows}
    for key, r in sorted(R.items()):
        if key[1] != "v3" or key[4] != "early" or key[5] != "evr" or r["trials_stale"] == 0:
            continue
        lm = R[key[:5] + ("lm",)]
        a, n1, c, n2 = r["trials_stale"], r["n_trials"], lm["trials_stale"], lm["n_trials"]
        assert n1 == n2 and c == 0, "paired outcome reconstruction required for new nonzero cells"
        # Since lm has zero stale trials, all a discordant pairs favor lm.
        p = min(1.0, 2.0 ** (1 - a))
        sig.append({"platform": key[0], "client": key[2], "gap": key[3], "phase": key[4], "evr": "%d/%d" % (a, n1), "lm": "%d/%d" % (c, n2), "p": p})
        ps.append(p)
    for s_, a in zip(sig, holm(ps)):
        s_["p_holm"] = a
    wcsv("e2_sig.csv", sig)
    # headline aggregates (API 33, v3, background unless stated)
    def agg(pol, gaps, client="bg", phase="late", proto="v3", plat="api33", base=False):
        RR = [r for r in rows if r["policy"] == pol and r["gap"] in gaps and r["phase"] == phase and r["client"] == client
              and r["protocol"] == proto and r["platform"] == plat]
        kk = "missed_base" if base else "missed"; nn = "changed_base" if base else "changed"
        return sum(r[kk] for r in RR), sum(r[nn] for r in RR), sum(r["trials_stale"] for r in RR), sum(r["n_trials"] for r in RR)
    death = ["kill", "forcestop", "perm", "reboot", "unregister"]
    allg = ["none", "freeze", "dozeidle", "bucket", "unregister", "kill", "forcestop", "perm", "reboot", "longfreeze", "longdoze", "longdoze2"]
    for pol in POL:
        for nm, gs, ph in [("death", death, "late"), ("all", allg, "late"), ("allearly", allg, "early"), ("susp", ["none", "freeze", "dozeidle", "bucket"], "early")]:
            k, n, kt, nt = agg(pol, gs, phase=ph)
            p = wilson(k, n); q = wilson(kt, nt)
            SUMMARY.update({"%s_%s_k" % (nm, pol): k, "%s_n" % nm: n, "%s_%s_rate" % (nm, pol): p[0], "%s_%s_lo" % (nm, pol): p[1],
                            "%s_%s_hi" % (nm, pol): p[2], "%s_%s_tk" % (nm, pol): kt, "%s_tn" % nm: nt,
                            "%s_%s_trate" % (nm, pol): q[0], "%s_%s_tlo" % (nm, pol): q[1], "%s_%s_thi" % (nm, pol): q[2]})
        k, n, kt, nt = agg(pol, ["none", "dozeidle", "unregister", "sigkill", "forcestop", "reboot"], client="fg", phase="early")
        SUMMARY.update({"fg_early_%s_k" % pol: k, "fg_early_n": n, "fg_early_%s_tk" % pol: kt, "fg_early_tn": nt})
        k, n, kt, nt = agg(pol, ["none", "dozeidle"], client="fg", phase="early")
        SUMMARY.update({"fgin_early_%s_k" % pol: k, "fgin_early_n": n})
        k1, n1, _, t1 = agg(pol, ["none", "dozeidle", "unregister", "sigkill", "forcestop", "reboot"], client="fg", phase="late")
        k2, n2, _, t2 = agg(pol, ["none", "dozeidle", "unregister", "sigkill", "forcestop", "reboot"], client="fg", phase="early")
        SUMMARY.update({"fg_any_%s_k" % pol: k1 + k2, "fg_any_n": n1 + n2})
        k1, n1, _, _ = agg(pol, ["none", "kill", "unregister", "freeze"], plat="api35", phase="late")
        k2, n2, _, _ = agg(pol, ["none", "kill", "unregister", "freeze"], plat="api35", phase="early")
        SUMMARY.update({"api35_any_%s_k" % pol: k1 + k2, "api35_any_n": n1 + n2})
        k1, n1, _, _ = agg(pol, ["longfreeze", "longdoze", "longdoze2"], phase="late")
        k2, n2, _, _ = agg(pol, ["longfreeze", "longdoze", "longdoze2"], phase="early")
        SUMMARY.update({"long_late_%s_k" % pol: k1, "long_late_n": n1, "long_early_%s_k" % pol: k2, "long_early_n": n2})
        k, n, kt, nt = agg(pol, ["none", "freeze", "dozeidle", "bucket", "unregister", "kill", "forcestop", "perm", "reboot"], proto="r1", phase="early")
        SUMMARY.update({"r1_early_%s_k" % pol: k, "r1_early_n": n})
    SUMMARY["e2_valid_by_cond"] = {"/".join(c): len(T) for c, T in by.items()}
    SUMMARY["e2_excluded"] = {"/".join(c) + ":" + r: n for (c, r), n in why.items() if r != "ok"}
    SUMMARY["e2v3_bg_trials"] = sum(len(T) for c, T in by.items() if c[:3] == ("api33", "v3", "bg"))
    SUMMARY["e2v3_fg_trials"] = sum(len(T) for c, T in by.items() if c[:3] == ("api33", "v3", "fg"))
    SUMMARY["e2r1_trials"] = sum(len(T) for c, T in by.items() if c[1] == "r1")
    SUMMARY["e2api35_trials"] = sum(len(T) for c, T in by.items() if c[0] == "api35")
    # cost (v3 bg, late)
    cr = [r for r in costrows if r["protocol"] == "v3" and r["client"] == "bg" and r["platform"] == "api33"]
    if cr:
        for k in ("gl_ms", "lm_ms", "val_ms", "evr_ms"):
            SUMMARY["cost_%s" % k], SUMMARY["cost_%s_lo" % k], SUMMARY["cost_%s_hi" % k] = boot_ci([r[k] for r in cr])
        SUMMARY["cost_lm_slower_frac"] = sum(1 for r in cr if r["lm_ms"] > r["gl_ms"]) / len(cr)
        SUMMARY["cost_n"] = len(cr)
        for k in ("lm_ref", "gl_ref", "evr_ref", "lm_ref_sup", "chg_sup", "n_sup"):
            SUMMARY["mean_%s" % k] = st.mean(r[k] for r in cr)
        brk = [r for r in cr if r["gap"] in death]
        SUMMARY["mean_evr_ref_death"] = st.mean(r["evr_ref"] for r in brk) if brk else None
        SUMMARY["mean_lm_ref_death"] = st.mean(r["lm_ref"] for r in brk) if brk else None
    # per-source provider latency (v3 bg late): refresh of one fact, LeaseMem validation of one source, TS ablation
    ref, val, valts = defaultdict(list), defaultdict(list), defaultdict(list)
    for c_, T in by.items():
        if c_[:3] != ("api33", "v3", "bg"):
            continue
        for t in T:
            D = t["late"]
            for fid, v in D["facts"].items():
                if v["src"] != "derived":
                    ref[v["src"]].append(v["refresh_ns"] / 1e6)
            for s_, v in D["lm_cost"].items():
                if isinstance(v, dict):
                    val[s_].append(v["ns"] / 1e6)
            for s_, v in (D.get("lmts_cost") or {}).items():
                if isinstance(v, dict):
                    valts[s_].append(v["ns"] / 1e6)
    srow = []
    for s_ in SOURCES:
        a, b, c = boot_ci(ref[s_]), boot_ci(val[s_]), boot_ci(valts[s_])
        srow.append({"source": s_, "refresh_ms": a[0], "refresh_lo": a[1], "refresh_hi": a[2], "validate_ms": b[0],
                     "validate_lo": b[1], "validate_hi": b[2], "validate_ts_ms": c[0], "n": len(ref[s_])})
    wcsv("e2_source_latency.csv", srow)
    # per-source verdicts (v3 bg late)
    ps_ = defaultdict(Counter)
    for c_, T in by.items():
        if c_[:3] != ("api33", "v3", "bg"):
            continue
        for t in T:
            early = classify(t, "early")
            for fid, x in classify(t, "late").items():
                k = ps_[x["src"]]
                k["evr_miss_early"] += early[fid]["changed"] and not early[fid]["refresh"]["evr"]
                k["changed_early"] += early[fid]["changed"]
                k["uses"] += 1; k["changed"] += x["changed"]
                lab = x["lm_label"] if not x["derived"] else ("FRESH" if not x["refresh"]["lm"] else "REFRESH")
                k["lab_" + lab] += 1
                if not x["changed"]:
                    k["unchanged"] += 1; k["unch_fresh"] += lab == "FRESH"; k["unch_false"] += lab == "CHANGED"
                else:
                    k["chg_detected"] += lab != "FRESH"
                k["ev_miss"] += x["changed"] and not x["refresh"]["ev"]
                k["evr_miss"] += x["changed"] and not x["refresh"]["evr"]
    wcsv("e2_per_source.csv", [dict(source=s, **ps_[s]) for s in SOURCES + ["derived"] if ps_[s]["uses"]],
         ["source", "uses", "changed", "lab_FRESH", "lab_CHANGED", "lab_UNKNOWN", "lab_REFRESH", "unchanged", "unch_fresh",
          "unch_false", "chg_detected", "ev_miss", "evr_miss", "evr_miss_early", "changed_early"])
    # durable-evidence resets across reboot: Contacts database empty after the reboot (not a mere decrease)
    resets, rbn, verch = 0, 0, 0
    for c_, T in by.items():
        if c_[3] != "reboot":
            continue
        for t in T:
            rbn += 1
            F = t["late"]["facts"]
            if F["c.set"]["truth"] == "" and F["c.set"]["mem"] != "":
                resets += 1
            wo, wn = t["late"]["wm_obs"].get("media", "|"), t["late"]["wm_now"].get("media", "|")
            verch += wo.split("|")[0] != wn.split("|")[0]
    SUMMARY["reboot_contacts_empty"], SUMMARY["reboot_n"], SUMMARY["reboot_media_version_changed"] = resets, rbn, verch
    SUMMARY["sigkill_fallbacks_r1"] = sum(1 for c_, T in by.items() if c_[1] == "r1" and c_[3] == "kill" for t in T if any(k.startswith("sigkill_fallback") for k in t))
    SUMMARY["amkill_alive_v3"] = sum(1 for c_, T in by.items() if c_[1] == "v3" and c_[3] == "kill" for t in T if t.get("alive_after_amkill"))
    # VER adapter end-to-end detection per contacts mutation kind (v3, late decision)
    ver = defaultdict(lambda: [0, 0])
    for c_, T in by.items():
        if c_[1] != "v3":
            continue
        for t in T:
            kinds = [m["kind"] for m in t.get("muts", []) if m["src"] == "contacts"] or ["none"]
            moved = t["late"]["wm_obs"].get("contacts@VER") != t["late"]["wm_now"].get("contacts@VER")
            ver[kinds[0]][0] += moved; ver[kinds[0]][1] += 1
    SUMMARY["ver_adapter"] = {k: "%d/%d" % tuple(v) for k, v in ver.items()}


# ---------------------------------------------------------------- E3 v2
def e3():
    rows = [r for r in load("e3v2_*.jsonl") if r.get("res")]
    SUMMARY["e3_trials"] = len(rows)
    cells = defaultdict(list)
    cls = Counter()
    resid = []
    for r in rows:
        res = r["res"]
        cells[(r["mode"], r["change"])].append(bool(res.get("stale")))
        if r["mode"] == "bnd":
            resid.append(res["effect_end"] - res["check2_start"])
        if r["change"] and r.get("mut"):
            m = r["mut"]
            ms, me = m["mut_start"], m["mut_end"]
            if r["mode"] == "bnd":
                if me < res["check2_start"]:
                    where = "before_check"
                elif ms > res["effect_end"]:
                    where = "after_effect"
                else:
                    where = "overlaps_check_or_residual"
            else:
                where = "before_action" if me < res["effect_start"] else ("after_effect" if ms > res["effect_end"] else "overlaps")
            cls[(r["mode"], where, bool(res.get("stale")))] += 1
    out = []
    for (m, c), v in sorted(cells.items()):
        k, n = sum(v), len(v)
        p = wilson(k, n)
        out.append({"mode": m, "change": c, "stale": k, "n": n, "rate": p[0], "lo": p[1], "hi": p[2]})
    wcsv("e3_boundary.csv", out)
    # stale rate per 10 ms of change start relative to the start of the boundary check (boundary mode, with change)
    bins = defaultdict(lambda: [0, 0])
    for r in rows:
        if r["mode"] == "bnd" and r["change"] and r.get("mut"):
            rel = r["mut"]["mut_start"] - r["res"]["check2_start"]
            if -20 <= rel < 60:
                b = int((rel + 20) // 10) * 10 - 20
                bins[b][0] += int(bool(r["res"].get("stale"))); bins[b][1] += 1
    wcsv("e3_bins.csv", [{"from_ms": b, "to_ms": b + 10, "stale": v[0], "n": v[1]} for b, v in sorted(bins.items())])
    wcsv("e3_where.csv", [{"mode": a, "where": b, "stale": int(s), "n": n} for (a, b, s), n in sorted(cls.items())])
    if resid:
        SUMMARY["e3_check_to_effect_ms"], SUMMARY["e3_cte_lo"], SUMMARY["e3_cte_hi"] = boot_ci(resid)
        SUMMARY["e3_cte_max"] = max(resid)


# ---------------------------------------------------------------- E4, E6, E7, E8
def e4():
    rows = [r for r in load("e4_gui.jsonl") if "error" not in r]
    out = []
    for t in ["contacts", "sms", "calendar", "calllog"]:
        for cold in (0, 1):
            R = [r for r in rows if r["target"] == t and r["cold"] == cold]
            okr = [r["secs"] for r in R if r.get("ok")]
            m = boot_ci(okr)
            out.append({"target": t, "cold": cold, "n": len(R), "ok": len(okr), "med_s": m[0], "lo": m[1], "hi": m[2]})
    wcsv("e4_gui.csv", out)
    allok = [r["secs"] for r in rows if r.get("ok")]
    if allok:
        SUMMARY["e4_gui_s_med"], SUMMARY["e4_gui_s_lo"], SUMMARY["e4_gui_s_hi"] = boot_ci(allok)
        SUMMARY["e4_n"], SUMMARY["e4_ok"] = len(rows), len(allok)


def e6():
    rows = load("e6_pitfalls.jsonl")
    reuse = [r for r in rows if r["exp"] == "sms_reuse" and r["res"].get("ok")]
    SUMMARY["e6_sms_reuse_k"] = sum(1 for r in reuse if r["res"]["did"].split("->")[0] == r["res"]["did"].split("->")[1])
    SUMMARY["e6_sms_reuse_n"] = len(reuse)
    mt = [r for r in rows if r["exp"] == "mtime" and all(x.get("ok") for x in r["res"])]
    SUMMARY["e6_mtime_same_k"] = sum(1 for r in mt if r["res"][1]["did"].split("->")[0] == r["res"][1]["did"].split("->")[1])
    SUMMARY["e6_mtime_n"] = len(mt)
    ck = [r for r in rows if r["exp"] == "clock"]
    for v in ("transient", "persistent"):
        R = [r for r in ck if r["variant"] == v]
        SUMMARY["e6_ts_%s_n" % v] = len(R)
        SUMMARY["e6_ts_%s_stale_accepted" % v] = sum(1 for r in R if r["lm"] == "FRESH" and r["stale_if_used"])
        SUMMARY["e6_ts_%s_guard" % v] = sum(1 for r in R if r["clock_jump"])
    v2 = load("e6v2_*.jsonl")
    for v in ("transient", "persistent"):
        R = [r for r in v2 if r["variant"] == v]
        SUMMARY["e6v2_%s_n" % v] = len(R)
        SUMMARY["e6v2_%s_ver_stale_accepted" % v] = sum(1 for r in R if r["lm_ver"] == "FRESH" and r["stale_if_used"])
        SUMMARY["e6v2_%s_ts_stale_accepted" % v] = sum(1 for r in R if r["lm_ts"] == "FRESH" and r["stale_if_used"])
        SUMMARY["e6v2_%s_ver_detected" % v] = sum(1 for r in R if r["lm_ver"] != "FRESH")


def e7():
    rows = load("e7_*.jsonl")
    if rows:
        SUMMARY["e7_n"], SUMMARY["e7_died"], SUMMARY["e7_switches"] = len(rows), sum(1 for r in rows if r.get("died_at")), rows[0]["switches"]
        adj = [int(a) for r in rows for a in r["adj"] if a.lstrip("-").isdigit()]
        SUMMARY["e7_adj_min"], SUMMARY["e7_adj_max"] = (min(adj), max(adj)) if adj else (None, None)


def e8():
    rows = [r for r in load("e8_*.jsonl") if "error" not in r]
    if not rows:
        return
    import importlib.util
    spec = importlib.util.spec_from_file_location("e8", os.path.join(HERE, "..", "driver", "e8_llm.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    sup = {n: s for n, s, _ in mod.DERIVED}
    per = []
    calls = []
    for r in rows:
        lab, chg = r["labels"], r["changed"]
        dd = r["derived_dec"]
        calls += [x["secs"] for x in dd.values()]
        P = ("gl", "evr", "ev", "lm", "memo")
        cost = {p: 0.0 for p in P}
        stale = {p: 0 for p in P}
        nre = {p: 0 for p in P}
        nchanged = 0
        do = r["derived_obs"]
        union = sorted(set(b for name in dd for b in sup[name]))
        read_all = sum(r["refresh_ms"][b] for b in union) / 1000.0          # re-read every input through the provider
        for name, x in dd.items():
            s = sup[name]
            changed = any(chg[b] for b in s)
            nchanged += changed
            redo = {"gl": True, "evr": any(lab[b]["evr"] == "REFRESH" for b in s), "ev": any(lab[b]["ev"] == "REFRESH" for b in s),
                    "lm": any(lab[b]["lm"] != "FRESH" for b in s),
                    # input memoization: keep the inputs the fact was derived from; re-derive iff a re-read input differs
                    "memo": do[name]["inputs"] != x["inputs"]}
            for p in P:
                if redo[p]:
                    cost[p] += x["secs"]; nre[p] += 1
                elif changed:
                    stale[p] += 1
        # provider reads: global, restart-aware and memoization read every input; LeaseMem validates, then reads only
        # the inputs it does not certify; event-only reads only flagged inputs
        cost["gl"] += read_all; cost["evr"] += read_all; cost["memo"] += read_all
        cost["lm"] += r["lm_validate_ms"] / 1000.0 + sum(r["refresh_ms"][b] for b in union if lab[b]["lm"] != "FRESH") / 1000.0
        cost["ev"] += sum(r["refresh_ms"][b] for b in union if lab[b]["ev"] == "REFRESH") / 1000.0
        unnec = sum(1 for name, x in dd.items() if any(lab[b]["lm"] != "FRESH" for b in sup[name]) and not any(chg[b] for b in sup[name]))
        unk = sum(1 for name, x in dd.items() if not any(chg[b] for b in sup[name]) and any(lab[b]["lm"] == "UNKNOWN" for b in sup[name]))
        row = {"gap": r["gap"], "p_change": r["p_change"], "trial": r["trial"], "n_derived": len(dd), "n_changed": nchanged,
               "lm_unnecessary": unnec, "lm_unnec_unknown": unk, "read_all_ms": round(read_all * 1000, 2)}
        for p in cost:
            row[p + "_s"], row[p + "_stale"], row[p + "_rederived"] = round(cost[p], 3), stale[p], nre[p]
        per.append(row)
    wcsv("e8_trials.csv", per)
    out = []
    for (g, pc) in sorted(set((r["gap"], r["p_change"]) for r in per)):
        R = [r for r in per if r["gap"] == g and r["p_change"] == pc]
        o = {"gap": g, "p_change": pc, "n": len(R), "n_derived": R[0]["n_derived"], "changed": sum(r["n_changed"] for r in R)}
        o["lm_unnecessary"] = sum(r["lm_unnecessary"] for r in R); o["lm_unnec_unknown"] = sum(r["lm_unnec_unknown"] for r in R)
        o["read_all_ms"] = st.median(r["read_all_ms"] for r in R)
        o["lm_faster_than_memo"] = sum(1 for r in R if r["lm_s"] < r["memo_s"])
        for p in ("gl", "evr", "ev", "lm", "memo"):
            m = boot_ci([r[p + "_s"] for r in R])
            o[p + "_s"], o[p + "_lo"], o[p + "_hi"] = m
            o[p + "_stale"] = sum(r[p + "_stale"] for r in R)
            o[p + "_rederived"] = st.mean(r[p + "_rederived"] for r in R)
        out.append(o)
    wcsv("e8_summary.csv", out)
    SUMMARY["e8_trials"] = len(per)
    SUMMARY["e8_call_s_med"], _, _ = boot_ci(calls)
    SUMMARY["e8_model"] = rows[0]["model"]


def e9():
    """Long frozen gaps: lost vs delayed callbacks to a frozen process."""
    rows = load("e9_frozen_*.jsonl")
    out = [e9_row(r, "api35" if r["_file"].endswith("_35.jsonl") else "api33") for r in rows]
    wcsv("e9_frozen.csv", out)
    e9_summary(out)


def e9_row(r, plat):
    """One E9 hold; also used by physical/analyze_phys.py."""
    if "error" in r or r.get("invalid") or "vlate" not in r:
        return {"platform": plat, "trial": r["trial"], "valid": 0, "reason": r.get("invalid") or r.get("error", "")[:60]}
    samples = r.get("frozen_samples", [])
    stayed = all(x[1] == "1" for x in samples) and r.get("frozen_at_end") == "1"
    muts = [m for m in r["muts"]]
    prov = [m for m in muts if m["src"] != "files"]
    srcs = sorted(set(m["src"] for m in muts))
    tg = r["t_gap_end"]
    def got(phase):
        ev = [e for e in (r[phase].get("events") or []) if e["t"] >= r["t_first_mut"]]
        return ev
    ev_v = got("vlate")
    per_src_lost = [s_ for s_ in srcs if not any(e["src"] == s_ for e in ev_v)]
    # callbacks for the last change of each source: did a callback arrive after that change?
    last_unseen = 0
    for s_ in srcs:
        tl = max(m["t_pre"] for m in muts if m["src"] == s_)
        if not any(e["src"] == s_ and e["t"] >= tl for e in ev_v):
            last_unseen += 1
    thaw = r["early"]["t_recv"]                     # the DECIDE broadcast thaws the process
    after = [(e["t"] - thaw) / 1000.0 for e in ev_v if e["t"] >= tg]
    first_after = after
    lm_miss = {ph: sum(1 for f, v in r[ph]["facts"].items() if v["mem"] != v["truth"] and v["lm"] == "FRESH") for ph in ("early", "late", "vlate")}
    ev_miss = {ph: sum(1 for f, v in r[ph]["facts"].items() if v["mem"] != v["truth"] and v["evr"] == "FRESH") for ph in ("early", "late", "vlate")}
    evo_miss = {ph: sum(1 for f, v in r[ph]["facts"].items() if v["mem"] != v["truth"] and v["ev"] == "FRESH") for ph in ("early", "late", "vlate")}
    died = r["pid_obs"] != r["vlate"]["pid"]
    ex = (r["vlate"].get("last_start") or {}).get("exit") or {}
    death_after = round((ex["ts"] - r["t_first_mut"]) / 1000.0, 1) if died and ex.get("ts") else ""
    return ({"platform": plat, "trial": r["trial"], "valid": 1, "stayed_frozen": int(stayed),
                "frozen_with_pending_s": r["frozen_with_pending_s"], "n_mut": len(muts), "n_mut_provider": len(prov),
                "callbacks_vlate": len(ev_v), "callbacks_early": len(got("early")), "callbacks_late": len(got("late")),
                "sources_mutated": len(srcs), "sources_no_callback": len(per_src_lost), "sources_last_change_unseen": last_unseen,
                "first_callback_after_thaw_s": min(first_after) if first_after else "",
                "last_callback_after_thaw_s": max(after) if after else "", "pid_same": int(r["pid_obs"] == r["vlate"]["pid"]),
                "evr_miss_early": ev_miss["early"], "evr_miss_late": ev_miss["late"], "evr_miss_vlate": ev_miss["vlate"],
                "lm_miss_any": lm_miss["early"] + lm_miss["late"] + lm_miss["vlate"],
                "died": int(died), "death_desc": ex.get("desc", "") if died else "", "death_after_s": death_after,
                "ev_miss_early": evo_miss["early"], "ev_miss_vlate": evo_miss["vlate"]})


def e9_summary(out):
    for plat in ("api33", "api35"):
        V = [o for o in out if o["platform"] == plat and o["valid"]]
        SUMMARY["e9_%s_valid" % plat] = len(V)
        SUMMARY["e9_%s_run" % plat] = sum(1 for o in out if o["platform"] == plat)
        if not V:
            continue
        SUMMARY["e9_%s_stayed" % plat] = sum(o["stayed_frozen"] for o in V)
        D = [o for o in V if o["died"]]
        SUMMARY["e9_%s_died" % plat] = len(D)
        SUMMARY["e9_%s_died_desc" % plat] = ";".join(sorted(set(o["death_desc"] for o in D)))
        SUMMARY["e9_%s_died_after" % plat] = ";".join(str(o["death_after_s"]) for o in D)
        SUMMARY["e9_%s_died_ev_miss_vlate" % plat] = sum(o["ev_miss_vlate"] for o in D)
        Sf = [o for o in V if o["stayed_frozen"]]
        SUMMARY["e9_%s_sf_src_mut" % plat] = sum(o["sources_mutated"] for o in Sf)
        SUMMARY["e9_%s_sf_src_lost" % plat] = sum(o["sources_no_callback"] for o in Sf)
        SUMMARY["e9_%s_sf_last_unseen" % plat] = sum(o["sources_last_change_unseen"] for o in Sf)
        SUMMARY["e9_%s_frozen_s_min" % plat] = min(o["frozen_with_pending_s"] for o in V)
        SUMMARY["e9_%s_mut_med" % plat] = st.median(o["n_mut"] for o in V)
        SUMMARY["e9_%s_mut_total" % plat] = sum(o["n_mut"] for o in V)
        SUMMARY["e9_%s_cb_total" % plat] = sum(o["callbacks_vlate"] for o in V)
        SUMMARY["e9_%s_src_mut" % plat] = sum(o["sources_mutated"] for o in V)
        SUMMARY["e9_%s_src_lost" % plat] = sum(o["sources_no_callback"] for o in V)
        SUMMARY["e9_%s_last_unseen" % plat] = sum(o["sources_last_change_unseen"] for o in V)
        SUMMARY["e9_%s_pid_same" % plat] = sum(o["pid_same"] for o in V)
        fa = [o["first_callback_after_thaw_s"] for o in V if o["first_callback_after_thaw_s"] != ""]
        SUMMARY["e9_%s_first_after_thaw_med" % plat] = st.median(fa) if fa else None
        SUMMARY["e9_%s_first_after_thaw_max" % plat] = max(fa) if fa else None
        la = [o["last_callback_after_thaw_s"] for o in V if o["last_callback_after_thaw_s"] != ""]
        SUMMARY["e9_%s_last_after_thaw_med" % plat] = st.median(la) if la else None
        SUMMARY["e9_%s_last_after_thaw_max" % plat] = max(la) if la else None
        for k in ("evr_miss_early", "evr_miss_late", "evr_miss_vlate", "lm_miss_any"):
            SUMMARY["e9_%s_%s" % (plat, k)] = sum(o[k] for o in V)
            SUMMARY["e9_%s_%s_trials" % (plat, k)] = sum(1 for o in V if o[k] > 0)


def e10_12_13():
    """E10 deployments, E11 FGS cost, E12 scale, E13 host agent: summaries (tables are rendered from raw logs)."""
    rows = load("e13_host_*.jsonl")
    if rows:
        out = []
        for ch in (False, True):
            R = [r for r in rows if r["change"] == ch]
            if not R:
                continue
            g = boot_ci([r["t_global_ms"] for r in R]); e = boot_ci([r["t_evcheck_ms"] for r in R])
            faster = sum(1 for r in R if r["t_evcheck_ms"] < r["t_global_ms"])
            out.append({"change": int(ch), "n": len(R), "global_ms": g[0], "global_lo": g[1], "global_hi": g[2],
                        "evcheck_ms": e[0], "evcheck_lo": e[1], "evcheck_hi": e[2], "evcheck_faster": faster,
                        "reread_mean": st.mean(r["n_reread"] for r in R), "changed_facts": sum(len(r["changed"]) for r in R),
                        "evcheck_miss": sum(len(r["evcheck_miss"]) for r in R)})
        wcsv("e13_host.csv", out)
        q = sorted(v for r in rows for k, v in r["ms_global"].items() if k.startswith(("c.", "s.", "l.", "m.", "k.")))
        SUMMARY["e13_content_query_ms_med"] = st.median(q)
        f = sorted(v for r in rows for k, v in r["ms_global"].items() if k.startswith(("g.", "f.")))
        SUMMARY["e13_shell_cmd_ms_med"] = st.median(f)


def main():
    sys.stdout.reconfigure(newline="")  # LF output on Windows too
    for fn in (e1, e2, e3, e4, e6, e7, e8, e9, e10_12_13):
        try:
            fn()
        except Exception as e:
            SUMMARY["error_" + fn.__name__] = repr(e)
            import traceback
            traceback.print_exc()
    aw = os.path.join(DER, "aw_census_summary.json")
    if os.path.exists(aw):
        SUMMARY["aw"] = json.load(open(aw))
    SUMMARY["note"] = ("Real Android emulator runs (API 33: P06Avd/P06Avd2; API 35: P06Avd35), deterministic scripted driver; "
                       "E8 uses a local LLM (Ollama qwen2.5:7b). AndroidWorld census is code inspection.")
    with open(os.path.join(DER, "summary.json"), "w", newline="") as f:
        json.dump(SUMMARY, f, indent=1, sort_keys=True, default=str)
    print(json.dumps({k: v for k, v in SUMMARY.items() if not isinstance(v, dict)}, indent=0, default=str)[:2500])


if __name__ == "__main__":
    main()
