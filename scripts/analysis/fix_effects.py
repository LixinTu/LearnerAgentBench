"""What each fix changed. Read-only."""
import json, pathlib, collections
frac = lambda v: v["score"]/v["max_score"] if v["max_score"] else 0
print("== contact fix: original run vs its re-run, judged by the same current checks where possible")
from learneragentbench.harness.runner import verify_run
from learneragentbench.env.world import World
from learneragentbench.schema import Trajectory, TaskSpec
from learneragentbench.tasks import Dataset, resolve_variant
from learneragentbench.tasks.variants import effective_task
ds = Dataset()
per = collections.defaultdict(lambda: [0,0.0,0.0,0,0,0,0,0,0,0])
first_same = 0; total = 0; rows = []
for old in sorted(pathlib.Path("runs/_superseded").glob("*/*")):
    if not (old/"verdict.json").exists(): continue
    new = pathlib.Path("runs")/old.parent.name/old.name
    cfg = json.loads((old/"config.json").read_text())
    base = ds.load_task(cfg["task_id"]); var = resolve_variant(base, cfg["variant_id"]); cur = effective_task(base, var)
    stored = TaskSpec.model_validate_json((old/"task_effective.json").read_text())
    spec = stored.model_copy(update={"checks": cur.checks})
    t_old = Trajectory.model_validate_json((old/"trajectory.json").read_text())
    w = World.from_snapshot(old/"world_final.db"); i = World.from_snapshot(old/"world_init.db")
    vo = verify_run(w, i, t_old, spec, var).model_dump(mode="json")
    vn = json.loads((new/"verdict.json").read_text())
    t_new = Trajectory.model_validate_json((new/"trajectory.json").read_text())
    def calls(t): return [(s.action.tool_call.tool, json.dumps(s.action.tool_call.args, sort_keys=True)) for s in t.steps if s.action.type=="tool_call" and s.action.tool_call]
    co, cn = calls(t_old), calls(t_new); total += 1
    # how far do the two runs agree before the first different action
    n = 0
    for a,b in zip(co,cn):
        if a!=b: break
        n+=1
    first_same += bool(co and cn and co[0]==cn[0])
    d = frac(vn)-frac(vo)
    p = per[cfg["condition"]]; p[0]+=1; p[1]+=frac(vo); p[2]+=frac(vn); p[3]+=d>1e-9; p[4]+=d<-1e-9; p[5]+=abs(d)<=1e-9; p[6]+=bool(vo["hard_failures"]); p[7]+=bool(vn["hard_failures"]); p[8]+=vo["task_success"]; p[9]+=vn["task_success"]
    rows.append((cfg["task_id"][:3], cfg["condition"][:4], cfg["variant_id"][:14], cfg["seed"], round(frac(vo),2), round(frac(vn),2), t_old.status[:3], t_new.status[:3], n, len(co), len(cn)))
print("condition n old new better worse same hardfail-old hardfail-new succ-old succ-new")
for k,p in per.items(): print(k.ljust(18), p[0], f"{p[1]/p[0]:.3f} {p[2]/p[0]:.3f}", p[3], p[4], p[5], p[6], p[7], p[8], p[9])
print("first call identical", first_same, "of", total)
by = collections.defaultdict(list)
for r in rows: by[r[0]].append(r[5]-r[4])
print({k:(len(v), round(sum(v)/len(v),2)) for k,v in sorted(by.items())})
print("runs that hit max_steps old/new", sum(r[6]=="max" for r in rows), sum(r[7]=="max" for r in rows))
print()
print("== judging audit: score at run vs now, runs NOT re-run, per sweep")
for s in ["baselines_local_v2","baselines_local_v3_new_tasks","paired_variants_new_tasks_local","tool_ablation_local","memory_ablation_local","persona_swap_local","family_c_v2_local"]:
    rows2 = collections.defaultdict(lambda:[0,0.0,0.0,0])
    for vp in pathlib.Path("runs",s).glob("*/verdict.json"):
        d = vp.parent
        if s=="baselines_local_v2" and "__C0" in d.name: continue
        if s=="family_c_v2_local" and "C07" in d.name: continue
        c = json.loads((d/"config.json").read_text())["condition"]
        v = json.loads(vp.read_text()); o = json.loads((d/"verdict_at_run.json").read_text()) if (d/"verdict_at_run.json").exists() else v
        r = rows2[c]; r[0]+=1; r[1]+=frac(o); r[2]+=frac(v); r[3]+= (o["score"],o["max_score"],o["task_success"])!=(v["score"],v["max_score"],v["task_success"])
    print(s, {k:(r[0], round(r[1]/r[0],3), round(r[2]/r[0],3), r[3]) for k,r in sorted(rows2.items())})
