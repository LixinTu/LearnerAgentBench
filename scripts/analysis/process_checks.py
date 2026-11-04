"""How much do 'memory was read' process checks move the comparison of memory-in-prompt against memory-through-tools? Read-only."""
import json, pathlib, collections, random
MEM = {"search_memory","get_preferences","get_memory","search_conversations"}
rows = collections.defaultdict(dict)
stat = collections.defaultdict(lambda:[0,0])
for root in ["runs/_analysis/record"]:
    for vp in sorted(pathlib.Path(root).glob("*/verdict.json")):
        d = vp.parent; v = json.loads(vp.read_text()); c = json.loads((d/"config.json").read_text())["condition"]
        task = json.loads((d/"task_effective.json").read_text()); spec = {k["id"]:k for k in task["checks"]}
        keep = [k for k in v["checks"] if not (
            (spec[k["check_id"]]["verifier"]=="audit.tool_called" and (set([spec[k["check_id"]]["params"].get("tool")]+spec[k["check_id"]]["params"].get("tools",[])) - {None}) <= MEM)
            or (spec[k["check_id"]]["verifier"]=="audit.read_before_write" and set(spec[k["check_id"]]["params"].get("read_tools",[])) <= MEM))]
        drop = [k for k in v["checks"] if k not in keep]
        for k in drop:
            stat[c][1]+=1; stat[c][0]+=bool(k["passed"])
        full = sum(k["weight"] for k in v["checks"]); fs = sum(k["weight"] for k in v["checks"] if k["passed"])
        kw = sum(k["weight"] for k in keep); ks = sum(k["weight"] for k in keep if k["passed"])
        key = (v["task_id"], v["seed"])
        rows[c][key] = (fs/full, ks/kw if kw else 0, v["task_id"][0])
print("memory-read process checks: pass/total per system", {k:tuple(x) for k,x in stat.items()})
def paired(a, b, idx, fam=None):
    tasks = collections.defaultdict(list)
    for key in rows[a]:
        if key in rows[b] and (fam is None or rows[a][key][2]==fam):
            tasks[key[0]].append(rows[b][key][idx]-rows[a][key][idx])
    ds = [sum(x)/len(x) for x in tasks.values()]
    random.seed(0); bs=[]
    for _ in range(5000):
        s=[random.choice(ds) for _ in ds]; bs.append(sum(s)/len(s))
    bs.sort(); return f"{sum(ds)/len(ds):+.3f} [{bs[125]:+.3f}, {bs[4875]:+.3f}] over {len(ds)} tasks"
for a,b in (("full_agent","tool_agent"),("chatbot","tool_agent"),("memory_assistant","full_agent"),("chatbot","memory_assistant")):
    print(b,"-",a,"as scored:",paired(a,b,0),"| without those checks:",paired(a,b,1))
    print("   family C as scored:",paired(a,b,0,"C"),"| without:",paired(a,b,1,"C"))
for c in rows: 
    v=list(rows[c].values()); print(c, "mean as scored", round(sum(x[0] for x in v)/len(v),3), "without", round(sum(x[1] for x in v)/len(v),3))
