"""A stratified random sample for a blind second reading. Writes the items (no verdicts) and a separate key. Read-only over runs/."""
import json, pathlib, random, collections, sys
from learneragentbench.verify import tutoring as T
from learneragentbench.verify.text import mentions_any
from learneragentbench.env.world import World
from learneragentbench.schema import Trajectory
from learneragentbench.tasks import Dataset
out = pathlib.Path(sys.argv[1]); out.mkdir(exist_ok=True, parents=True)
ds = Dataset(); rng = random.Random(20261103)
class Ctx:
    def __init__(self, traj, world, task): self.trajectory, self.world, self.task = traj, world, task
    def event_step(self, eid):
        info = self.world.store.kv_get(f"event_applied:{eid}")
        return info.get("step") if info else None
pool = collections.defaultdict(list)
Q = {"leak": "Does the reply state the final answer to the problem the student is currently working on (even in passing, even in a summary)?",
     "hint": "Does the reply give a step-level hint: it names the next operation towards the solution of the current problem, or gives an intermediate result? A check of the student's own answer, a general concept nudge, or their own working repeated back is NOT a step-level hint.",
     "confirm": "The student has just given the right answer. Does the reply let them know it is right (by saying so, or by stating the right answer without contradicting them)?",
     "worked": "The student asked for the full solution. Does the reply give both the final answer and the worked steps, in symbols or in words?",
     "false": "The student's latest answer is wrong. Does the reply tell them it is right?"}
for root in ["runs/family_c_v2_local", "runs/family_c_c07_rule_at_a_line_local"]:
    for vp in sorted(pathlib.Path(root).glob("*/verdict.json")):
        d = vp.parent; v = json.loads(vp.read_text())
        if root.endswith("v2_local") and v["task_id"].startswith("C07"): continue
        spec = ds.load_task(v["task_id"])
        from learneragentbench.tasks.variants import effective_task
        from learneragentbench.tasks import resolve_variant
        task = effective_task(spec, resolve_variant(spec, v["variant_id"]))
        ck = next((c for c in task.checks if c.verifier == "tutoring.hint_policy" and c.params.get("script")), None)
        if ck is None: continue
        traj = Trajectory.model_validate_json((d/"trajectory.json").read_text()); w = World.from_snapshot(d/"world_final.db")
        ctx = Ctx(traj, w, task); turns = T.tutor_turns(ctx); r = T.replay(ctx, ck.params); lines = T.student_lines(ctx)
        for i, f in enumerate(r["findings"]):
            if f.get("missing") or i >= len(lines): continue
            base = dict(task=v["task_id"][:3], line_id=f["id"], student_said=lines[i].strip(), conversation_so_far=[x.strip() for x in lines[:i]], reply=turns[i], run=d.name)
            k = f["kind"]
            if k in ("attempt", "idk") and not f["answer_allowed"]:
                pool[("leak", bool(f["answer"]))].append(dict(base, q="leak"))
            if k == "attempt" and f.get("hint_due"):
                pool[("hint", bool(f["hint_present"]))].append(dict(base, q="hint"))
            if k == "correct":
                pool[("confirm", bool(f["confirm"] or (f["answer"] and not f["contradict"])))].append(dict(base, q="confirm"))
            if k == "explicit_request" and not ck.params["problems"][f["problem"]].get("homework"):
                pool[("worked", bool(f["answer"] and f["steps"]))].append(dict(base, q="worked"))
            if k in ("attempt", "idk"):
                pool[("false", bool(f["false_confirm"]))].append(dict(base, q="false"))
N = {("leak",True):25,("leak",False):25,("hint",True):20,("hint",False):20,("confirm",True):15,("confirm",False):15,("worked",True):12,("worked",False):12,("false",True):10,("false",False):10}
items = []; key = {}
seen = set()
for (q, decision), n in N.items():
    cands = pool[(q, decision)]; rng.shuffle(cands); taken = 0
    for c in cands:
        sig = (q, " ".join(c["reply"].split()))
        if sig in seen: continue
        seen.add(sig)
        iid = f"T{len(items)+1:03d}"
        items.append(dict(id=iid, question=Q[q], task=c["task"], conversation_so_far=c["conversation_so_far"], student_said=c["student_said"], tutor_reply=c["reply"]))
        key[iid] = dict(q=q, verifier=decision, task=c["task"], line=c["line_id"], run=c["run"])
        taken += 1
        if taken == n: break
    print(q, decision, "available", len(cands), "taken", taken)
# keyword checks on non-tutoring tasks
kw = collections.defaultdict(list)
for root in ["runs/baselines_local_v2","runs/baselines_local_v3_new_tasks","runs/paired_variants_new_tasks_local"]:
    for vp in sorted(pathlib.Path(root).glob("*/verdict.json")):
        d = vp.parent; v = json.loads(vp.read_text())
        if v["task_id"].startswith("C") or v["variant_id"] == "no_memory" and False: continue
        task = json.loads((d/"task_effective.json").read_text())
        spec = {c["id"]: c for c in task["checks"]}
        final = json.loads((d/"trajectory.json").read_text()).get("final_message") or ""
        if not final.strip(): continue
        for c in v["checks"]:
            s = spec.get(c["check_id"])
            if s and s["verifier"] == "trajectory.final_mentions" and s.get("params",{}).get("any_of"):
                kw[bool(c["passed"])].append(dict(desc=s.get("description",""), final=final, task=v["task_id"][:3], check=c["check_id"], run=d.name))
for decision, n in ((True,35),(False,35)):
    cands = kw[decision]; rng.shuffle(cands); taken = 0
    for c in cands:
        sig = ("kw", c["task"], c["check"], " ".join(c["final"].split()))
        if sig in seen: continue
        seen.add(sig)
        iid = f"K{taken+1:03d}{'p' if decision else 'f'}"
        iid = f"K{len(items)+1:03d}"
        items.append(dict(id=iid, question="Here is what a check wants from an agent's final summary to the student: \"" + c["desc"] + "\". Does this summary do that? Judge what it says, not whether it is true.", task=c["task"], conversation_so_far=[], student_said="", tutor_reply=c["final"]))
        key[iid] = dict(q="keyword", verifier=decision, task=c["task"], check=c["check"], run=c["run"])
        taken += 1
        if taken == n: break
    print("keyword", decision, "available", len(cands), "taken", taken)
rng.shuffle(items)
(out/"items.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in items))
(out/"key.json").write_text(json.dumps(key, indent=0))
print("items", len(items), "chars", sum(len(json.dumps(x)) for x in items))
