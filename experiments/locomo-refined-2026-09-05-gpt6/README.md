# LoCoMo-Refined 严格·演进实验现场

实验与阶段C已完成：10库、272个session、1,382道题。官方全量 **78.2923%（1082/1382）**；剔除两道烧题后 **78.2609%（1080/1380）**。F1 52.4936%，BLEU 43.9291%。与既往76.34%及78.15%处于相近水平，本次不主张差异。

先读 [RUN-REPORT.md](RUN-REPORT.md) 了解配置、分组成绩、成本、耗时和错误分析；[RUN-LOG.md](RUN-LOG.md) 保存UTC全过程与恢复入口；[FROZEN.md](FROZEN.md) 保留两段冻结及预算修订的全部旧/新哈希。最终核验见 [final-verification.json](results/final-verification.json)，当前状态见 [state/progress.json](state/progress.json)。

同一条严格·演进主线披露了预算口径误停、OpenRouter HTTP402资金中断、Codex账户上限中断，以及编排者原样重启。只有预算guard经维护者授权重冻结；契约、材料、答题doctrine和scorer没有因此改变。构建保留118/213个封存检查点，答题保留801份完成答案。16个HTTP402失败job通过框架正常路径解决。时间表将停顿和编排者恢复端点分开，Codex停顿仅报可证实的上界。

自身记录构建+答题费用 **$17.896440**，不是完整账单；judge另计且可归因金额未知。Own accounting undercounts (approximately 40% was observed at 07:16Z); key-level figures are not attributable while the key is shared. 约40%是当时观察缺口，不能用作固定校正系数。

## 结果与现场

- [predictions.jsonl](results/predictions.jsonl)：1,382个唯一qa_id及系统作答。
- [scored-stripped.jsonl](results/scored-stripped.jsonl)：剥离题面、金标与证据后的逐题分数。
- [official-summary.md](results/official-summary.md)：官方原样汇总；[dual-scores.json](results/dual-scores.json) 提供双分数。
- [session-progress.csv](build-record/session-progress.csv)、[stage-costs.json](results/stage-costs.json)、[stoppages.json](results/stoppages.json)：完整进度、记录费用与停顿边界。
- [error-analysis.json](results/error-analysis.json)：评分落地后8道分层随机错题及2道目的性补充的脱敏判读。

本次lr6r2-01至lr6r2-10容器已关闭并移除，40个卷保留。框架worktree源码保持只读；data、material、app-*、logs和secrets均不入库。原始题库金标字段的直接读取禁令继续有效，分析仅使用评分已完成的产物。旧failure-summary和results/incidents下的停止报告属于历史事件，不能当作最终状态。

## 复查与重现

同机数值复查与报告再生成不调用模型：

```sh
repo/.venv/bin/python scripts/report_metrics.py
repo/.venv/bin/python scripts/final_report.py
repo/.venv/bin/python scripts/verify_final.py
```

阶段C的执行顺序为post_score_audit.py → report_metrics.py → error-analysis → final_report.py；十库只读审计已有完成标记，报告再生成复用已有分析。verify_final.py核验冻结、封存检查点、逐题对齐、分数、脱敏和本次资源状态，不启动流水线。

本现场执行已结束，无需重新启动pipeline。若接续未完成的副本，先查state/progress.json和state/pipeline-pid.json，确认没有活动进程，再使用冻结的scripts/pipeline.py；它以锁、原子标记和哈希实现幂等恢复，不删除完成标记、不重建完成单元。长任务按RUN-LOG记载用nohup并保持工具承载会话。

异地完整复现需要框架c58efd5618d3734fa97e535895ac07019d37e5cd、数据集887091190789e8d6760e70b9edd696539923dc4f及冻结配置，依TASKBOOK在独立目录创建自己的scaffold资源与随机端口，由拥有者提供忽略目录中的凭据。setup_projects.py/configure_build.py/to_material.py记录了准备方式；随机环境路径变化必须重新登记哈希。git中的完成标记不是数据库备份，不能直接搬到空库后当成已完成构建。模型与判官的再次运行不保证逐字相同。
