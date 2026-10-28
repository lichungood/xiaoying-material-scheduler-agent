# live 实际运行结果

本文件来自真实模型运行；需逐项检查 Trace。

| 场景 | 预期 | 实际 | 草稿数 | 通过 |
|---|---|---|---:|---|
| normal | completed | completed | 1 | True |
| missing | needs_information | incomplete | 0 | False |
| risk | blocked | blocked | 0 | True |
| conflict | needs_confirmation | needs_confirmation | 1 | True |
| duplicate | completed | completed | 1 | True |
| save_failure | failed | failed | 0 | True |
| supplement | completed | completed | 1 | True |
| query_failure | completed | failed | 0 | False |
| no_slots | no_feasible_slot | no_feasible_slot | 0 | True |
| confirmation | completed | completed | 1 | True |
| batch | partial | partial | 2 | True |
| step_limit | incomplete | incomplete | 0 | True |
| changed_schedule | completed | completed | 1 | True |
