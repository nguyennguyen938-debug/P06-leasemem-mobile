#!/usr/bin/env python3
"""L4 (F6 group L), lab mode only: resumed draft-writing tasks with local LLMs on the host GPU, effects on a lab phone.
Port of followup/agent_tasks.py (emulator Table agent-tasks) to the phone rules; the prompts, models, gaps and arms
are that file's own (imported, not copied). Changes: every user-scoped command through Dev.u(); the draft (the task's
effect) is written into the client's private files (files/lm-agent-drafts/result-<arm>.json, base64 through run-as)
instead of shared storage, then read back; records carry d.meta(); output goes to OUT (create-only).

The LLM server is Ollama on the host at http://127.0.0.1:11434 (agent_tasks.generate posts there); both models of
agent_tasks.MODELS must be pulled, else the script stops before touching the phone. P06_LLM_FAKE=1 (dry runs with the fake adb only)
replaces the model with a fixed valid action and skips the server check.
Usage: l4_agent.py SERIAL OUT.jsonl [N=24]
"""
import base64, hashlib, json, os, random, sys, time, urllib.request
from pathlib import Path
A = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(A / "followup")); sys.path.insert(0, str(A / "revision"))
import agent_tasks as at
from run import setup, lmdrv

serial, out = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 24
LLM = "http://127.0.0.1:11434"
FAKE = os.environ.get("P06_LLM_FAKE") == "1"
P = lmdrv.CPKG
DRAFTS = "files/lm-agent-drafts"

if FAKE:
    def generate(model, task, inputs):
        a = {"action": "save_draft", "task": task, "inputs": inputs, "text": "Draft for %s." % task}
        return {"request": {"model": model, "fake": True}, "response": {"response": json.dumps(a)}, "action": a, "wall_s": 0.0}
    inventory = {"fake": True}
else:
    try:
        inventory = json.load(urllib.request.urlopen(LLM + "/api/tags", timeout=30))
    except Exception as e:
        raise SystemExit("L4: no Ollama server at %s (%r); nothing was done on the phone" % (LLM, e))
    missing = [m for m in at.MODELS if m not in {x.get("name") for x in inventory.get("models", [])}]
    if missing:
        raise SystemExit("L4: the Ollama server lacks %s (`ollama pull <model>`); nothing was done on the phone" % missing)
    generate = at.generate

c, w = setup(serial, Path(out).parent); d = c.d
if not d.lab:
    raise SystemExit("L4 runs only in lab mode (P06_TARGET=lab, a wiped lab phone on USB)")


def save(arm, action):
    """The task's effect: the draft in the client's private files, written and read back through run-as."""
    payload = json.dumps(action, sort_keys=True)
    b = base64.b64encode(payload.encode()).decode()
    d.app_sh(P, "mkdir -p %s && echo %s | base64 -d > %s/result-%s.json" % (DRAFTS, b, DRAFTS, arm))
    return d.cat(P, "%s/result-%s.json" % (DRAFTS, arm))


rng = random.Random(20261116)
with lmdrv.open_new(out) as f:
    f.write(json.dumps({**d.meta(), "serial": serial, "exp": "l4_inventory", "llm": LLM, "inventory": inventory}) + "\n")
    for model in at.MODELS:
        generate(model, "warmup", {"value": "ready"})
        for gap, prob in [("force-stop", .1), ("force-stop", .3), ("none", .3)]:
            for i in range(n):
                task, keys = at.TASKS[i % len(at.TASKS)]
                r = {**d.meta(), "serial": serial, "exp": "l4_agent", "model": model, "gap": gap, "p_change": prob, "trial": i,
                     "task": task, "keys": keys, "seed": 20261116, "host_load": lmdrv.host_load()}
                try:
                    if not d.pid():
                        d.launch(); d.sh(d.u("am start-foreground-service -n %s/.FgService" % P))
                    w.ensure_base(); c.call("resetcache"); r["anchor"] = c.call("batch", mode="refresh")
                    old = at.inputs(r["anchor"]["values"], keys); r["cached"] = generate(model, task, old)
                    d.home(); r["pid_before"] = d.pid()
                    if gap == "force-stop":
                        d.sh(d.u("am force-stop " + P)); assert not d.pid()
                    r["mutations"] = [w.mutate(src, "update") for src in ["contacts", "media", "calendar"] if rng.random() < prob]
                    time.sleep(.2)
                    if gap == "force-stop":
                        d.launch(); d.sh(d.u("am start-foreground-service -n %s/.FgService" % P))
                    r["pid_after"] = d.pid(); order = ["refresh", "memo", "evidence"]; rng.shuffle(order); r["order"] = order; r["arms"] = {}
                    for arm in order:
                        t = time.perf_counter(); x = {}; r["arms"][arm] = x
                        x["read"] = c.call("batch", mode="validate" if arm == "evidence" else "refresh"); current = at.inputs(x["read"]["values"], keys)
                        reuse = arm == "memo" and old == current and r["cached"]["action"] is not None
                        x["reused"] = reuse
                        x["generation"] = r["cached"] if reuse else generate(model, task, current)
                        action = x["generation"]["action"]
                        x["dispatchable"] = isinstance(action, dict) and action.get("action") == "save_draft"
                        x["submitted_inputs"] = action.get("inputs") if isinstance(action, dict) else None
                        if x["dispatchable"]:
                            actual = save(arm, action); x["saved"] = json.loads(actual)
                            x["effect_sha256"] = hashlib.sha256(actual.strip().encode()).hexdigest()
                        x["suffix_wall_s"] = time.perf_counter() - t
                        truth = at.inputs(c.call("batch", mode="refresh")["values"], keys); x["truth_after"] = truth
                        x["stale_action"] = x["dispatchable"] and old != truth and x["submitted_inputs"] == old
                        x["wrong_inputs"] = x["dispatchable"] and x["submitted_inputs"] != truth
                        sv = x.get("saved", {})
                        x["task_success"] = bool(x["dispatchable"] and sv.get("inputs") == truth and sv.get("task") == task
                                                 and isinstance(sv.get("text"), str) and sv["text"].strip())
                        x["certified_reuses"] = 0
                    r["changed_inputs"] = old != r["arms"]["refresh"]["truth_after"]
                except Exception as e:
                    r["error"] = repr(e)
                f.write(json.dumps(r) + "\n"); f.flush(); print(model, gap, prob, i, r.get("error", "ok")[:100], flush=True)
