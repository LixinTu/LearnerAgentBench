"""All numbers of the final analysis. Read-only over runs/. Output goes to docs/logs as evidence."""
import collections, json, re, subprocess, sys, pathlib, random, statistics
from pathlib import Path
A = "runs/_analysis"
def lab(*args):
    r = subprocess.run([".venv/bin/python", "-m", "learneragentbench.harness.cli", *args], capture_output=True, text=True)
    if r.returncode: raise SystemExit(f"lab {args} exit {r.returncode}: {r.stderr[-400:]}")
    return r.stdout
def head(t): return t.split("\n\ncapability scores")[0]
def sec(t): print("\n" + "=" * 8, t, "=" * 8)
def compare_lines(a, b, fa, fb, la, lb, n=3):
    out = lab("compare", a, b, *(["--filter-a", fa] if fa else []), *(["--filter-b", fb] if fb else []), "--label-a", la, "--label-b", lb).splitlines()
    return "\n".join(l[:190] for l in out[1:n+1])

CONDS = ["chatbot", "memory_assistant", "tool_agent", "full_agent"]
sec("T1 baseline of record: 63 tasks, 4 systems, 3 seeds")
print(head(lab("summarize", f"{A}/record", "--group-by", "condition", "--floor")))
sec("T2 by family")
print(head(lab("summarize", f"{A}/record", "--group-by", "family,condition", "--floor")))
sec("T3 paired, all 63 tasks")
for a, b in (("chatbot","tool_agent"),("memory_assistant","full_agent"),("full_agent","tool_agent"),("chatbot","memory_assistant")):
    print(f"-- {b} - {a}"); print(compare_lines(f"{A}/record", f"{A}/record", f"condition={a}", f"condition={b}", a, b))
sec("T3b paired, the 25 old non-C tasks / 28 new non-C tasks / family C")
for name, root in (("old non-C", f"{A}/v2"), ("new non-C", f"{A}/new"), ("family C", f"{A}/c")):
    for a, b in (("chatbot","tool_agent"),("memory_assistant","full_agent"),("full_agent","tool_agent"),("chatbot","memory_assistant")):
        print(f"-- [{name}] {b} - {a}"); print(compare_lines(root, root, f"condition={a}", f"condition={b}", a, b, 1))
print("-- [family C] tool_agent - read_only"); print(compare_lines(f"{A}/c", f"{A}/c", "condition=read_only", "condition=tool_agent", "read_only", "tool_agent", 3))
print("-- [family C] chatbot - read_only"); print(compare_lines(f"{A}/c", f"{A}/c", "condition=read_only", "condition=chatbot", "read_only", "chatbot", 3))

# ------------------------------------------------------------- per-run facts
def verdicts(roots, flt=None):
    for r in roots:
        for vp in sorted(Path(r).glob("*/verdict.json")):
            d = vp.parent
            v = json.loads(vp.read_text()); c = json.loads((d/"config.json").read_text())
            if flt and not flt(v, c): continue
            yield d, v, c
BASE = ["runs/baselines_local_v2", "runs/baselines_local_v3_new_tasks", "runs/family_c_v2_local", "runs/family_c_c07_rule_at_a_line_local"]
def in_record(v, c):
    if v["variant_id"] != "base" or c["condition"] not in CONDS: return False
    return True
def record_rows():
    seen = set()
    for r in BASE:
        for d, v, c in verdicts([r], in_record):
            if r.endswith("family_c_v2_local") and v["task_id"].startswith("C07"): continue
            if r.endswith("baselines_local_v2") and v["task_id"].startswith("C"): continue
            yield d, v, c
rows = list(record_rows())
print("\nrecord runs", len(rows), "tasks", len({v['task_id'] for _,v,_ in rows}))
sec("T4 success and no-hard-failure")
for cond in CONDS:
    rs = [(d,v) for d,v,c in rows if c["condition"]==cond]
    print(cond, "n", len(rs), "success", sum(v["task_success"] for _,v in rs), "no hard failure", sum(not v["hard_failures"] for _,v in rs),
          "attribution", dict(collections.Counter(v["failure_attribution"] for _,v in rs)), "unverified checks", sum(1 for _,v in rs for k in v["checks"] if k["passed"] is None))
print("successes:", [ (v["task_id"][:3], c["condition"], v["seed"]) for _,v,c in rows if v["task_success"]])
print("no hard failure, tool_agent+full_agent, per task:", dict(collections.Counter(v["task_id"][:3] for _,v,c in rows if not v["hard_failures"] and c["condition"] in ("tool_agent","full_agent"))))
print("no hard failure, talk only, per task:", dict(collections.Counter(v["task_id"][:3] for _,v,c in rows if not v["hard_failures"] and c["condition"] in ("chatbot","memory_assistant"))))

sec("T5 which checks fail, acting systems, by verifier")
fails = collections.Counter(); tot = collections.Counter(); hardf = collections.Counter()
for _, v, c in rows:
    if c["condition"] not in ("tool_agent","full_agent"): continue
    for k in v["checks"]:
        tot[k["verifier"]] += 1
        if k["passed"] is False:
            fails[k["verifier"]] += 1
            if k["hard"]: hardf[k["verifier"]] += 1
print("verifier".ljust(34), "pass", "total", "rate", "hard fails")
for name, n in tot.most_common():
    print(name.ljust(34), str(n-fails[name]).rjust(4), str(n).rjust(5), f"{(n-fails[name])/n:.2f}", str(hardf[name]).rjust(5))

sec("T6 family C, aspects (pass/total, base variant, C07 re-run)")
asp = collections.defaultdict(lambda: collections.defaultdict(lambda: [0,0]))
cruns = []
for d, v, c in verdicts(["runs/family_c_v2_local","runs/family_c_c07_rule_at_a_line_local"], lambda v,c: v["variant_id"]=="base"):
    if d.parent.name=="family_c_v2_local" and v["task_id"].startswith("C07"): continue
    cruns.append((d,v,c))
    task = json.loads((d/"task_effective.json").read_text())
    m = {k["id"]: k["params"].get("aspect") for k in task["checks"] if k["verifier"]=="tutoring.hint_policy"}
    for k in v["checks"]:
        a = m.get(k["check_id"])
        if a and k["passed"] is not None:
            asp[a][c["condition"]][1]+=1; asp[a][c["condition"]][0]+= bool(k["passed"])
C5 = CONDS+["read_only"]
print("aspect".ljust(26), *[x[:12].ljust(13) for x in C5])
for a in sorted(asp): print(a.ljust(26), *[f"{asp[a][x][0]}/{asp[a][x][1]}".ljust(13) for x in C5])
print("runs", len(cruns), "attribution", collections.Counter(v["failure_attribution"] for _,v,_ in cruns))
# leak per task, per system
lk = collections.defaultdict(lambda: collections.defaultdict(lambda:[0,0]))
for d,v,c in cruns:
    task = json.loads((d/"task_effective.json").read_text())
    m = {k["id"]: k["params"].get("aspect") for k in task["checks"] if k["verifier"]=="tutoring.hint_policy"}
    for k in v["checks"]:
        if m.get(k["check_id"])=="answer_leak":
            lk[v["task_id"][:3]][c["condition"]][1]+=1; lk[v["task_id"][:3]][c["condition"]][0]+=bool(k["passed"])
print("no-leak pass per task"); print("task".ljust(6), *[x[:12].ljust(13) for x in C5])
for t in sorted(lk): print(t.ljust(6), *[f"{lk[t][x][0]}/{lk[t][x][1]}".ljust(13) for x in C5])
# paired bootstrap of leak pass rate over tasks
def boot(xs, n=5000):
    random.seed(0); m=[]; 
    for _ in range(n):
        s=[random.choice(xs) for _ in xs]; m.append(sum(s)/len(s))
    m.sort(); return m[int(.025*n)], m[int(.975*n)]
for a,b in (("read_only","chatbot"),("read_only","tool_agent"),("tool_agent","chatbot"),("memory_assistant","chatbot")):
    ds=[lk[t][b][0]/lk[t][b][1]-lk[t][a][0]/lk[t][a][1] for t in sorted(lk)]
    lo,hi=boot(ds); print(f"no-leak rate {b} - {a}: {sum(ds)/len(ds):+.3f} [{lo:+.3f}, {hi:+.3f}]  tasks better/worse/same {sum(x>0 for x in ds)}/{sum(x<0 for x in ds)}/{sum(x==0 for x in ds)}")

sec("T7 counterfactual variants (tool_agent, 3 seeds each)")
sys.path.insert(0, "src")
from learneragentbench.analysis import passive_floor
from learneragentbench.tasks import Dataset
ds = Dataset()
baseavg = collections.defaultdict(list)
for _, v, c in rows:
    if c["condition"]=="tool_agent": baseavg[v["task_id"]].append(v["score"]/v["max_score"])
vr = collections.defaultdict(list)
for d, v, c in verdicts(["runs/paired_variants_new_tasks_local","runs/family_c_v2_local","runs/family_c_c07_rule_at_a_line_local"], lambda v,c: c["condition"]=="tool_agent" and v["variant_id"]!="base"):
    if d.parent.name=="family_c_v2_local" and v["task_id"].startswith("C07"): continue
    vr[(v["task_id"], v["variant_id"])].append(v)
print("task variant cond".ljust(58), "base  var  floor  added-checks pass/total  hard-free  success")
sumc = collections.defaultdict(lambda: [0,0,0,0,0,0.0,0.0,0.0])
for (tid, var), vs in sorted(vr.items()):
    spec = ds.load_task(tid); vs_spec = next(x for x in spec.variants if x.id==var)
    added = {k.id for k in vs_spec.checks_add}
    ap = sum(1 for v in vs for k in v["checks"] if k["check_id"] in added and k["passed"]); at = sum(1 for v in vs for k in v["checks"] if k["check_id"] in added)
    fl = passive_floor(tid, var, None)
    fl = fl if isinstance(fl,(int,float)) else (fl[0]/fl[1] if fl else 0)
    sc = sum(v["score"]/v["max_score"] for v in vs)/len(vs); bs = sum(baseavg[tid])/len(baseavg[tid]) if baseavg[tid] else float("nan")
    print(f"{tid[:3]} {var} [{vs_spec.condition}]".ljust(58), f"{bs:.2f}  {sc:.2f}  {fl:.2f}  {ap}/{at}".ljust(28), sum(not v["hard_failures"] for v in vs), sum(v["task_success"] for v in vs))
    s = sumc[vs_spec.condition]; s[0]+=1; s[1]+=len(vs); s[2]+=ap; s[3]+=at; s[4]+=sum(not v["hard_failures"] for v in vs); s[5]+=sc; s[6]+=bs; s[7]+=fl
print("\nby counterfactual condition")
print("condition".ljust(26),"variants runs base variant floor added-pass hard-free")
for k,s in sorted(sumc.items()):
    print(k.ljust(26), str(s[0]).rjust(4), str(s[1]).rjust(5), f"{s[6]/s[0]:.2f} {s[5]/s[0]:.2f} {s[7]/s[0]:.2f}", f"{s[2]}/{s[3]}".rjust(9), str(s[4]).rjust(4))
tn=sum(s[0] for s in sumc.values()); print("total variants", tn, "runs", sum(s[1] for s in sumc.values()), "added checks", sum(s[2] for s in sumc.values()), "/", sum(s[3] for s in sumc.values()), "hard-free", sum(s[4] for s in sumc.values()), "above floor", sum(1 for (tid,var),vs in vr.items() if 0))

sec("T8 plan text without acting (record, per system, non-C and C separately)")
exec(open(sys.argv[1]).read().split('if __name__')[0])
def stats(sel):
    out = collections.defaultdict(lambda: collections.Counter())
    for d,v,c in sel:
        t = json.loads((d/"trajectory.json").read_text())
        calls = [s["action"]["tool_call"] for s in t["steps"] if s["action"]["type"]=="tool_call" and s["action"].get("tool_call")]
        ok_mut = sum(1 for s in t["steps"] if s["observation"]["type"]=="tool_result" and s["observation"]["content"].get("tool") in MUT)
        mut_try = sum(1 for x in calls if x["tool"] in MUT)
        final = t.get("final_message") or ""
        o = out[c["condition"]]; o["runs"]+=1
        if ok_mut==0:
            o["no_write"]+=1
            o["never_tried"]+= mut_try==0
            o["tried_all_rejected"]+= mut_try>0
            o["plan_text"]+= bool(PLANTEXT.search(final))
            o["announce"]+= bool(ANNOUNCE.search(final))
            o["claim"]+= bool(STRICT.search(final))
    return out
for name, sel in (("non-C", [x for x in rows if not x[1]["task_id"].startswith("C")]), ("all 63", rows)):
    print("--", name); o = stats(sel)
    print("system".ljust(18), "runs no_write never_tried rejected plan_text announce claim")
    for k in CONDS: x=o[k]; print(k.ljust(18), x["runs"], x["no_write"], x["never_tried"], x["tried_all_rejected"], x["plan_text"], x["announce"], x["claim"])
sec("T8b claims in the final message with no successful call behind them (lower bound, regular expressions)")
START = r"(?:^|[.!?\n:]\s*|-\s+|\bI(?:'ve| have)?\s+(?:also |now |just |already |successfully )?)"
CL = {"message": (rf"{START}(?:sent|emailed|messaged|notified|informed)\b|\b(?:has|have) been (?:sent|informed|notified)\b", {"send_message"}),
      "purchase": (rf"{START}(?:purchased|bought)\b|\bhas been purchased\b", {"purchase"}),
      "booking": (rf"{START}booked\b|\bhas been booked\b", {"book_slot"}),
      "plan or calendar": (rf"{START}(?:scheduled|created|updated|adjusted|added|set up)\b|\bhas been (?:created|updated|added|scheduled)\b", {"create_study_plan","update_study_plan","create_calendar_event","update_calendar_event","delete_calendar_event","create_task","update_task"}),
      "logged": (rf"{START}(?:logged|recorded)\b|\bhas been (?:logged|recorded)\b", {"record_learning_progress","record_memory"})}
from learneragentbench.env.world import World as _W
tab = collections.defaultdict(collections.Counter); ex2 = []
for d,v,c in rows:
    final = json.loads((d/"trajectory.json").read_text()).get("final_message") or ""
    w = _W.from_snapshot(d/"world_final.db")
    ok = {r.tool for r in w.tool_calls(v["run_id"]) if r.ok}
    any_un = False
    for cat,(rx,tools) in CL.items():
        if re.search(rx, final, re.I|re.M) and not (ok & tools):
            tab[c["condition"]][cat]+=1; any_un=True
            if c["condition"] in ("tool_agent","full_agent") and len(ex2)<14: ex2.append((v["task_id"][:3],c["condition"][:4],v["seed"],cat," ".join(final.split())[:170]))
    tab[c["condition"]]["runs with one"]+=any_un
    tab[c["condition"]]["runs"]+=1
    if any_un and v["task_success"]: print("SUCCESS WITH AN UNBACKED CLAIM:", v["task_id"], c["condition"], v["seed"])
cats = ["message","purchase","booking","plan or calendar","logged"]
print("system".ljust(18),"runs with one/runs".ljust(20),*[x.ljust(17) for x in cats])
for k in CONDS: print(k.ljust(18),f"{tab[k]['runs with one']}/{tab[k]['runs']}".ljust(20),*[str(tab[k][x]).ljust(17) for x in cats])
for e in ex2: print(e)
sec("T9 tool calls: rejected and why, acting systems, record")
from learneragentbench.env.world import World
et = collections.Counter(); per = collections.Counter(); tot=0; bad=0; by = collections.Counter(); samples = {}
for d,v,c in rows:
    if c["condition"] not in ("tool_agent","full_agent"): continue
    w = World.from_snapshot(d/"world_final.db")
    for rec in w.tool_calls(v["run_id"]):
        tot+=1
        if not rec.ok:
            bad+=1; et[rec.error_type]+=1; by[(rec.tool, rec.error_type)]+=1
            samples.setdefault((rec.tool, rec.error_type), (rec.error or "")[:110])
print("calls", tot, "rejected", bad, f"{bad/tot:.2f}", dict(et))
for k,n in by.most_common(16): print(n, k, samples[k])
sec("T10 ablations (paired against the same system)")
print("-- read_only vs tool_agent, 25 non-C tasks"); print(compare_lines(f"{A}/v2", f"{A}/tool", "condition=tool_agent", "condition=read_only", "full", "readonly", 3))
print(head(lab("summarize", f"{A}/tool", "--group-by", "condition,variant_id", "--floor")))
print("-- no memory, memory through tools"); print(compare_lines(f"{A}/v2", f"{A}/memory", "condition=tool_agent", "condition=memory_via_tools", "base", "no_mem", 3))
print("-- no memory, memory in prompt"); print(compare_lines(f"{A}/v2", f"{A}/memory", "condition=full_agent", "condition=memory_in_prompt", "base", "no_mem", 3))
print("-- persona swap"); print(lab("compare", f"{A}/v2", f"{A}/persona", "--filter-a", "condition=tool_agent", "--label-a", "base", "--label-b", "swap")[:1500])
