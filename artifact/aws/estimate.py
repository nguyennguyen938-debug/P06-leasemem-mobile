#!/usr/bin/env python3
"""Device-minute estimate for every physical task on AWS Device Farm, from the emulator data (no AWS call).

How: for each emulator raw file, the seconds per trial are the median gap between the start stamps of consecutive
trials (device or host clock, whichever the driver recorded), which includes every wait and setup step of a trial;
gaps above 10 times the median (host sleep, restarts) are dropped. Phone trials may be faster or slower: B0 measures
the real seconds per trial and this table is recomputed. Each Device Farm run also costs a fixed preparation time
(the device is wiped, the APKs are installed, fixtures are written); RUN_OVERHEAD_MIN is an assumption until B0
measures it. A task is split into runs of at most RUN_BUDGET_MIN of trial time so a run stays under the 150-minute
Device Farm timeout. Price: 0.17 USD per device minute (CLAUDE.md of the project).
Usage: python aws/estimate.py [--json]
"""
import json, math, statistics as st, sys
from pathlib import Path

A = Path(__file__).resolve().parents[1]
R = A / "results"
USD_PER_MIN = 0.17
RUN_OVERHEAD_MIN = 6.0     # assumption: wipe, install 4 APKs, grants, fixtures (B0 measures it)
RUN_TIMEOUT_MIN = 150      # Device Farm execution timeout per run
RUN_BUDGET_MIN = 110       # trial time per run: 150 min minus overhead minus a margin for slower phone trials


def rows(rel):
    p = R / rel
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def per_trial_s(stamps, unit_s):
    """Median gap between consecutive start stamps, in seconds; gaps over 10x the median are dropped."""
    d = [(b - a) * unit_s for a, b in zip(stamps, stamps[1:]) if b > a]
    if not d:
        return None
    m = st.median(d)
    d = [x for x in d if x <= 10 * m]
    return st.median(d)


def field(rs, f):
    return [x for x in (f(r) for r in rs if "error" not in r) if isinstance(x, (int, float))]


def timings():
    """task step -> (seconds per trial, source file, how measured)."""
    T = {}
    for g in ["none", "freeze", "dozeidle", "bucket", "unregister", "kill", "forcestop", "perm", "reboot"]:
        f = "raw/e2v3_bg_%s.jsonl" % g
        T["B2/" + g] = (per_trial_s(field(rows(f), lambda r: r.get("t_obs")), 1e-3), f, "t_obs, device ms")
    deploy = rows("followup-20261116/deploy-emulator-5620.jsonl") + rows("followup-20261116/deploy-emulator-5622.jsonl")
    for m in ["bg_unfrozen", "bg_freezer", "fg", "assistant"]:
        sub = [r for r in deploy if r.get("mode") == m]
        T["B1/" + m] = (per_trial_s(field(sub, lambda r: (r.get("mutation") or {}).get("t_pre")), 1e-3),
                        "followup-20261116/deploy-emulator-562*.jsonl", "mutation.t_pre, device ms")
    first_mut = lambda r: min([m["t_pre"] for m in r.get("muts", []) if "t_pre" in m] or [None], key=lambda x: x or 0) or None
    T["B3"] = (per_trial_s(field(rows("raw/e1_coverage_bg.jsonl"), first_mut), 1e-3),
               "raw/e1_coverage_bg.jsonl", "earliest muts.t_pre, device ms")
    for k, f in [("B4", "revision-20261115/stock-emulator-5620.jsonl"), ("B6", "revision-20261115/host-emulator-5620.jsonl")]:
        rs = rows(f); trials = {}
        for r in rs:
            trials.setdefault(r["trial"], []).append(r)
        s = [sum(x["end"] - x["start"] for x in v) for v in trials.values() if all("start" in x and "end" in x for x in v)]
        T[k] = (st.median(s) if s else None, f, "sum of end - start over the cases of a trial, host s")
    T["B5"] = (per_trial_s(field(rows("raw/e9_frozen_33.jsonl"), lambda r: r.get("t_obs")), 1e-3), "raw/e9_frozen_33.jsonl", "t_obs, device ms")
    T["B9"] = (per_trial_s(field(rows("raw/e3v2_boundary.jsonl"), lambda r: r.get("at")), 1e-3), "raw/e3v2_boundary.jsonl", "at, device ms")
    p6 = rows("raw/e6_pitfalls.jsonl")
    T["B10/sms_reuse"] = (per_trial_s(field([r for r in p6 if r.get("exp") == "sms_reuse"], lambda r: (r.get("res") or {}).get("t_pre")), 1e-3),
                          "raw/e6_pitfalls.jsonl", "res.t_pre, device ms")
    T["B10/mtime"] = (per_trial_s(field([r for r in p6 if r.get("exp") == "mtime"], lambda r: ((r.get("res") or [{}])[0] or {}).get("t_pre")), 1e-3),
                      "raw/e6_pitfalls.jsonl", "res[0].t_pre, device ms")
    return T


# planned trials per step (PLAN-dien-thoai-that.md section 5); B9: 100 changes + 25 + 20 + 20 controls, then 100 in band
PLAN = {"B1": {"B1/bg_unfrozen": 20 + 20 + 20, "B1/bg_freezer": 20, "B1/fg": 20 + 20 + 20, "B1/assistant": 20},   # Contacts + MediaStore + call log
        "B3": {"B3": 30},
        "B2": {"B2/" + g: 25 for g in ["none", "freeze", "dozeidle", "bucket", "unregister", "kill", "forcestop", "perm", "reboot"]},
        "B4": {"B4": 20}, "B9": {"B9": 165 + 100}, "B10": {"B10/sms_reuse": 50, "B10/mtime": 50}, "B5": {"B5": 10},
        "B13": {"B1/bg_unfrozen": 10, "B1/bg_freezer": 10, "B1/fg": 10, "B1/assistant": 10,
                **{"B2/" + g: 10 for g in ["none", "freeze", "dozeidle", "kill", "forcestop"]}},
        "B6": {"B6": 30}, "B7": {"B6": 30}}     # B7 has no emulator run; its trials resemble B6's continuous case
B0_MIN = 20.0              # assumption: one probe run (setup, 27 probes, one reboot, one full trial)


def estimate():
    T = timings(); out = {}
    for task, steps in PLAN.items():
        trial_min = sum(n * (T[s][0] or 0) for s, n in steps.items()) / 60
        runs = max(1, math.ceil(trial_min / RUN_BUDGET_MIN))
        total = trial_min + runs * RUN_OVERHEAD_MIN
        out[task] = {"trial_min": round(trial_min, 1), "runs": runs, "device_min": round(total, 1),
                     "usd": round(total * USD_PER_MIN, 2), "steps": {s: [n, T[s][0] and round(T[s][0], 1)] for s, n in steps.items()}}
    out["B0"] = {"trial_min": B0_MIN, "runs": 1, "device_min": B0_MIN, "usd": round(B0_MIN * USD_PER_MIN, 2), "steps": {}}
    return T, out


def selftest():
    assert per_trial_s([0, 10, 20, 30, 1000], 1) == 10        # the 970 s host-sleep gap is dropped
    assert per_trial_s([5], 1) is None
    print("estimate selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest(); sys.exit(0)
    T, E = estimate()
    if "--json" in sys.argv:
        print(json.dumps({"timings": {k: [v[0], v[1], v[2]] for k, v in T.items()}, "estimate": E}, indent=1)); sys.exit(0)
    print("| Task | Trial time, min | Runs (<= %d min) | Device min incl. %.0f min/run | USD at %.2f/min |" % (RUN_TIMEOUT_MIN, RUN_OVERHEAD_MIN, USD_PER_MIN))
    print("|---|---|---|---|---|")
    order = ["B0", "B1", "B3", "B2", "B4", "B9", "B10", "B5", "B13", "B6", "B7"]
    for k in order:
        e = E[k]; print("| %s | %.1f | %d | %.1f | %.2f |" % (k, e["trial_min"], e["runs"], e["device_min"], e["usd"]))
    core = sum(E[k]["device_min"] for k in ["B0", "B1", "B3", "B2", "B4"]); allm = sum(E[k]["device_min"] for k in order)
    print("| core B0 to B4 | | | %.1f | %.2f |" % (core, core * USD_PER_MIN))
    print("| all tasks | | | %.1f | %.2f |" % (allm, allm * USD_PER_MIN))
    print()
    print("| Step | s per trial | Emulator file | Stamp |")
    print("|---|---|---|---|")
    for k, (s, f, how) in T.items():
        print("| %s | %s | `%s` | %s |" % (k, "%.1f" % s if s else "no data", f, how))
