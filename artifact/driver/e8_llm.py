#!/usr/bin/env python3
"""E8 (round 2): agent memory of LLM-derived facts. Re-deriving a fact costs an LLM call; validating its supports
costs provider queries. Real emulator + real local LLM (Ollama, qwen2.5:7b, temperature 0, fixed seed).

Per trial: the client OBSERVEs its base facts; the host derives D derived facts from them with the LLM (each
derived fact records the base facts it depends on). A gap is injected (kill: epoch break; or none), sources change
with probability P, and the client DECIDEs (+14 s). Each policy re-derives a derived fact when it would refresh any
of its supports: global refresh and restart-aware event-only re-derive everything after an epoch break; LeaseMem
re-derives only facts whose supports are CHANGED or UNKNOWN. To time every policy on the same decision, the host
re-derives every derived fact from the current base values and records each call's wall-clock time; a policy's
cost is its validation time plus the times of the facts it re-derives. A policy that reuses a derived fact whose
supports changed made a stale decision.
Usage: e8_llm.py SERIAL GAP N P_CHANGE SEED OUT.jsonl
"""
import json, os, random, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lmdrv

MODEL = "qwen2.5:7b"
DERIVED = [  # name, supports, prompt template (base fact values substituted)
    ("photo_caption", ["m.latest"], "Write a one-line caption for a photo file named '{m.latest}'."),
    ("contacts_summary", ["c.set"], "Summarize this contact list in one short sentence: {c.set}."),
    ("callback_note", ["l.latest", "l.missed"], "Newest caller: {l.latest}. Missed calls: {l.missed}. In one sentence, who should I call back and why?"),
    ("share_msg", ["m.latest", "c.dana"], "Draft a one-line text to {c.dana} sharing the photo '{m.latest}'."),
    ("notes_summary", ["f.list"], "These note files exist: {f.list}. Summarize them in one sentence."),
    ("dana_card", ["c.dana"], "Write a one-line contact card for Dana whose number is {c.dana}."),
    ("omar_card", ["c.omar"], "Write a one-line contact card for Omar whose number is {c.omar}."),
    ("sms_reply", ["s.latest"], "Draft a one-line reply to this message: '{s.latest}'."),
    ("standup_reminder", ["k.standup", "c.dana"], "Write a one-line SMS to {c.dana} reminding them about '{k.standup}'."),
    ("mode_note", ["g.mode"], "In one sentence, explain to the user that the assistant mode is now '{g.mode}'."),
]


def llm(prompt):
    body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0, "seed": 7, "num_predict": 48}}).encode()
    t0 = time.time()
    req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        out = json.loads(r.read())
    return out["response"].strip(), time.time() - t0, out.get("eval_count")


def fill(tpl, vals):
    for k, v in vals.items():
        tpl = tpl.replace("{" + k + "}", str(v))
    return tpl


def derive(vals):
    res = {}
    for name, sup, tpl in DERIVED:
        text, secs, toks = llm(fill(tpl, vals))
        res[name] = {"text": text, "secs": round(secs, 3), "tokens": toks, "inputs": {s: vals[s] for s in sup}}
    return res


def main():
    serial, gap, n, p, seed, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5]), sys.argv[6]
    d = lmdrv.Dev(serial); rng = random.Random(seed); w = lmdrv.World(d, rng)
    d.launch()
    llm("Say OK.")                                        # warm the model
    with open(out, "a") as fo:
        for t in range(n):
            rec = {"trial": t, "gap": gap, "p_change": p, "seed": seed, "model": MODEL}
            try:
                if not d.pid():
                    d.launch()
                d.home()
                made = w.ensure_base().get("made", 1)
                time.sleep(12.0 if made else 2.0)
                ob = d.cmd("OBSERVE")
                vals0 = {k: v["val"] for k, v in ob["facts"].items()}
                rec["derived_obs"] = derive(vals0)
                rec["t_gap_start"] = d.now_ms()
                if gap == "kill":
                    d.home(); time.sleep(0.5); d.sh("am kill %s" % lmdrv.CPKG); time.sleep(0.5)
                    if d.pid():
                        d.sh("kill -9 %s" % d.pid())
                plan = [(s, rng.choice(lmdrv.World.KINDS[s])) for s in lmdrv.World.KINDS if rng.random() < p]
                rec["muts"] = [w.mutate(s, k) for s, k in plan]
                time.sleep(rng.uniform(12, 30))
                if gap == "kill":
                    d.launch()
                time.sleep(14.0)
                dec = d.cmd("DECIDE")
                F = dec["facts"]
                vals1 = {k: v["truth"] for k, v in F.items() if v["src"] != "derived"}
                rec["derived_dec"] = derive(vals1)          # re-derivation of every fact, timed per call
                rec["labels"] = {k: {pol: v[pol] for pol in ("ev", "evr", "lm", "lme", "lmts")} for k, v in F.items() if v["src"] != "derived"}
                rec["changed"] = {k: v["mem"] != v["truth"] for k, v in F.items() if v["src"] != "derived"}
                rec["lm_validate_ms"] = (sum(v["ns"] for k, v in dec["lm_cost"].items() if isinstance(v, dict)) +
                                         sum(v for k, v in dec["lm_cost"].items() if k.startswith("probe_"))) / 1e6
                rec["refresh_ms"] = {k: v["refresh_ns"] / 1e6 for k, v in F.items() if v["src"] != "derived"}
                rec["broken"] = dec.get("broken")
                fo.write(json.dumps(rec) + "\n"); fo.flush()
                print("trial", gap, p, t, len(plan), flush=True)
            except Exception as e:
                rec["error"] = repr(e); fo.write(json.dumps(rec) + "\n"); fo.flush()
                print("ERR", t, repr(e), flush=True); d.launch()


if __name__ == "__main__":
    main()
