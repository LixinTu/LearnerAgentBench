# LearnerAgentBench: notes for agents

Run and test (all from this directory):

```
.venv/bin/ruff check src tests && .venv/bin/pyright src
.venv/bin/python -m pytest tests -q
.venv/bin/python -m learneragentbench.harness.cli validate --all --oracle
```

`lab` means `.venv/bin/python -m learneragentbench.harness.cli`. Plan and status: `docs/ROADMAP.md`. Evidence: `docs/logs/`.

Hard constraints:

- Commit as Lixin Tu <ltu35@gatech.edu>. Local commits only: no push, no paid API, no cloud compute, no real student data.
- Local model: Ollama at http://127.0.0.1:11434/v1, `qwen2.5:7b-instruct`. Mock and oracle scores are never agent results.

Pitfalls we actually hit:

- A background shell reports exit 0 whatever happened. The real exit code is in `docs/logs/*.exit`.
- Sweep logs are block-buffered unless python runs with `-u`. Count `verdict.json` files to see progress.
- A tool answer can mislead the model: read transcripts before calling a failure the model's. Permission was once checked before existence, so a wrong contact id came back as "needs approval".
- A sweep file with `tasks: [all]` expands to tasks added since it last ran. To repeat particular runs use `lab rerun`, not `lab sweep`.
- Changed a check: `lab rescore` (the agent could not see it). Changed anything the agent sees: `lab rescore` refuses, so re-run.
- Do not edit `data/` or `src/` while a sweep or the checks are running.
- Read every run that looks successful. Two of five first-look successes were a false report and an invented schedule that the checks could not see.
- Text checks match whole words, so keyword lists hold real words, never stems (`docs/TASK_AUTHORING.md` rule 11).
- At temperature 0 the seed only changes the run id in the prompt: three seeds are near-replays, roughly one sample per task.
- Read every score against the passive floor (`lab summarize --floor`). A do-nothing agent scores about 0.27.
- Persona memory ids are hash-generated: look them up before `memory_remove` or `memory_replace`, which raise on unknown ids.
- `trajectory.asked_user` needs every keyword in one question, so give one keyword.
