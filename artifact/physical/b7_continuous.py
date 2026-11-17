#!/usr/bin/env python3
"""B7: continuous mutation with a timestamp oracle. Separates "stale when certified" from "fresh when certified but
stale when acted on".

Per trial: fixtures, cache anchors for every arm, one refresh as the initial truth; then a writer thread updates LM
Dana's number back to back (org.leasemem.mut; each update logs its device commit window [t_pre, t_dev] in
System.currentTimeMillis and sets c.dana to "+1555"+tag). While it writes, every arm in random order runs one batch
(the certification) and immediately one `effect` op that durably uses the batch's c.dana value (the action). The
client reports each batch's end and per-fact read intervals in elapsedRealtimeNanos plus the wall-minus-elapsed
offset, so both instants map onto the writer's clock. classify() below is the oracle; the raw record keeps every
input it needs. Usage: b7_continuous.py SERIAL OUT.jsonl [--n 30] [--arms refresh,stamp,relay]
                b7_continuous.py --selftest
"""
import argparse, json, random, sys, threading, time, traceback
from pathlib import Path
A = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(A / "driver")); sys.path.insert(0, str(A / "revision"))
FACT = "c.dana"


def truth_at(t, v0, muts):
    """c.dana at device wall time t (ms). None if t lies inside a commit window (the oracle cannot tell)."""
    v = v0
    for m in sorted(muts, key=lambda m: m["t_dev"]):
        if m["t_pre"] <= t <= m["t_dev"]:
            return None
        if m["t_dev"] < t:
            v = "+1555" + m["tag"]
    return v


def classify(rec):
    """arm -> {"class": fresh | stale_at_certification | stale_at_action_only | ambiguous, "t_cert", "t_act", "read_ok"}.
    Certification instant = batch end; action instant = effect start. read_ok: a re-read value equals the truth at the
    start or end of its read interval (None when the batch served c.dana from cache or the interval is ambiguous)."""
    v0 = rec["truth0"]["values"][FACT]; muts = rec["mutations"]; res = {}
    for arm, x in rec["arms"].items():
        b, e = x["batch"], x["effect"]; used = b["values"][FACT]
        t_cert = b["wall_offset_ms"] + b["end_ns"] / 1e6; t_act = e["wall_ms"]
        tc, ta = truth_at(t_cert, v0, muts), truth_at(t_act, v0, muts)
        cls = ("ambiguous" if tc is None or ta is None else "stale_at_certification" if used != tc
               else "stale_at_action_only" if used != ta else "fresh")
        read_ok = None
        if FACT in b.get("reads", {}):
            s, f = (b["wall_offset_ms"] + ns / 1e6 for ns in b["reads"][FACT])
            ends = [truth_at(s, v0, muts), truth_at(f, v0, muts)]
            read_ok = None if None in ends else used in ends
        res[arm] = {"class": cls, "t_cert": round(t_cert, 1), "t_act": t_act, "used": used, "truth_cert": tc,
                    "truth_act": ta, "read_ok": read_ok, "refreshed": FACT in b.get("reads", {})}
    return res


def selftest():
    m = lambda tag, a, b: {"tag": tag, "t_pre": a, "t_dev": b}
    muts = [m("1", 1000, 1010), m("2", 2000, 2010)]
    assert truth_at(500, "x", muts) == "x" and truth_at(1005, "x", muts) is None and truth_at(1500, "x", muts) == "+15551"
    batch = lambda used, end_ms, reads=None: {"values": {FACT: used}, "wall_offset_ms": 0, "end_ns": end_ms * 1e6,
                                              "reads": {FACT: [r * 1e6 for r in reads]} if reads else {}}
    rec = {"truth0": {"values": {FACT: "x"}}, "mutations": muts, "arms": {
        "fresh": {"batch": batch("+15551", 1500, [1400, 1450]), "effect": {"wall_ms": 1600}},
        "late": {"batch": batch("+15551", 1900), "effect": {"wall_ms": 2500}},
        "stale": {"batch": batch("x", 1500), "effect": {"wall_ms": 1600}},
        "amb": {"batch": batch("x", 1005), "effect": {"wall_ms": 1600}}}}
    c = classify(rec)
    assert [c[k]["class"] for k in ("fresh", "late", "stale", "amb")] == \
        ["fresh", "stale_at_action_only", "stale_at_certification", "ambiguous"], c
    assert c["fresh"]["read_ok"] is True and c["stale"]["read_ok"] is None
    print("b7 selftest ok")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("serial"); ap.add_argument("out")
    ap.add_argument("--n", type=int, default=30); ap.add_argument("--arms", default="refresh,stamp,relay")
    a = ap.parse_args(); arms = a.arms.split(",")
    import lmdrv
    from run import setup
    c, w = setup(a.serial, Path(a.out).parent); rng = random.Random(2611701)
    with lmdrv.open_new(a.out) as f:
        for i in range(a.n):
            r = {**c.d.meta(), "trial": i, "seed": 2611701, "arms_order": None, "start": time.time()}
            try:
                w.ensure_base(); c.call("resetcache")
                r["anchor"] = {arm: c.call("batch", mode=arm) for arm in arms}
                r["truth0"] = c.call("batch", mode="refresh"); r["mutations"] = []
                stop = threading.Event(); errors = []

                def writer():
                    try:
                        while not stop.is_set():
                            r["mutations"].append(w.mutate("contacts", "update"))
                    except Exception as e:
                        errors.append(repr(e))
                th = threading.Thread(target=writer); th.start(); time.sleep(0.3)
                order = list(arms); rng.shuffle(order); r["arms_order"] = order; r["arms"] = {}
                try:
                    for arm in order:
                        b = c.call("batch", mode=arm)
                        r["arms"][arm] = {"batch": b, "effect": c.call("effect", value=b["values"][FACT])}
                        time.sleep(rng.uniform(0, 0.5))
                finally:
                    stop.set(); th.join(60)
                r["writer_errors"] = errors; r["truth_after"] = c.call("batch", mode="refresh")
                summary = {k: v["class"] for k, v in classify(r).items()}
            except Exception as e:
                r["error"] = repr(e); r["trace"] = traceback.format_exc(); summary = None
            r["end"] = time.time(); f.write(json.dumps(r) + "\n"); f.flush()
            print(i, len(r.get("mutations", [])), "mutations", summary or r.get("error"), flush=True)


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
