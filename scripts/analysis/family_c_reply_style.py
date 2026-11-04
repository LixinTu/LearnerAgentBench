"""Does read_only leak more because it writes summaries instead of tutoring? Text-based, read-only."""
import json, pathlib, re, collections
from learneragentbench.verify import tutoring as T
from learneragentbench.env.world import World
from learneragentbench.schema import Trajectory
from learneragentbench.tasks import Dataset, resolve_variant
from learneragentbench.tasks.variants import effective_task
ds = Dataset()
class Ctx:
    def __init__(self, traj, world, task): self.trajectory, self.world, self.task = traj, world, task
    def event_step(self, eid):
        info = self.world.store.kv_get(f"event_applied:{eid}")
        return info.get("step") if info else None
SUMMARY = re.compile(r"^\s*(?:solved|calculated|corrected|recorded|created|verified|updated|clarified|confirmed|added|helped|guided|reviewed|provided|adjusted|completed|scheduled|set up|sent)\b", re.I)
WORKS = re.compile(r"(?:let'?s|we can|step[- ]by[- ]step|first,|1\.\s)", re.I)
ASKS = re.compile(r"\?\s*$")
tab = collections.defaultdict(collections.Counter)
for root in ["runs/family_c_v2_local","runs/family_c_c07_rule_at_a_line_local"]:
    for vp in sorted(pathlib.Path(root).glob("*/verdict.json")):
        d = vp.parent; v = json.loads(vp.read_text())
        if v["variant_id"]!="base" or (root.endswith("v2_local") and v["task_id"].startswith("C07")): continue
        c = json.loads((d/"config.json").read_text())["condition"]
        spec = ds.load_task(v["task_id"]); task = effective_task(spec, resolve_variant(spec,"base"))
        ck = next(k for k in task.checks if k.verifier=="tutoring.hint_policy" and k.params.get("script"))
        traj = Trajectory.model_validate_json((d/"trajectory.json").read_text()); w = World.from_snapshot(d/"world_final.db")
        ctx = Ctx(traj,w,task); turns = T.tutor_turns(ctx); r = T.replay(ctx, ck.params)
        for i,f in enumerate(r["findings"]):
            if f.get("missing") or f["kind"] not in ("attempt","idk") or f.get("answer_allowed"): continue
            t = tab[c]; t["turns"]+=1
            txt = turns[i]; leak = bool(f["leak"])
            style = "summary" if SUMMARY.search(txt) else ("question only" if ASKS.search(txt) and len(txt)<200 else ("works it out" if WORKS.search(txt) else "other"))
            t[style]+=1; t[style+"_leak"]+=leak; t["leak"]+=leak; t["len"]+=len(txt)
print("system".ljust(18),"turns leak".ljust(12),"summary".ljust(12),"question only".ljust(16),"works it out".ljust(16),"other".ljust(12),"mean chars")
for c in ["chatbot","memory_assistant","tool_agent","full_agent","read_only"]:
    t=tab[c]; print(c.ljust(18),f"{t['turns']} {t['leak']}".ljust(12),*[f"{t[s]} ({t[s+'_leak']} leak)".ljust(w) for s,w in (("summary",12),("question only",16),("works it out",16),("other",12))], t["len"]//max(t["turns"],1))
