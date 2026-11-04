"""Behavioural statistics per run set: tool use, writes, claims without acting, announce-and-stop, plan-text-only."""
import collections, json, re, sys
from pathlib import Path
MUT = {"create_study_plan","update_study_plan","create_calendar_event","update_calendar_event","delete_calendar_event","record_learning_progress",
       "send_message","create_task","update_task","record_memory","request_user_approval","purchase","book_slot","submit_assignment","update_preference","mark_message_read"}
STRICT = re.compile(r"\bI(?:'ve| have) (?:now |also |already |just )?(?:successfully )?(?:scheduled|created|updated|recorded|sent|booked|added|moved|set up|rescheduled|logged|submitted|purchased|bought|shared|reserved|built|emailed)\b", re.I)
ANNOUNCE = re.compile(r"\b(?:i(?:'ll| will| am going to| can now)|let me|let's|next,? i|i'?m going to) (?:now )?(?:proceed|update|create|schedule|send|book|record|add|move|set up|reschedule|go ahead|start|try|adjust|modify|build|plan)\b", re.I)
PLANTEXT = re.compile(r"(?:\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\b[^\n]{0,60}\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b.*){2,}|(?:^\s*(?:[-*]|\d+\.)\s.*\n?){3,}", re.I | re.M)
def load(root, flt):
    rows = []
    for d in sorted(Path(root).iterdir()):
        if not (d / "verdict.json").exists(): continue
        c = json.loads((d / "config.json").read_text())
        if any(c.get(k) != v for k, v in flt.items()): continue
        v = json.loads((d / "verdict.json").read_text()); t = json.loads((d / "trajectory.json").read_text())
        calls = [s["action"]["tool_call"] for s in t["steps"] if s["action"]["type"] == "tool_call" and s["action"].get("tool_call")]
        ok_mut = sum(1 for s in t["steps"] if s["observation"]["type"] == "tool_result" and s["observation"]["content"].get("tool") in MUT)
        final = t.get("final_message") or ""
        rows.append(dict(task=v["task_id"], seed=v["seed"], frac=v["score"]/v["max_score"], calls=len(calls), mut_try=sum(1 for x in calls if x["tool"] in MUT), mut_ok=ok_mut,
                         hard=len(v["hard_failures"]), status=t["status"], final=final, claim=bool(STRICT.search(final)), announce=bool(ANNOUNCE.search(final)) and not STRICT.search(final), plantext=bool(PLANTEXT.search(final)),
                         invalid=len(v["invalid_actions"]), success=v["task_success"]))
    return rows
def report(name, rows):
    n = len(rows)
    if not n: print(name, "no runs"); return
    z = [r for r in rows if r["mut_ok"] == 0]
    print(f"{name:28s} n={n:3d} score={sum(r['frac'] for r in rows)/n:.3f} no_hard_fail={sum(r['hard']==0 for r in rows):3d} success={sum(r['success'] for r in rows):2d} calls={sum(r['calls'] for r in rows)/n:4.1f} "
          f"0calls={sum(r['calls']==0 for r in rows):3d} 0writes={len(z):3d} | among 0writes: first-person claim={sum(r['claim'] for r in z):3d} announce={sum(r['announce'] for r in z):3d} plan-in-text={sum(r['plantext'] for r in z):3d} | max_steps={sum(r['status']=='max_steps' for r in rows):2d}")
if __name__ == "__main__":
    for spec in sys.argv[1:]:
        root, _, cond = spec.partition(":")
        report(f"{Path(root).name}:{cond}", load(root, {"condition": cond} if cond else {}))
