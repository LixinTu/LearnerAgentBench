"""``lab`` — the benchmark command line.

    lab list [--family F]
    lab validate --all | TASK_ID [--oracle]
    lab run --model M --adapter {oracle,openai_compatible} [--task T ...] [--family F ...]
            [--variant V ...] [--seed S ...] [--persona P] [--max-steps N] [--out DIR]
            [--memory-access full|transcripts_only|none] [--tool-profile full|read_only|none]
            [--base-url URL] [--json-fallback] [--interrupt-after N]
    lab resume RUN_DIR --model M --adapter A [...]
    lab reverify RUN_DIR
    lab show RUN_DIR
    lab summarize RUNS_ROOT [--group-by condition,family] [--floor]
    lab rescore RUNS_ROOT [--dry-run] [--skip-family F]
    lab collect OUT ROOT [ROOT ...] [--where k=v] [--where-not k=v]
    lab compare RUNS_A RUNS_B [--filter-a k=v,...] [--filter-b k=v,...] [--pair-on task_id,seed]
    lab coverage [--write docs/COVERAGE.md]
    lab sweep experiments/<name>.yaml [--out runs] [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..schema import RunConfig, TaskFamily
from ..tasks import Dataset
from ..verify import VERIFIERS


def _config_from_args(a: argparse.Namespace) -> RunConfig:
    params = {}
    if getattr(a, "base_url", None):
        params["base_url"] = a.base_url
    if getattr(a, "json_fallback", False):
        params["json_fallback"] = True
    if getattr(a, "interrupt_after", None) is not None:
        params["interrupt_after"] = a.interrupt_after
    if getattr(a, "max_tokens", None):
        params["max_tokens"] = a.max_tokens
    return RunConfig(model=a.model, adapter=a.adapter, task_ids=list(getattr(a, "task", []) or []),
                     families=[TaskFamily(f) for f in (getattr(a, "family", []) or [])],
                     persona_ids=[a.persona] if getattr(a, "persona", None) else [],
                     variant_ids=list(getattr(a, "variant", None) or ["base"]), seeds=list(getattr(a, "seed", None) or [0]),
                     max_steps=getattr(a, "max_steps", None), output_dir=getattr(a, "out", "runs"),
                     memory_access=getattr(a, "memory_access", "full"), tool_profile=getattr(a, "tool_profile", "full"),
                     temperature=getattr(a, "temperature", 0.0), adapter_params=params, tags=list(getattr(a, "tag", []) or []))


def cmd_list(a: argparse.Namespace) -> int:
    ds = Dataset(a.data_dir)
    fams = [TaskFamily(f) for f in a.family] if a.family else None
    for tid in ds.task_ids(fams):
        t = ds.load_task(tid)
        print(f"{tid:36s} {t.family.value:44s} persona={t.persona_id:10s} variants={len(t.variants)} checks={len(t.checks)}")
    print(f"personas: {ds.persona_ids()}  skill graphs: {ds.graph_ids()}")
    return 0


def cmd_validate(a: argparse.Namespace) -> int:
    from .validate import validate_task
    ds = Dataset(a.data_dir)
    ids = ds.task_ids() if a.all else [a.task_id]
    bad = 0
    for tid in ids:
        report = validate_task(ds, tid, run_oracle=a.oracle, out_root=a.out)
        status = "OK " if report["ok"] else "BAD"
        print(f"[{status}] {tid}: {report['summary']}")
        for line in report["problems"]:
            print(f"      - {line}")
        bad += 0 if report["ok"] else 1
    print(f"{len(ids) - bad}/{len(ids)} tasks valid; {len(VERIFIERS)} verifiers registered")
    return 1 if bad else 0


def cmd_run(a: argparse.Namespace) -> int:
    from .runner import run_one
    ds = Dataset(a.data_dir)
    cfg = _config_from_args(a)
    task_ids = list(cfg.task_ids) or ds.task_ids(cfg.families or None)
    if cfg.persona_ids:
        task_ids = [t for t in task_ids if ds.load_task(t).persona_id in cfg.persona_ids]
    if not task_ids:
        print("no tasks selected", file=sys.stderr)
        return 2
    rows = []
    for tid in task_ids:
        for vid in cfg.variant_ids:
            for seed in cfg.seeds:
                res = run_one(ds, tid, vid, cfg, seed, out_root=cfg.output_dir)
                v = res.verdict
                rows.append(v)
                print(f"{tid} {vid} s{seed}: {'SUCCESS' if v.task_success else 'fail'} score={v.score:g}/{v.max_score:g} "
                      f"status={res.trajectory.status} steps={len(res.trajectory.steps)} calls={v.tool_call_count} "
                      f"attr={v.failure_attribution} -> {res.out_dir}")
    n_ok = sum(1 for v in rows if v.task_success)
    print(f"{n_ok}/{len(rows)} runs succeeded")
    return 0


def cmd_resume(a: argparse.Namespace) -> int:
    from .runner import resume_run
    res = resume_run(a.run_dir, _config_from_args(a), Dataset(a.data_dir))
    print(f"resumed: status={res.trajectory.status} success={res.verdict.task_success} score={res.verdict.score:g}/{res.verdict.max_score:g}")
    return 0


def cmd_reverify(a: argparse.Namespace) -> int:
    from .runner import reverify
    v = reverify(a.run_dir, Dataset(a.data_dir))
    print(f"success={v.task_success} score={v.score:g}/{v.max_score:g} attribution={v.failure_attribution}")
    return 0


def cmd_show(a: argparse.Namespace) -> int:
    out = Path(a.run_dir)
    v = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
    t = json.loads((out / "trajectory.json").read_text(encoding="utf-8"))
    print(f"run {v['run_id']}\n task {v['task_id']} variant {v['variant_id']} seed {v['seed']} model {v['model']}")
    print(f" status {t['status']}  success {v['task_success']}  score {v['score']}/{v['max_score']}  attribution {v['failure_attribution']}")
    for c in v["checks"]:
        mark = {True: "PASS", False: "FAIL", None: "n/a "}[c["passed"]]
        print(f"  [{mark}] {c['check_id']:28s} w={c['weight']:g}{' HARD' if c['hard'] else ''}  {c['evidence'][:110]}")
    if v["authorization_violations"]:
        print(" authorization violations:", *v["authorization_violations"], sep="\n   ")
    print(" steps:")
    for s in t["steps"]:
        act = s["action"]
        what = act["tool_call"]["tool"] + " " + json.dumps(act["tool_call"]["args"])[:70] if act["type"] == "tool_call" else act["type"] + " " + act["message"][:70]
        print(f"  {s['index']:3d} {s['observation']['type']:12s} -> {what}")
    print(" final:", t["final_message"][:300])
    return 0


def cmd_sweep(a: argparse.Namespace) -> int:
    from .sweep import run_sweep
    stats = run_sweep(a.experiment, out_root=a.out, data_dir=a.data_dir, dry_run=a.dry_run, limit=a.limit)
    print(f"planned={stats['planned']} done={stats['done']} skipped={stats['skipped']} failed={stats['failed']} -> {stats['out']}")
    return 0


def cmd_coverage(a: argparse.Namespace) -> int:
    from .coverage import coverage_matrix, render_markdown
    md = render_markdown(coverage_matrix(Dataset(a.data_dir)))
    if a.write:
        Path(a.write).write_text(md, encoding="utf-8")
        print(f"written: {a.write}")
    else:
        print(md)
    return 0


def cmd_summarize(a: argparse.Namespace) -> int:
    from ..analysis import summarize_runs
    print(summarize_runs(a.runs_root, group_by=a.group_by, floor=a.floor, data_dir=a.data_dir))
    return 0


def cmd_rescore(a: argparse.Namespace) -> int:
    from .runner import RescoreError, rescore
    ds = Dataset(a.data_dir)
    n = moved = 0
    refused: list[str] = []
    for p in sorted(Path(a.runs_root).glob("*/verdict.json")):
        if a.skip_family and json.loads((p.parent / "task_effective.json").read_text(encoding="utf-8")).get("family") == a.skip_family:
            continue
        n += 1
        try:
            verdict, changed = rescore(p.parent, ds, dry_run=a.dry_run)
        except RescoreError as exc:
            refused.append(str(exc))
            continue
        if changed:
            moved += 1
            print(f"changed: {p.parent.name}: now {verdict.score:g}/{verdict.max_score:g}")
    print(f"{a.runs_root}: {n} runs judged against the current checks, {moved} changed, {len(refused)} refused" + (" (dry run)" if a.dry_run else ""))
    for r in refused:
        print("refused:", r)
    return 1 if refused else 0


def cmd_collect(a: argparse.Namespace) -> int:
    from ..analysis import collect_runs, parse_filter
    n = collect_runs(a.out, a.sources, where=parse_filter(a.where), where_not=parse_filter(a.where_not))
    print(f"{n} runs collected into {a.out}")
    return 0


def cmd_compare(a: argparse.Namespace) -> int:
    from ..analysis import compare_runs, parse_filter
    try:
        print(compare_runs(a.runs_a, a.runs_b, filter_a=parse_filter(a.filter_a), filter_b=parse_filter(a.filter_b),
                           pair_on=a.pair_on, label_a=a.label_a, label_b=a.label_b))
    except ValueError as exc:
        print(f"compare: {exc}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=None, help="dataset root (default: the package's data/)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list")
    p.add_argument("--family", action="append")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("validate")
    p.add_argument("task_id", nargs="?")
    p.add_argument("--all", action="store_true")
    p.add_argument("--oracle", action="store_true", help="also run the oracle policy and require success")
    p.add_argument("--out", default="runs/validate")
    p.set_defaults(fn=cmd_validate)

    def run_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--model", required=True)
        p.add_argument("--adapter", required=True, choices=["oracle", "openai_compatible"])
        p.add_argument("--task", action="append")
        p.add_argument("--family", action="append")
        p.add_argument("--variant", action="append")
        p.add_argument("--seed", action="append", type=int)
        p.add_argument("--persona")
        p.add_argument("--max-steps", type=int)
        p.add_argument("--out", default="runs")
        p.add_argument("--memory-access", default="full", choices=["full", "transcripts_only", "none"])
        p.add_argument("--tool-profile", default="full", choices=["full", "read_only", "none"])
        p.add_argument("--base-url")
        p.add_argument("--json-fallback", action="store_true")
        p.add_argument("--interrupt-after", type=int)
        p.add_argument("--max-tokens", type=int)
        p.add_argument("--temperature", type=float, default=0.0)
        p.add_argument("--tag", action="append")

    p = sub.add_parser("run")
    run_args(p)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("resume")
    p.add_argument("run_dir")
    run_args(p)
    p.set_defaults(fn=cmd_resume)

    p = sub.add_parser("reverify")
    p.add_argument("run_dir")
    p.set_defaults(fn=cmd_reverify)

    p = sub.add_parser("show")
    p.add_argument("run_dir")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("summarize")
    p.add_argument("runs_root")
    p.add_argument("--group-by", default="model,variant_id")
    p.add_argument("--floor", action="store_true", help="add what a passive agent scores on the same tasks, and the score above it")
    p.set_defaults(fn=cmd_summarize)

    p = sub.add_parser("rescore", help="judge stored runs against the current checks, without re-running the agent")
    p.add_argument("runs_root")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-family", default=None)
    p.set_defaults(fn=cmd_rescore)

    p = sub.add_parser("collect", help="copy the scoring files of selected runs into one run set")
    p.add_argument("out")
    p.add_argument("sources", nargs="+")
    p.add_argument("--where", default=None, help="k=v[,k=v]")
    p.add_argument("--where-not", default=None, help="k=v[,k=v]")
    p.set_defaults(fn=cmd_collect)

    p = sub.add_parser("compare", help="paired comparison of two run sets (same tasks and seeds)")
    p.add_argument("runs_a")
    p.add_argument("runs_b")
    p.add_argument("--filter-a", default=None, help="k=v[,k=v] on verdict/sidecar fields, e.g. condition=tool_agent,variant_id=base")
    p.add_argument("--filter-b", default=None)
    p.add_argument("--pair-on", default="task_id,seed")
    p.add_argument("--label-a", default="A")
    p.add_argument("--label-b", default="B")
    p.set_defaults(fn=cmd_compare)

    p = sub.add_parser("sweep")
    p.add_argument("experiment", help="experiments/<name>.yaml")
    p.add_argument("--out", default="runs")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None, help="run at most N new runs (resumable)")
    p.set_defaults(fn=cmd_sweep)

    p = sub.add_parser("coverage")
    p.add_argument("--write", default=None, help="write the Markdown matrix to this path")
    p.set_defaults(fn=cmd_coverage)

    a = ap.parse_args(argv)
    if a.cmd == "validate" and not a.all and not a.task_id:
        ap.error("validate needs a TASK_ID or --all")
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
