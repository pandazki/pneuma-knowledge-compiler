#!/usr/bin/env python3
"""Assemble the final Chinese report from scored, stripped, auditable artifacts."""
import collections
import json
import statistics
from pathlib import Path
from report_metrics import table

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT / name).read_text())


def minutes_range(lower, upper):
    return f'{lower/60:.2f}' if lower == upper else f'{lower/60:.2f}–{upper/60:.2f}'


def main():
    assert (ROOT / 'state/score.done').exists()
    assert (ROOT / 'state/post-score-audit.done').exists()
    rows = [json.loads(x) for x in (ROOT / 'results/scored-stripped.jsonl').read_text().splitlines()]
    scores = read('results/dual-scores.json')
    costs = read('results/stage-costs.json')
    build = read('results/build-completion.json')
    durations = read('results/durations.json')
    stoppages = read('results/stoppages.json')
    analysis = read('results/error-analysis.json')
    audits = [read(f'build-record/post-score-audit-{i:02d}.json') for i in range(10)]
    events = [json.loads(x) for x in (ROOT / 'build-record/events.jsonl').read_text().splitlines()]
    usage = [json.loads(p.read_text()) for p in (ROOT / 'build-record/answers').glob('*.json')]
    assert len(rows) == len(usage) == 1382
    assert all(a['pending'] == a['unresolved'] == 0 for a in audits)
    assert sum(a['historical_http402_jobs_retained'] for a in audits) == 16
    assert sum(a['http402_jobs_still_unresolved'] for a in audits) == 0
    evolve = collections.Counter()
    for a in audits:
        evolve.update(a['evolve_status_counts'])
    challenge = [c for a in audits for c in a['challenge']]
    own = sum(c['usd'] or 0 for c in costs.values())
    correct = sum(r['llm_score'] for r in rows)
    f1 = 100 * statistics.mean(r['f1_score'] for r in rows)
    bleu = 100 * statistics.mean(r['bleu_score'] for r in rows)
    latency = sorted(r['seconds'] for r in usage)
    source = 'https://github.com/mem-eval-suite/LoCoMo_refined/blob/887091190789e8d6760e70b9edd696539923dc4f/README.md'
    cost_rows = []
    for name, c in costs.items():
        amount = f'${c["usd"]:.6f}' if c['usd'] is not None else '未记录，不能按免费处理'
        cost_rows.append(f'| {name} | {c["jobs"]} | {c.get("jobs_with_usage", 0)} | {c["input_tokens"]:,} | {c["output_tokens"]:,} | {amount} |')
    timing_rows = [f'| {d["phase"]} | {d["attempts"]} | {d["wall_seconds"]/60:.2f} | {minutes_range(d["active_seconds"], d["active_seconds_upper_bound"])} | {minutes_range(d["pause_seconds_lower_bound"], d["pause_seconds"])} | {d["start"]} | {d["end"]} |' for d in durations]
    names = {'budget-stop': '预算口径误停（内部基础设施）', 'provider-402': '提供方资金中断（外部服务）', 'codex-limit': 'Codex账户用量上限（执行环境）'}
    pause_rows = [f'| {names.get(d["incident"], d["incident"])} | {"≤" if d["duration_is_upper_bound"] else ""}{d["seconds"]/60:.2f} | {d["stopped_utc"]} | {d["resumed_utc"]} |' for d in stoppages]
    codex = read('results/codex-restart-audit.json')
    pause_rows.append(f'| 编排者原样重启（恢复事件，未另计停顿） | — | {codex["resumed_utc"]} | 同一Codex停顿的结束点 |')
    error_rows = [f'| {x["qa_id"]} | {x["category"]} | {x["classification"]} | {x["observation"]} |' for x in analysis['samples']]
    evolve_steps = sum(e['event'] == 'EVOLVE_FINISHED' for e in events)
    forced = sum(e['event'] == 'EVOLVE_FINISHED' and e['forced'] for e in events)
    retries = sum(e['event'] == 'ANSWER_RETRY' for e in events)
    text = f'''# LoCoMo-Refined 严格·演进全量评测

官方全量 **{scores['official']:.4f}%（{correct:g}/1,382）**；剔除两道烧题后 **{scores['unburned']:.4f}%（1,380题）**。全量 F1 **{f1:.4f}%**、BLEU **{bleu:.4f}%**。完成10库、272个session、1,382次作答及官方refined判分。

这是同一条严格·演进主线。执行期间发生预算口径误停、提供方HTTP402资金中断，以及Codex账户用量上限导致的会话中断；后者由编排者原样重启流水线。恢复保留完成单元，未对已完成答案选择性重答、调参或挑选判分结果。内部预算guard经明确授权仅作基础设施重冻结；提供方资金中断、Codex中断和编排者重启都不是实验内容干预。完整时间线见 [RUN-LOG](RUN-LOG.md)，旧/新哈希见 [FROZEN](FROZEN.md)。

## 协议与可复查性

框架固定为 `c58efd5618d3734fa97e535895ac07019d37e5cd`；数据集固定为 `887091190789e8d6760e70b9edd696539923dc4f`。执行者GPT-6；实际编译、检索、答题等文本模型均为 `openai/gpt-5.6-luna`，GPT角色经OpenRouter钉官方 `openai` provider，禁止fallback。执行者模型与被测系统模型不能混为一谈。

契约只依据结构白名单和十个首session设计。白名单先用诱饵对象验证；272个材料均用生成项目真实解析函数往返校验，speaker/text逐字节一致，caption与query分别保留。答题程序只投影qa_id、conversation_idx、question；未把金标字段交给被测模型。执行者从未直接查看原始题库的answer/evidence/evidence_messages/category字段；阶段C仅从已完成的判分产物读取分析所需信息。

两段冻结分别覆盖构建依赖与答题/判分/doctrine。执行前和恢复前核验SHA-256；预算修订B之外的实验内容没有改变。118和213个封存checkpoint在最终构建时仍逐个一致，未重建已完成单元。框架源码只读，未读取既往实验分支或报告。

官方README暴露的两个ID为 `conv-26#q0000`、`conv-26#q0001`，烧题表只记录ID和出处。提交1,382行，qa_id唯一且与官方题库逐一对齐。官方原脚本以 `--metrics llm f1 bleu --llm-judge refined --concurrency 64` 调用，判官为 `qwen/qwen3-14b`。参见 [提交核验](state/predictions-validated.json)、[官方原样汇总](results/official-summary.md)、[双分数](results/dual-scores.json)。

## 实验设计与押注

| 选择 | 冻结设置与理由 |
|---|---|
| 十份契约 | 共同约束人物归属、具体事实、完整集合、时间与证据；主题族只由各首session决定，不写具体答案值 |
| 逐session严格构建 | 按时间 ingest→compile→队列清零；有未解决失败即停止该单元，不伪造完成 |
| 模型与成本 | 文本角色全部Luna；embedding为text-embedding-3-small；押注通用小模型在明确契约和宽证据下足够，避免Astra超预算 |
| people/time | 开启人物投影与时间索引；UTC为重放日期默认，不声称是参与者真实时区 |
| attention/silent | 不开attention；评测ask使用silent，访问账本不应因测量改变 |
| overview | 默认四槽、2000字符、8 claims后要求概览，保留页面导航和原始事实层 |
| 状态变化与归档 | 契约要求区分supersede与纠错，保留有效历史；不主动archive普通历史，不把这些能力必然转化为分数收益 |
| 语义切分/图像 | semantic、smart重叠；caption模式，分别标记BLIP描述和query，不发送原图 |
| challenge | 每轮最多4问、最多1轮、输出上限4096，确认缺口后补偿编译 |
| evolve | 至少60条新增claims且隔5个session触发，尾部强制；`adopt-clean`程序化采纳，未人工挑选提案 |
| 答题doctrine | fast/concise、all/structured，plan_queries=3，候选claims=80/windows=60，all_context_chars=120000，answer reasoning=high |
| 后处理 | 仅移除机器引用和HTML注释；不按题目/类别改写答案，不强迫猜测，保留框架弃答约束 |
| 拓扑/并发 | 两库同时运行，各默认4个middleware容器；答题全局32路、跨库且库内并发，退避和幂等续跑；只操作lr6r2资源 |

任务书估计每栈6个容器，实际CLI默认启动4个；本次不启动console。大证据池与concise风格的押注，是让模型同时获得较宽覆盖并压缩输出；本次没有消融，无法单独认定它、people/time、semantic或challenge带来了多少分。

## 分组成绩

均按题目加权，LLM/F1/BLEU列均为百分比；category与模态标签只在评分落地后从判分产物读取。

### 分 conversation

{table(rows, 'conversation_idx')}

### 分 category

{table(rows, 'category')}

### 分模态

{table(rows, 'is_multi_modality')}

模态分组反映数据集标签。本次使用图像描述/query元数据，不能把有图题的成绩解释为原生视觉能力。

## 官方榜与既往线

固定数据集提交的[官方README]({source})列出以下LLM参照值；这不是实时榜，不保证各系统的模型、预算、输入表示及执行细节一致。

| 系统 | 官方README LLM % |
|---|---:|
| MemoraX AI | 82.65 |
| MemOS | 63.60 |
| MemPalace | 58.68 |
| EverMemOS | 58.25 |
| Mem0 | 48.91 |
| 本次严格·演进 | {scores['official']:.4f} |

| 运行 | 框架 | 执行者 | LLM % | 本次差值 pp | 已知协议差异 |
|---|---|---|---:|---:|---|
| 2026-08-06 | c132a27 | 未提供 | 76.34 | {scores['official']-76.34:+.4f} | 参考脚本五库并行、库内串行答题；evolve 50 claims/4 sessions；契约和doctrine未提供 |
| 2026-09-03 | 0646268 | GPT-5.6 | 78.15 | {scores['official']-78.15:+.4f} | 只知道任务书给出的框架/执行者/成绩；不能补猜其配置 |
| 2026-09-05 本次 | c58efd5 | GPT-6 | {scores['official']:.4f} | 0 | 两库、32路答题、60 claims/5 sessions，本文完整配置 |

三条既往/当前线按任务书属于同协议同判官，但框架版本、执行者与实验设计同时变化，被测角色配置的历史细节也不完整。没有消融或重复运行，不能把差值归因到某个组件或执行者。任务书提示判官噪音约±1pp，本次没有重复判分估计噪音；2–3pp以内不主张差异。更大的观测差值也不构成单变量因果证据。

## 成本口径

Own accounting undercounts (approximately 40% was observed at 07:16Z); key-level figures are not attributable while the key is shared.

自身归因账存在低估（07:16Z观察约40%）；共享key期间key级数字不可归因于本实验。约40%是当时job账与key差额的观察缺口，后者后来确认有外部流量，不能作为已校准真实漏计率，也不乘固定校正因子。Codex中断时尚未落盘的在飞请求可能已收费并在恢复后重发，也不在完整记录账中；运行agent本身的Codex额度费用另属执行环境，不计入被测系统的OpenRouter token账。

| 环节 | job/题数 | 有token记录数 | input token | output token | 声明价估算 USD |
|---|---:|---:|---:|---:|---:|
{chr(10).join(cost_rows)}
| embedding（跨index/recall） | 未分项记录 | 未记录 | 未知 | — | 未知 |
| official judge | 1,382 | 未记录 | 未知 | 未知 | 共享key差额不可归因 |

已记录构建+答题合计 **${own:.6f}**。Luna按每百万input/output **$0.20/$1.20**计价，缓存保守按普通输入价；ask数据是检索规划、证据处理与最终答题的CLI汇总，不能再按角色拆账。embedding声明价$0.02/百万input，但没有完整用量记录。challenge、evolve、index或失败子调用未记token时是未知费用，不是免费。合成预检另有18 token（13 input/5 output），provider自报$0.0000086。

判官另计；原scorer记录的 [judge-cost](results/judge-cost.json) 是共享key级前后读数，**不可归因为本次判官费用**，不与自身账相加。判官token和可归因费用未被官方产物完整提供，因此没有伪造判官金额或实际总账。本次只可确认记录账未触及$50软顶/$60硬顶；不能据此声称已完整测得真实总成本。

过半136个session时记录账$4.306806，构建外推$8.613611，低于保留的$45构建停止线；最终记录构建${build['recorded_build_usd']:.6f}。预算与重试仅用于运行基础设施，没有依据中间答案改变实验内容。

## 耗时、三段停顿与编排者重启

| 阶段 | 启动次数 | 总经过分钟 | 活跃进程分钟 | 停顿分钟 | UTC开始 | UTC结束 |
|---|---:|---:|---:|---:|---|---|
{chr(10).join(timing_rows)}

| 停顿/恢复事件 | 分钟 | UTC退出或最后观测 | UTC恢复 |
|---|---:|---|---|
{chr(10).join(pause_rows)}

前两段暂停按pipeline退出至下一次启动计量。Codex精确退出时刻未单独落盘，只有用户报告的15:28Z中断，以及最后完成答案15:28:03.906986Z；至编排者重启15:29:31.580842Z的87.673856秒只作为停顿上界，因此答题活跃时间给区间。编排者重启是恢复端点，不再重复加一段停顿。原编排者披露时间中的“.6N”格式瑕疵保留原文，重启时刻取结构化PHASE_START事件。

活跃进程时间含容器起停、队列处理和退避，不等于模型推理时间；HTTP402最早在10:57出现，至11:01:58退出前的失败重试包含在活跃时间中。答题单题墙时中位数{statistics.median(latency):.2f}s、P95 {latency[int(.95*(len(latency)-1))]:.2f}s；这是已持久化作答的统计，未落盘请求不在其中，并发下也不能把单题耗时总和当墙时。

第一次在118个checkpoint处因错误采用共享key差额而停止。维护者裁定“不用管 key，余额够的”，只授权预算guard改用自身job/answer token账；原哈希保留，软/硬顶及$45构建预留线保留。第二次在213个checkpoint处发生OpenRouter HTTP402，是提供方资金中断；充值后原样续跑。16个HTTP402失败job全部保留为历史记录，并由框架正常重试路径解决；未直接编辑job状态或库内容。两次构建恢复均未重建完成单元。见 [预算修订核验](results/budget-refreeze-audit.json)、[提供方恢复核验](results/provider-recovery-verified.json)。

第三次是Codex账户用量上限切断执行会话及其承载的进程。编排者（Claude）在801份原子答案处用未修改的pipeline.py重启，只做基础设施恢复；本执行者恢复后核验PID与冻结哈希并仅监测，没有另起pipeline或触碰运行中的任务。最终1,382个完成答题事件对应1,382个唯一ID，没有重复完成事件。脚本内ANSWER_RETRY为0不等于中断前的在飞请求从未重发。阶段C仍由本执行者完成。见 [Codex恢复核验](results/codex-restart-audit.json)。

其他预执行偏差也已披露：uv依赖初次缺yaml后用all-packages安装；十首session输出截断后只重读允许窗口；首次后台启动被工具回收，未产生构建/付费调用；冻结修订A在执行前封闭原始日志泄漏面。这些不构成有完成单元后的额外停顿。

## 演进、质询与silent核验

最终272份来源、{build['documents']}份正本文档、{build['claims']}条claims。以下均来自只读计数，详见build-record的post-score-audit文件。

| 指标 | 数值 |
|---|---:|
| evolve step完成 | {evolve_steps} |
| 其中尾部强制 | {forced} |
| evolve状态分布 | {json.dumps(dict(evolve),ensure_ascii=False)} |
| 产生proposal的任务 | {sum(a['evolve_proposals'] for a in audits)} |
| evolve_adopt jobs | {sum(a['job_counts'].get('evolve_adopt',0) for a in audits)} |
| challenge jobs | {len(challenge)} |
| challenge轮数合计 | {sum(c['rounds'] for c in challenge)} |
| 盲问数 | {sum(c['questions'] for c in challenge)} |
| 报告缺口数 | {sum(c['gaps'] for c in challenge)} |
| 入队补偿次数 | {sum(c['compensation_enqueued'] for c in challenge)} |
| degraded审计数 | {sum(c['degraded'] for c in challenge)} |
| 未解析detail数 | {sum(not c['detail_parsed'] for c in challenge)} |
| 历史失败job（已解决） | {sum(a['historical_failed_jobs'] for a in audits)} |
| 最终pending / unresolved | 0 / 0 |
| consultation记录 / business记录 | {sum(a['consultation_records'] for a in audits)} / {sum(a['business_consultation_records'] for a in audits)} |
| 答题重试次数 | {retries} |
| 空字符串作答 | {sum(not r['predicted_answer'].strip() for r in rows)} |

“严格·演进”表示按冻结规则运行演进与程序化采纳政策，不保证模型一定提出或采纳结构变化。质询产生缺口/补偿也不是覆盖充分或得分提高的证明；成功job数不代表每次审计都完整，degraded单列。历史失败job共20个，其中16个为HTTP402，其余4个属于已解决的其他历史失败；没有删去失败记录，也不把队列最终清零写成从未失败。

## 错题抽样与复盘

抽样方法：{analysis['method']}。只记录qa_id、错误现象和抽象分析，不把题面、金标或证据内容写入仓库。样本用于解释失败形态，不估计各形态总体占比。

| qa_id | category | 分类 | 观察 |
|---|---|---|---|
{chr(10).join(error_rows)}

这些观察比较官方判分产物中的作答与判定。答题时未保存完整检索轨迹，不能仅凭最终错误区分“没编入”“没召回”或“答案模型没用好”；没有事后重答来改分。

### 赌对 / 赌错 / 未证实

{chr(10).join('- '+x for x in analysis['takeaways'])}

{analysis['conclusion']}

## 现场入口

[predictions](results/predictions.jsonl)只含qa_id和本系统作答；[剥离版判分](results/scored-stripped.jsonl)不含题面/金标/证据字段；[官方汇总](results/official-summary.json)原样保留；[数值附表](results/metrics-tables.md)、[逐session记录](build-record/session-progress.csv)和[冻结清单](FROZEN.md)支持逐文件核验。原始数据、材料、应用、日志和凭据均git忽略。阶段C使用 `post_score_audit.py`、`report_metrics.py`、`final_report.py`，其中错题分析为明确标注的人工判读。

当前现场的幂等入口为 `repo/.venv/bin/python scripts/pipeline.py`；已完成阶段和单元会跳过。异地重现需同一框架/数据集提交、冻结契约与角色配置、相应依赖及独立scaffold资源；随机端口/路径属于环境，不把恢复标记当作可移植数据库备份。凭据由拥有者在忽略目录提供。重新运行模型或判官不保证逐字相同。
'''
    (ROOT / 'RUN-REPORT.md').write_text(text)
    print(json.dumps({'report_written': True, 'official': scores['official'], 'own_recorded_usd': own}))


if __name__ == '__main__':
    main()
