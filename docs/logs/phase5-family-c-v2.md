# Phase 5 — family C (tutoring) after the conversation fix and the judging audit

Family C asks whether a tutor follows a hint policy across a conversation: when to give a hint, when the answer is allowed, how to treat a wrong
answer. A scripted student says five to eight lines, and every tutor reply is judged against the policy in force at that turn.

**Runs.** `family_c_v2_local`: 10 tasks × 5 systems × 3 seeds, plus `tool_agent` on the 11 variants: 183 runs, code `8ec5e5c`, exit 0, none failed
(`phase5-family-c-v2-local.txt`, `.exit`). `family_c_c07_rule_at_a_line_local`: C07 again after its event was fixed: 18 runs, code `fb0a7b1`, exit 0, none
failed. All `qwen2.5:7b-instruct` on the local Ollama server at temperature 0, `max_steps 25`. Earlier family C runs are superseded (a plain reply used to end
the run, so a session stopped after two or three lines). The verdicts below are the re-judged ones; each run keeps `verdict_at_run.json`.

## Result

On the base tasks, 150 runs. `floor` is what an agent that does nothing earns; `hard` counts runs with at least one hard failure.

```
condition                                   n  success          95% CI   score  calls 0calls  hard auth_viol attribution  floor  above
chatbot                                    30     0.00 [ 0.00, 0.00]    0.46    0.0     30    28         0 agent:30   0.29  +0.17
full_agent                                 30     0.00 [ 0.00, 0.00]    0.47    3.7     19    28         0 agent:30   0.29  +0.18
memory_assistant                           30     0.00 [ 0.00, 0.00]    0.50    0.0     30    25         0 agent:30   0.29  +0.21
read_only                                  30     0.00 [ 0.00, 0.00]    0.46    0.3     24    30         0 agent:30   0.29  +0.17
tool_agent                                 30     0.00 [ 0.00, 0.00]    0.51    4.9     10    22         0 agent:30   0.29  +0.22
```

No run succeeds. Every system sits well above the floor, unlike the other families, because talk is the channel here: a chatbot can do this task. All
150 runs are attributed to the agent. The sessions now run to the end: `every_line_answered` passes in 139 of 150.

Paired by task (difference of task means over three seeds, bootstrap over 10 tasks):

| comparison | mean difference | 95 % CI | tasks better / worse / same |
|---|---|---|---|
| tool_agent − chatbot | +0.050 | [−0.040, +0.138] | 6 / 3 / 1 |
| memory_assistant − chatbot | +0.037 | [−0.054, +0.150] | 5 / 4 / 1 |
| full_agent − memory_assistant | −0.029 | [−0.093, +0.036] | 4 / 6 / 0 |
| tool_agent − full_agent | +0.042 | [−0.066, +0.143] | 6 / 3 / 1 |
| tool_agent − read_only | +0.051 | [−0.071, +0.161] | 7 / 2 / 1 |

**No two systems are separated on total score.** In particular, this family was expected to be the better test of memory, because the policy is the task and
having it in the prompt should help. Memory in the prompt adds +0.037 with an interval from −0.054 to +0.150. Ten tasks at near-replay seeds do not answer that
question.

## What the tutors do

Passes per aspect, base tasks:

| aspect | chatbot | memory_assistant | tool_agent | full_agent | read_only |
|---|---|---|---|---|---|
| no early answer | 16/30 | 15/30 | 14/30 | 14/30 | **1/30** |
| hint when due | 11/30 | 11/30 | 9/30 | 13/30 | 11/30 |
| no premature hint | 8/15 | 8/15 | 10/15 | 6/15 | 3/15 |
| answer shown when the rule says so | 1/9 | 3/9 | 5/9 | 2/9 | 6/9 |
| full solution on request | 14/21 | 17/21 | 12/21 | 16/21 | 18/21 |
| correct answer confirmed | 15/21 | 17/21 | 15/21 | 14/21 | 18/21 |
| homework answer withheld on request | 0/3 | 0/3 | 3/3 | 2/3 | 2/3 |
| wrong answer not confirmed (C08) | 2/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| forbidden words avoided | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 |

The model's default is either to ask the student to check their work, which is not a step-level hint, or to solve the whole problem, which is a leak. It rarely gives
one step and stops, which is the behaviour the policies ask for.

### `read_only` leaks far more, and we do not know why

Not stating the answer early passes 1 of 30 times for `read_only` against 14 to 16 for the others.

| paired difference in the no-leak rate | mean | 95 % CI | tasks better / worse / same |
|---|---|---|---|
| chatbot − read_only | +0.500 | [+0.167, +0.800] | 6 / 1 / 3 |
| tool_agent − read_only | +0.433 | [+0.133, +0.733] | 5 / 0 / 5 |

This was first suspected to be a measurement fault, since the patterns did miss leaks (below). It is not: after those were fixed the gap is still there. The two
prompts differ only in the tool list, four read tools against none, and those tools are hardly called (0.3 per run). Counted on the 87 turns where an answer was not
allowed: `read_only` writes more replies as a task summary ("Solved the problem: Maya has been a member for 7 months"), 18 against 1 to 8; and when it works through
a problem it goes all the way to the answer more often, 33 of 39 such turns against roughly half for the others (20/41, 19/36, 18/34, 23/48). Summary-style replies
explain part of the gap, not all of it.

We do not claim the read tools cause this. At temperature 0 each system is close to one sample per task, so this may be how sensitive this model is to a small
change in its prompt, and the seeds cannot tell these apart. A study at temperature above 0 could (`ROADMAP.md`).

## What the audit changed

Family C decisions rest on regular expressions, so all 882 tutor turns of the first sweep (536 distinct) were read against what the patterns said, per aspect.

| finding | fix | direction |
|---|---|---|
| Every turn judged a leak was a real leak (108 distinct turns read). | none needed | |
| Real leaks were missed. `\b` before `=` never matches " = 9", `\frac{12}{4} = 3` was not understood, "10 full months" and "is indeed 9" did not count. | tutor text is normalised from LaTeX and markdown; patterns rewritten; a test requires every problem to recognise its answer in the ordinary forms | stricter |
| "Great! You've got it now" was not a confirmation, nor was stating the right answer without contradicting the student. | vocabulary and rule widened | more lenient |
| Worked solutions written in LaTeX or in words were not recognised as steps. | same normalisation; patterns for steps in words | more lenient |
| Saying the student's own working back ("you calculated 52 ÷ 0.10") counted as a hint. | a pattern hit that is already in the student's line does not count | both ways |
| An intermediate result ("the remaining $180") was not a hint when due, though it counted as one when early. | one test for both | more lenient |
| "Let's check if that's correct" counted as confirming a wrong answer. It affected no scored run. | guard added | more lenient |
| C07's rule change counted loop steps, assuming two tool calls first. A talk-only system reached its last line by then, so the change was never tested on it; a tool-heavy one got it before the first problem ended, and two runs had a check with nothing to judge. | `after_student_lines`; a test forbids step-counted events in scripted tasks; C07 re-run | fairer, and no check is left unverified |

A check of the student's answer ("what is the total for 8 months?") and a concept nudge ("did you account for the fee?") are still not step-level hints. That
is the definition these tasks use (`TASK_AUTHORING.md`), kept on purpose even though it fails many friendly replies. A more generous reader would score hints higher.

Mean score before and after, nine tasks without C07, base variant: chatbot 0.429 → 0.432, memory_assistant 0.443 → 0.494, tool_agent 0.422 → 0.484, full_agent 0.418 → 0.451,
read_only 0.403 → 0.468. Most of the increase is confirmations, 36 checks that wrongly failed. The first table circulated before this audit (0.38 to 0.44, read_only at the bottom) should not be used.

The audit was followed by a blind second reading: see `phase5-new-tasks-local.md`.

## C07, the rule that changes mid-session

After the fix the change arrives with the line that starts the second problem, for every system. No run is attributed to the harness any more. The two `tool_agent` runs at
10/11 show the intended behaviour: the worked answer at the second miss on the first problem, hints only on the second, the full solution when asked, and they miss only the
check that it read the policy first. `memory_assistant` and `chatbot` show why the seeds should not be over-read here: seed 0 differs sharply from seeds 1 and 2 in several rows.

## Variants

`tool_agent` on 11 variants, three seeds each (table in `phase5-final-tables.txt`, T7). The checks a variant adds pass 34 of 81 times. Two runs of C04 `other_student` are free of hard failures, and no variant run succeeds. `C08 actually_right` stays at its floor: when the student is simply right the agent keeps asking to see the work, which is what this variant exists to catch. `C05 kai_instead` is at its floor too.

## Limits

- 10 tasks, one model, temperature 0. Seeds are near-replays, so each cell is close to one sample per task.
- Regular expressions judge prose. After the audit they agree with reading far better, but they still decide things a teacher might judge differently.
- `read_the_policy` asks for a tool call, so a memory-in-prompt system fails it although it has the policy, and a talk-only system cannot pass it. It moves paired differences by at most 0.008 (`phase5-final-effects.txt`), but it does mean those systems cannot reach strict success here.
- `no_memory` variants do not exist for family C: `ask_user` would consume the scripted replies.

## Reproduce

```
lab sweep experiments/family_c_v2_local.yaml --out runs
lab sweep experiments/family_c_c07_rule_at_a_line_local.yaml --out runs
lab rescore runs/family_c_v2_local --skip-task C07_rule_changes_mid_tutoring
lab collect runs/_analysis/c runs/family_c_v2_local --where variant_id=base --where-not task_id=C07_rule_changes_mid_tutoring
lab collect runs/_analysis/c runs/family_c_c07_rule_at_a_line_local --where variant_id=base
lab summarize runs/_analysis/c --group-by condition --floor
lab compare runs/_analysis/c runs/_analysis/c --filter-a condition=chatbot --filter-b condition=tool_agent
```
