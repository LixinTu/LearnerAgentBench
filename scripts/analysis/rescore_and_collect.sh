#!/bin/bash
# Re-judge every sweep against the current checks, then build the run sets the analysis reads.
cd "$(dirname "$0")/../.."
L=".venv/bin/python -m learneragentbench.harness.cli"; CF=C_adaptive_tutoring_and_intervention; C07=C07_rule_changes_mid_tutoring; A=runs/_analysis
worst=0
for s in baselines_local_v2 baselines_local_v3_new_tasks paired_variants_new_tasks_local tool_ablation_local memory_ablation_local persona_swap_local family_c_c07_rule_at_a_line_local; do
  $L rescore runs/$s 2>&1 | tail -1 | cut -c1-150; rc=${PIPESTATUS[0]}; echo "$s rescore exit=$rc"; [ $rc -gt $worst ] && worst=$rc
done
$L rescore runs/family_c_v2_local --skip-task $C07 2>&1 | tail -1 | cut -c1-150; rc=${PIPESTATUS[0]}; echo "family_c_v2_local rescore exit=$rc"; [ $rc -gt $worst ] && worst=$rc
rm -rf $A
$L collect $A/v2 runs/baselines_local_v2 --where-not family=$CF
$L collect $A/new runs/baselines_local_v3_new_tasks
$L collect $A/tool runs/tool_ablation_local --where-not family=$CF
$L collect $A/memory runs/memory_ablation_local
$L collect $A/persona runs/persona_swap_local --where-not family=$CF
$L collect $A/c runs/family_c_v2_local --where variant_id=base --where-not task_id=$C07
$L collect $A/c runs/family_c_c07_rule_at_a_line_local --where variant_id=base
$L collect $A/record runs/baselines_local_v2 --where-not family=$CF
$L collect $A/record runs/baselines_local_v3_new_tasks
$L collect $A/record runs/family_c_v2_local --where variant_id=base --where-not task_id=$C07,condition=read_only
$L collect $A/record runs/family_c_c07_rule_at_a_line_local --where variant_id=base --where-not condition=read_only
$L collect $A/variants runs/paired_variants_new_tasks_local
$L collect $A/cvariants runs/family_c_v2_local --where condition=tool_agent --where-not variant_id=base,task_id=$C07
$L collect $A/cvariants runs/family_c_c07_rule_at_a_line_local --where condition=tool_agent,variant_id=no_change
echo "worst=$worst"
exit $worst
