"""Is the first observation of each re-run identical to its original? Read-only."""
import json, pathlib, collections
same = diff = 0; fields = collections.Counter(); per_sweep = collections.defaultdict(lambda:[0,0,0,0]); ex = []
for old in sorted(pathlib.Path("runs/_superseded").glob("*/*")):
    if not (old/"steps.jsonl").exists(): continue
    new = pathlib.Path("runs")/old.parent.name/old.name
    a = json.loads((old/"steps.jsonl").read_text().splitlines()[0]); b = json.loads((new/"steps.jsonl").read_text().splitlines()[0])
    ca, cb = a["observation"]["content"], b["observation"]["content"]
    d = [k for k in set(ca)|set(cb) if ca.get(k)!=cb.get(k)]
    fa = a["action"]; fb = b["action"]
    first_same = fa.get("type")==fb.get("type") and fa.get("tool_call")==fb.get("tool_call") and fa.get("message")==fb.get("message")
    p = per_sweep[old.parent.name]; p[0]+=1; p[1]+= not d; p[2]+=first_same; p[3]+= (not d and first_same)
    if d:
        diff+=1; fields.update(d)
        if len(ex)<3: ex.append((old.name[:70], d, str(ca.get(d[0]))[:200], str(cb.get(d[0]))[:200]))
    else: same+=1
print("first observation identical", same, "different", diff, dict(fields))
for s,p in per_sweep.items(): print(s, "pairs",p[0],"same prompt",p[1],"same first action",p[2],"both",p[3])
for e in ex: print(e)
