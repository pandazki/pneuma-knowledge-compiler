# Truth-set rigor audit — aggregate

cases audited: 84 / 84
verdicts: fix 51, sound 33
issues by severity: blocking 59, material 41

| severity | kind | n |
|---|---|---|
| blocking | ambiguous_question | 14 |
| blocking | temporal_ambiguity | 11 |
| blocking | facet_superseded | 8 |
| blocking | missing_core | 6 |
| blocking | over_narrow_core | 6 |
| blocking | compound_facet | 5 |
| blocking | wrong_tag | 4 |
| blocking | facet_not_entailed | 3 |
| blocking | probe_basis_wrong | 2 |
| material | compound_facet | 20 |
| material | quote_mismatch | 7 |
| material | ambiguous_question | 4 |
| material | facet_not_entailed | 3 |
| material | probe_basis_wrong | 3 |
| material | facet_superseded | 2 |
| material | premise_not_false | 1 |
| material | temporal_ambiguity | 1 |

## Cases needing a decision (fix / unsure), most severe first

### aggregate-01 — fix
- **blocking / ambiguous_question** (aggregate-01): 问题没有限定只统计具名商家。语料还出现了未具名的“修车店”“维修点”，并明确说林舟在比较“两家报价”，却没有把这些泛称或另一家报价方与三个具名商家建立身份对应。因此，总商家数可能是三家，也可能更多，语料无法唯一确定。
  - `2026-03-12-3-月-12-日日页.md`: “修车店来电提醒该做常规保养，问周末能否留车。”
  - `2026-03-14-不去饭局后的家务.md`: “明天再比维修点报价，今晚不算哪家便宜。”
  - `2026-03-15-保养报价中的基础项目.md`: “我现在只是把两家报价并排看”
  - proposed: 将 question 改为：“这批材料里明确写出名称的汽车保养商家一共有几家？分别是哪几家？不计仅以‘修车店’‘维修点’‘店里’等泛称出现、且无法与具名商家建立身份对应的记录。”
- **blocking / wrong_tag** (aggregate-01-d): “一共几家”是问题明确要求回答的内容，不能标为永不导致失败的 detail。当前规则会让声称“四家”但提到三个预期名称的错误答案通过全部 core facets。该计数还应由三个具名商家的证据共同支撑。
  - `2026-03-15-保养报价中的基础项目.md`: “北巷保养咨询”
  - `2026-03-31-今日取车未能交付.md`: “桥桥保养站”
  - `2026-04-09-保养取车窗口调整.md`: “常青养护”
  - proposed: 在采用修订后问题的前提下，将 aggregate-01-d 改为：{"facet_id":"aggregate-01-d","tag":"core","text":"明确具名的商家一共三家","evidence":[{"corpus_file":"2026-03-15-保养报价中的基础项目.md","quote":"北巷保养咨询"},{"corpus_file":"2026-03-31-今日取车未能交付.md","quote":"桥桥保养站"},{"corpus_file":"2026-04-09-保养取车窗口调整.md","quote":"常青养护"}]}
- notes: 三个名称的现有 evidence.quote 均为对应文件中的逐字子串；全语料搜索未发现其他明确具名的汽车保养商家，也未发现后来对这三个名称的更正或取代。OWNER_DIALOGUE literal 已检查，与本案无关。

### aggregate-02 — fix
- **blocking / ambiguous_question** (aggregate-02): “实际执行”没有说明是指触发具体删除请求并实施删除动作，还是也包括已经发生的内部演练查看。语料一方面记载内部演练已经查看三个位置、内部查看确已发生；另一方面又把这些活动定性为“演练前的问答准备”。因此“零次实际删除处理”和“一次内部演练/查看”都是可辩护的理解，当前零次 core 会把后一种谨慎回答判错。
  - `2026-05-16-删除演练-留给业务方的确认栏.md`: “这页只登记内部演练已经查看的三个位置：选定材料的记录页、来源跳转的观察项和状态旁的回复位置。”
  - `2026-05-16-删除演练-留给业务方的确认栏.md`: “内部观察页按实际顺序保留发起时间、查看位置和未解问题。”
  - `2026-05-16-删除演练-留给业务方的确认栏.md`: “它只是演练前的问答准备：内部查看可以存在，业务侧结论尚不存在。”
  - `2026-05-24-周期结束时的待办状态.md`: “删除演练我还在看范围和回告格，暂时没有一格可以确认。”
  - proposed: 将 question 改为：“截至2026-05-24周期结束，删除演练进入过几次实际删除处理阶段（这里指具体删除请求已经到达并触发删除动作；仅内部查看和确认栏准备不计）？”将 aggregate-02-a.text 改为：“进入实际删除处理阶段的次数为零次。”其证据应改引 2026-05-16 的“没有具体删除请求到达时，清单不会生成处理完成时间，也不会预填申请人或项目范围。它只是演练前的问答准备：内部查看可以存在，业务侧结论尚不存在。”并保留 2026-05-24 的周期末状态。
- notes: 两条原 case 引文均逐字匹配。detail facet 的见证人陈述未发现后续明确取代。OWNER_DIALOGUE literal 也已完整检查；其最新陈述仅确认删除演练仍未获采购答复，未消除“内部查看是否算实际执行”的歧义。

### aggregate-03 — fix
- **blocking / temporal_ambiguity** (aggregate-03): 问题没有指定截止日期，也没有询问“当前/现在”的最新状态。七个账号和两条完整首链都是截至2026年5月10日的快照；语料还明确说截止时未完成并非最终失败，之后也没有给出该邀请批次的最终汇总。因此“7人、2人”只能作为截至5月10日的答案，不能作为无时间边界的最终结果。
  - `2026-05-10-首次成功失败路径核对.md`: “截至今天，那七个账号里只有两个人留下了完整的首条链记录。”
  - `2026-05-10-账号到达与首次成功的计数边界.md`: “这页不计算增长趋势，不比较不存在的前一批，也不把截止时尚未完成写成最终失败。”
  - proposed: 截至2026年5月10日，5月5日发出的十二份小范围邀请中，有几位受邀对象建立了账号，其中几位留下了完整的首条链记录？
- notes: 两个facet的引文均为对应文件中的逐字子串，facet文本由上下文蕴含、均为单一命题，且都应标为core。全语料检索未发现后来明确改写7/2的同批次汇总，但也未找到该批次的最终截止统计；后续出现的“两条链”是预算调整链与材料替代链，不是受邀账号首链计数。

### aggregate-06 — fix
- **blocking / missing_core** (aggregate-06): 问题明确询问“分成几类”，但没有 core facet 要求答案说明总数是三类。仅陈述现有三项后再错误声称还有第四类，也会满足当前全部 core facets。
  - `2026-04-14-名称匹配决策日志（事故后）.md`: “输出分为可回到原位置、需人工确认、字段不足三类。”
  - proposed: 新增 core facet：事故重放的九条输入最后分为三类。
- **blocking / compound_facet** (aggregate-06-b): 该 facet 合并了两个可独立判断的命题：三条输入只提供相同短名，以及三条输入进入人工确认清单。问题只要求类别和数量；答案“三条需人工确认”已正确回答，却不蕴含其短名原因，可能被误判为遗漏。
  - `2026-04-14-受影响导入段重放记录.md`: “三条只给出相同短名，进入人工确认清单”
  - `2026-04-14-名称匹配决策日志（事故后）.md`: “输出分为可回到原位置、需人工确认、字段不足三类。”
  - proposed: 将 core facet 改为“三条需人工确认”；如需保留原因，另设 detail facet：“三条只给出相同短名”。
- **blocking / compound_facet** (aggregate-06-c): 该 facet 合并了“缺少可比较字段”和“保持阻断”两个命题。类别本身是字段不足；保持阻断是其处理结果。正确答案“两条字段不足”不必同时陈述处理状态。
  - `2026-04-14-受影响导入段重放记录.md`: “两条缺少可比较字段，保持阻断”
  - `2026-04-14-名称匹配决策日志（事故后）.md`: “输出分为可回到原位置、需人工确认、字段不足三类。”
  - proposed: 将 core facet 改为“两条字段不足”；如需保留处理结果，另设 detail facet：“两条保持阻断”。
- notes: 所有现有 evidence quote 均为指定文件中的逐字子串。全 corpus 检索未发现晚于 2026-04-14 的文件更改九条输入的 4/3/2 分类；2026-09-01 的 OWNER_DIALOGUE 仅更新尾款状态，与本案无关。

### aggregate-08 — fix
- **blocking / ambiguous_question** (aggregate-08): “填好了”没有被定义。表中六格的候选状态非空，但其中两个“只记了角色”、四个只有可能对象或备选，而且所有非空格仍注明缺项；因此可合理理解为六格非空、四格已有候选人，或零格完全完成。
  - `2026-05-03-十二个邀请槽位-未完成工作台.md`: “当前状态：名单未完成，邀请文字未完成，未执行发出动作。”
  - `2026-05-03-十二个邀请槽位-未完成工作台.md`: “| 05 | 曾指出摘要越界的人 | 只记了角色 | 对象本人确认 |”
  - `2026-05-03-十二个邀请槽位-未完成工作台.md`: “| 06 | 会追问证据位置的人 | 有两位备选 | 二选一的依据 |”
  - `2026-05-03-十二个邀请槽位-未完成工作台.md`: “- [ ] 十二个槽位都对应到具体且合适的人”
  - proposed: 将 question 改为：“5 月 3 日那张工作台中，十二个邀请槽位的‘候选状态’栏有几个非空、有几个标为‘空’？”
- **blocking / missing_core** (aggregate-08): 问题要求两个数量，但唯一的 core facet 只覆盖空槽位数量；非空数量仅能从三个 detail facets 推得。由于 detail 永不决定通过与否，漏答非空数量的答案仍会通过。
  - `2026-05-03-十二个邀请槽位-未完成工作台.md`: “| 01 | 做项目交接的人 | 有一位可能对象 | 联系许可、近期是否方便 |”
  - `2026-05-03-十二个邀请槽位-未完成工作台.md`: “| 03 | 负责内部流程的人 | 有一位可能对象 | 是否能看状态样例 |”
  - `2026-05-03-十二个邀请槽位-未完成工作台.md`: “| 05 | 曾指出摘要越界的人 | 只记了角色 | 对象本人确认 |”
  - `2026-05-03-十二个邀请槽位-未完成工作台.md`: “| 06 | 会追问证据位置的人 | 有两位备选 | 二选一的依据 |”
  - `2026-05-03-十二个邀请槽位-未完成工作台.md`: “| 08 | 需要交接旧资料的人 | 只记了角色 | 联系许可 |”
  - `2026-05-03-十二个邀请槽位-未完成工作台.md`: “| 10 | 习惯从原句复核的人 | 有一位可能对象 | 是否愿意参加 |”
  - proposed: 新增 core facet：{"facet_id":"aggregate-08-f","tag":"core","text":"候选状态非空的槽位有六个"}，并以 01、03、05、06、08、10 的六行表格为证据。
- **blocking / over_narrow_core** (aggregate-08-a): 问题只问空槽位有几个，没有问哪些槽位；core facet 额外要求答出六个编号，会让只回答正确数量的答案被判遗漏。
  - `2026-05-03-十二个邀请槽位-未完成工作台.md`: “下一次先补 02、04、07、09、11、12 的人选理由”
  - proposed: 将 aggregate-08-a 的 text 改为“候选状态标为‘空’的槽位有六个”。如需保留编号，另增 detail facet：“候选状态标为‘空’的是 02、04、07、09、11、12。”
- notes: 所有现有 evidence quote 均为命名文件中的逐字子串。5 月 5 日的材料记录了之后向十二人发信，但问题明确固定在 5 月 3 日，因此不构成 facet_superseded。

### calendar-02 — fix
- **blocking / ambiguous_question** (calendar-02): “这算把问题修好了吗”没有说明“问题”是项目列表的跨日显示问题，还是尚未验证的时区/数据层问题。前者已有修复：列表改用来源开始时间后，该记录回到 3 月 31 日；后者则不能据此认定已修复。因此“算修好”和“不算时区修复”都是可辩护答案，而现有 core facet 强制选择后者。
  - `2026-04-02-林舟-贾宁.md`: “我先把项目列表改成按来源开始时间排，跨日那条已经回到 3 月 31 日。”
  - `2026-04-02-林舟-贾宁.md`: “测试先留着，但别把它叫时区修复。你的历史夹具坏了，本身就是现在不能判断数据层的原因。”
  - proposed: 将问题改为：“到 4 月 2 日为止，那条跨日记录在项目列表中回到哪一天了？这能算时区修复吗？”
- **blocking / facet_not_entailed** (calendar-02-b): “这不算把问题修好”过于宽泛。语料只确定不能把这次列表改动称作“时区修复”，且当时不能判断数据层；它同时明确项目列表排序已经完成，记录也已回到正确日期。
  - `2026-04-02-林舟-贾宁.md`: “那只能说明这个样本的页面读错列。”
  - `2026-04-02-林舟-贾宁.md`: “记了。今天实际完成的是列表排序和两条新测试；历史回放、附件地址、名称候选都没查完。”
  - proposed: 将 calendar-02-b 的 text 改为：“这不能算时区修复”。
- **material / compound_facet** (calendar-02-c): 该 facet 同时断言“改的只是显示层”和“不能称为时区修复”，是两个可分别判断的命题；其中后半又与修正后的 core facet 重复。
  - `2026-04-02-林舟-贾宁.md`: “我先把项目列表改成按来源开始时间排，跨日那条已经回到 3 月 31 日。”
  - `2026-04-02-林舟-贾宁.md`: “测试先留着，但别把它叫时区修复。”
  - proposed: 删除 calendar-02-c；“不能算时区修复”由修正后的 calendar-02-b 表达，列表改动方式已由 calendar-02-d 表达。并将 calendar-02-d 的 text 顺手改为更通顺的单一命题：“项目列表被改成按来源开始时间排序”。
- notes: 现有各 evidence.quote 均为命名文件中的逐字子串。calendar-02-a 和 calendar-02-d 的事实内容成立；固定到 4 月 2 日也消除了后续状态变更问题。OWNER_DIALOGUE literal 已核查，没有涉及该跨日记录或时区修复。

### calendar-05 — fix
- **blocking / temporal_ambiguity** (calendar-05-a): “二十四天（4 月 3 日到 4 月 27 日）”把 4 月 3 日的记录日期当成了邮件被找到的日期，但该记录明确说邮件是“昨晚”找到的，即 4 月 2 日晚，且没有给出准确时间。与此同时，4 月 3 日另有一次归档检索命中。因此“找到”可指实际发现、4 月 3 日的报告记录或归档检索；按记录日期是 24 天，按实际自然日是 25 天，精确经过时长则无法确定。当前 core facet 会把基于实际发生时间的正确回答判错。
  - `2026-04-03-找到-客厅预算调整邮件.md`: “昨晚按旧项目名重新搜，找到了我一直说的那封改预算邮件。”
  - `2026-04-03-归档检索作业-0403-2-完成.md`: “检索范围：云麓只读邮件归档；关键词：预算更新表 v3；命中：1 封邮件。”
  - `2026-04-27-材料替代-现场会位置请确认.md`: “这个位置可以作为现有链的材料之一。”
  - proposed: question 改为：“按两份记录的日期计算：从 4 月 3 日的《找到：客厅预算调整邮件》记录，到 4 月 27 日吴岚确认现场会位置可用，中间相隔多久？”；facet text 改为：“相隔二十四天（4 月 3 日到 4 月 27 日，约三周半）”。
- notes: 两条原始 evidence quote 均为对应文件中的精确子串。后续材料没有撤回 4 月 27 日的位置确认；OWNER_DIALOGUE 与本事件无关。

### chain-01 — fix
- **blocking / temporal_ambiguity** (chain-01): 问题未限定日期，也未说“当前/现在”。2026-04-27 的记录确实给出题设四个节点，但后续语料把“第一条”明确称为预算调整链，并把材料替代链称为“第二条”。因此，回答四月的四节点或后来的第一条预算链，均有语料依据；当前问题会把一种合理答案判错。
  - `my-data/2026-04-27-第一条记录链-编排状态，不请验收.md`: “我把第一条记录链排成了一个尚未完成的工作序列：原始变更提出、现场会的口头确认位置、失效附件的说明、以及仍待比较的颜色样和预算差异。”
  - `my-data/2026-05-13-采购阅读版-第一条链导出修订.md`: “本页的对象是已能回源的第一条预算调整记录。”
  - `my-data/2026-05-18-材料替代链的最后状态.md`: “第一条预算链之前已能回源，第二条现在也有它自己的来源和确认；两条的状态不要合成一个总的通过标记。”
  - proposed: 将问题改为：“在 2026 年 4 月 27 日 17:06 的《第一条记录链：编排状态，不请验收》中，林舟所说的第一条记录链由哪几个节点组成？”
- **blocking / facet_superseded** (chain-01): 四个 core facet 共同描述的是 2026-04-27 当时的第一条链编排；后续语料已把第一条定为预算调整链、材料替代链定为第二条。问题不固定 2026-04-27 时，不能继续把这组历史节点当作无时间限定的唯一真值。
  - `my-data/2026-05-13-采购阅读版-第一条链导出修订.md`: “修订后的首列写作“预算调整记录”，并在同一行给出三个明确的阅读入口：最初提出的邮件、说明执行范围的现场会位置、以及由陈放留存的当前状态。”
  - `my-data/2026-05-13-采购阅读版-第一条链导出修订.md`: “第二条材料替代链仍不在这一页中，尚无由本页推出的验收或开始时限。”
  - proposed: 采用上述带日期和记录标题的问题；在该历史限定下，现有四个 facet 可原样保留。
- notes: 题设中的五处 evidence quote 均为所列 2026-04-27 文件的逐字子串；四个 facet 在限定该记录时均受语料支持且 core 标记合适。OWNER_DIALOGUE 仅更新尾款状态，与记录链节点无关。

### chain-03 — fix
- **blocking / temporal_ambiguity** (chain-03): 问题没有指定时间点，但预期答案描述的是 2026-04-24 的历史快照。至少第一处缺口在 2026-04-27 已被明确补上，之后 2026-05-18 又记录第二条材料替代链已有自己的来源和确认。因此，无日期的问题不能无歧义地要求这两个旧缺口。证据项中的 as_of 不能替问题本身限定时间。
  - `2026-04-24-材料替代链-仍待核对的两个位置.md`: “中间那条现场确认还是只剩转写里的时间点”
  - `2026-04-27-材料替代-现场会位置请确认.md`: “这只能补“当时有口头确认”的缺口，不能把颜色样已经通过、预算差异已经结清，或附件已经恢复写进去。”
  - `2026-05-18-材料替代链的最后状态.md`: “第一条预算链之前已能回源，第二条现在也有它自己的来源和确认；两条的状态不要合成一个总的通过标记。”
  - proposed: 将 question 改为：「截至 2026 年 4 月 24 日，材料替代链上哪两处仍未核对清楚？」
- **blocking / facet_superseded** (chain-03-a): 该 facet 在 2026-04-24 成立，但 2026-04-27 已找到可复看的现场会记录、说话内容和 10:36 左右的时间位置，并明确称其补上了口头确认缺口。无历史日期限定时，要求答案仍说“只剩转写里的时间点”会把符合最新状态的答案判错。
  - `2026-04-27-材料替代-现场会位置请确认.md`: “我翻到现场会记录了。原来那份材料附件现在打不开，但会议里有人问能不能把原计划的板材换成另一种，吴岚当时说可以按替代材料继续，前提是把颜色样和预算差异留在项目记录。那句话在会议记录的 10:36 附近，不在失效附件里。”
  - `2026-04-27-材料替代-现场会位置请确认.md`: “这只能补“当时有口头确认”的缺口，不能把颜色样已经通过、预算差异已经结清，或附件已经恢复写进去。”
  - proposed: 将问题限定为历史时点：「截至 2026 年 4 月 24 日，材料替代链上哪两处仍未核对清楚？」限定后可保留 chain-03-a。
- notes: 两条 facet 的 evidence.quote 以及顶层 evidence.quote 均为命名文件中的逐字子串。若问题限定到 2026-04-24，两条 facet 都由当日文件支持、均是问题所问的核心缺口，且各自是单一 proposition。

### chain-06 — fix
- **blocking / temporal_ambiguity** (chain-06): 问题没有限定截止时间。4 月 12 日的事故说明明确只陈述截至当日 15:00 的状态，但 5 月 15 日又记录了通过简化入口进行的新导入。因此，“又恢复了哪一个”既可理解为截至 4 月 12 日只恢复受限只读，也可理解为询问整个语料期内的恢复情况；顶层 evidence 的 as_of 不能替问题本身限定时间。
  - `2026-04-12-事故说明-同姓记录错误关联与当前处置.md`: “现发送本次错误关联的书面说明，范围截至 4 月 12 日 15:00。”
  - `2026-05-15-材料替代记录-导入结果与待确认项.md`: “按今天简化后的入口，我把材料替代这条记录导入了内部试用区。”
  - proposed: 将问题改为：“截至 2026 年 4 月 12 日 15:00，同姓记录错误关联事故中，4 月 7 日起哪些控制保持暂停，4 月 11 日只恢复了哪条查看路径？”
- **blocking / facet_superseded** (chain-06-a): 在没有问题截止时间的情况下，“新导入……保持暂停”不是最新语料状态；5 月 15 日已有一条材料经简化入口完成导入。该 facet 只能作为截至 4 月 12 日的状态成立。
  - `2026-04-12-事故说明-同姓记录错误关联与当前处置.md`: “4 月 7 日起，关系写入、新导入、候选自动应用和既有分享入口保持暂停”
  - `2026-05-15-材料替代记录-导入结果与待确认项.md`: “材料是我下午那段，来源位置也是我从页面里选的那一个，导入本身没有问题。”
  - proposed: 在问题中加入“截至 2026 年 4 月 12 日 15:00”，并将该状态限定为该截止时点。
- **blocking / missing_core** (chain-06): 按原问题“停了哪些入口”的历史事件口径，4 月 7 日停止接收操作的“手工确认入口”也是必答项，却没有任何 core facet 捕捉。语料还明确区分手工确认与候选自动应用：4 月 11 日允许执行临时人工确认时，自动应用仍继续停。
  - `2026-04-07-受限视图错误关联影响清单.md`: “关系写入、手工确认入口和新的导入均停止接收操作；分享入口保留原记录，但只返回暂停提示。”
  - `2026-04-11-受限只读恢复协调.md`: “按这个条件执行临时人工确认，自动应用继续停。”
  - proposed: 采用限定状态而非罗列全部历史停用动作的问题：“截至 2026 年 4 月 12 日 15:00，同姓记录错误关联事故中，4 月 7 日起哪些控制保持暂停，4 月 11 日只恢复了哪条查看路径？”
- **blocking / over_narrow_core** (chain-06-a): 原问题只问停了哪些入口及恢复哪一个，没有要求给出精确起始日期；但 core facet 强制要求“4 月 7 日起”。完整列出所有入口和恢复项却未说日期的答案仍然回答了原问题，却无法蕴含该 facet。
  - `2026-04-12-事故说明-同姓记录错误关联与当前处置.md`: “4 月 7 日起，关系写入、新导入、候选自动应用和既有分享入口保持暂停”
  - proposed: 要保留日期为 core 要求，应把问题改为：“截至 2026 年 4 月 12 日 15:00，同姓记录错误关联事故中，4 月 7 日起哪些控制保持暂停，4 月 11 日只恢复了哪条查看路径？”
- **material / compound_facet** (chain-06-a): 该 facet 合并了四个可分别 stated/omitted/contradicted 的暂停事实，不符合单一命题要求。
  - `2026-04-12-事故说明-同姓记录错误关联与当前处置.md`: “4 月 7 日起，关系写入、新导入、候选自动应用和既有分享入口保持暂停”
  - proposed: 拆成四个 core facet：“4 月 7 日起关系写入保持暂停”；“4 月 7 日起新导入保持暂停”；“4 月 7 日起候选自动应用保持暂停”；“4 月 7 日起既有分享入口保持暂停”。
- **material / compound_facet** (chain-06-d): 该 detail facet 合并了写入、导入和原分享链接三个分别可判定的未恢复事实。
  - `2026-04-11-受限只读恢复协调.md`: “不恢复写入、导入或原分享链接”
  - proposed: 拆成三个 detail facet：“写入没有随受限只读恢复”；“导入没有随受限只读恢复”；“原分享链接没有随受限只读恢复”。
- notes: 所有给定 evidence quote 及顶层 quote 均已核为对应文件中的逐字子串。OWNER_DIALOGUE 只更新尾款状态，不改变本事故的入口状态。

### chain-08 — fix
- **blocking / temporal_ambiguity** (chain-08): 问题没有限定时间。2026-04-03 时第二条变更尚未找到，但 2026-05-18 已有自己的来源和确认，因此“没有找到”和“找到了”分别在不同时间成立。证据中的 as_of 不会替问题建立时间限定。
  - `2026-04-03-现场会定位-只到样板之后.md`: “第二条变更更没有找到”
  - `2026-05-18-材料替代链的最后状态.md`: “第一条预算链之前已能回源，第二条现在也有它自己的来源和确认；两条的状态不要合成一个总的通过标记。”
  - proposed: 将 question 改为“截至2026年4月3日，云麓试点的第二条（材料替代）变更找到了吗？”，并保留 core facet“没有找到”。
- **blocking / facet_superseded** (chain-08-a): “没有找到”只是在 2026-04-03 成立；后续语料明确记录第二条已有自己的来源和确认。未经日期限定时，该 facet 已被后续状态取代。
  - `2026-04-03-现场会定位-只到样板之后.md`: “今天能整理出的只是三份来源各自的边界：邮件说明调整被发出，现场定位提示录制里可能有数量讨论，消息提示你纠正过某个表述。它们还没有组成完整变更链，第二条变更更没有找到。历史回放也继续留在未完成。”
  - `2026-05-18-材料替代链的最后状态.md`: “第一条预算链之前已能回源，第二条现在也有它自己的来源和确认；两条的状态不要合成一个总的通过标记。”
  - `2026-05-20-阶段复盘后的条件核对.md`: “昨天我说它对两条变更记录有用，意思是有人能把材料、确认和当前状态重新找回来。”
  - proposed: 采用历史时间点版本：question 写为“截至2026年4月3日，云麓试点的第二条（材料替代）变更找到了吗？”，facet text 保持“没有找到”。若要测试最新状态，则应将问题写为“目前云麓试点的第二条（材料替代）变更找到了吗？”并将 core facet 改为“找到了，已有自己的来源和确认”。
- notes: 原引文与命名文件逐字匹配，且 facet 本身是单一命题；问题仅在于未限定日期并忽略了后续状态。OWNER_DIALOGUE 未改变这条变更链的状态。

### chain-separation — fix
- **blocking / probe_basis_wrong** (chain-separation): The quoted sentence is verbatim and establishes only that the two chains must not share one aggregate pass status. It does not require separate canonical documents. The corpus explicitly permits the two chains to appear side by side while retaining separate provenance and questions. Therefore a faithful library could place both marker sets in one document and be incorrectly rejected by this distinct_documents probe.
  - `my-data/2026-05-18-材料替代链的最后状态.md`: “两条的状态不要合成一个总的通过标记”
  - `my-data/2026-05-18-午后复盘卡片.md`: “两行可以并排，但各自的问题仍各自回去找。”
  - `my-data/2026-03-21-云麓来源映射读取说明.md`: “预算变更与材料替代是两个独立入口。”
  - proposed: Remove this distinct_documents probe. If the probe framework can test separation within one document, replace it with a rule whose note says: “预算变更与材料替代是两个独立入口；它们可以在同一页或同一卡片中并排，但必须各自保留来源、确认与状态，且不得把两条链的状态合成一个总的通过标记。该规则不要求 A、B 侧记号由不同 canonical 文档承载。” Otherwise, delete the case rather than testing document-level separation.
- notes: The OWNER_DIALOGUE literal was inspected; it concerns the later tail-payment state and does not modify this rule. Later corpus material preserves separate chain-level provenance/status but does not impose separate-document storage.

### definition-01 — fix
- **blocking / temporal_ambiguity** (definition-01): 问题没有给出日期，也没有使用“当前/现在”。但 Seamlog 的定位随时间发生了明确变化：早期构想是自动生成周报的总时间线，之后自动周报被移出试点，最新方向才收窄为小型设计团队的变更证据链。原问题允许对不同历史阶段作答，而现有 facets 只接受最新阶段。
  - `2026-03-03-林舟-贾宁.md`: “林舟: 我把东西临时叫 Seamlog。现在脑子里是一张总时间线：会里一句、消息里一句、邮件里一句，最后自动吐出周报。看着会很像有答案。”
  - `2026-03-13-范围会前的一屏说明.md`: “林舟: 删的是自动周报：它移出试点目标。全项目看板也不顺带进入。我现在只保留一个要验证的问题——发生争议时，能不能沿着一条记录找回原话和后来的判断。”
  - `2026-05-22-下一周期候选-继续、停止、延后.md`: “把候选分成三栏，不是为了给每一栏都找一个好消息。继续栏只留“小型设计团队的变更证据链”：让人回到材料、确认和当前状态的原处。它仍是一个窄场景的工作假设，不是对所有项目流程的接管。”
  - proposed: 将 question 改为：“截至 2026-05-24，Seamlog 当前的下一周期工作假设是什么？”
- **material / compound_facet** (definition-01-a): 该 facet 同时要求两个可分别判断的命题：Seamlog 做变更证据链，以及它面向小型设计团队。回答只陈述其中一项时，当前 facet 无法作原子化判定；同时，“做的是”还弱化了原文明确保留的“工作假设”限定。
  - `2026-05-22-下一周期候选-继续、停止、延后.md`: “继续栏只留“小型设计团队的变更证据链””
  - `2026-05-22-下一周期候选-继续、停止、延后.md`: “它仍是一个窄场景的工作假设，不是对所有项目流程的接管。”
  - proposed: 将 definition-01-a 拆为两个 core facets：definition-01-a：“Seamlog 当前的下一周期工作假设是变更证据链”；definition-01-e：“该工作假设面向小型设计团队”。两者均可引用“继续栏只留“小型设计团队的变更证据链””。
- notes: 所有 facet 和顶层 evidence 的 quote 均为对应文件中的逐字子串。5 月 22 日之后的输入没有撤回小型设计团队变更证据链这一方向；2026-09-01 的 OWNER_DIALOGUE 仅更新尾款状态，没有改变产品方向。

### definition-02 — fix
- **blocking / ambiguous_question** (definition-02): “它们之间发生过什么”没有限定要回答事故的原因、可见影响还是后续修正。语料明确记录了三个不同层次：同姓候选导致错误关联、云麓视图出现澄湾摘要、之后来源被分开并恢复受限只读。当前唯一的事件类 core facet只接受第二层；回答“两个项目的业主来源被错误写入同一关系”虽足以回答原问题，却会因未陈述“两条现场摘要”而被判错。
  - `my-data/2026-04-12-事故说明-同姓记录错误关联与当前处置.md`: “**影响。** 两份属于不同项目的业主来源因同姓候选被写入同一关系，云麓受限客户视图一度出现澄湾的两条现场摘要。”
  - `my-data/2026-04-11-受限只读恢复协调.md`: “吴岚: 我确认这两条错误归并的更正结果。允许恢复云麓授权试点账号的受限只读查看，仅限现有项目；不恢复写入、导入或原分享链接。执行后把三类账号结果留档。”
  - proposed: 将 question 改为：“云麓和澄湾分别是什么？在同姓记录错误关联事故中，云麓受限客户视图曾出现什么跨项目内容？”
- **material / compound_facet** (definition-02-e): 该 detail facet同时断言项目不同和房号不同，是两个可分别判断的命题；其中项目不同又已由 definition-02-c 覆盖。
  - `my-data/2026-04-05-同姓候选关系核对表.md`: “| 项目与房号 | 云麓 7 栋 1604 | 澄湾 3 栋 1202 | 项目和房号不同 |”
  - proposed: 将 definition-02-e 的 text 改为“两条业主记录的房号不同”；保留现有 evidence，项目不同继续由 definition-02-c 单独覆盖。
- notes: 五处 case evidence 引文均与指定文件逐字匹配。definition-02-d 是明确的历史事件陈述；后续修正没有使“曾出现”失真。2026-09-01 的 owner statement 只更新尾款状态，并继续使用“云麓受限试点”这一称呼，未改变本案实体关系。

### definition-04 — fix
- **blocking / ambiguous_question** (definition-04): “执行过”没有区分演练前的内部查看、实际删除动作和完成业务方确认。语料同时记载内部演练已查看三个位置，又明确称其为“演练前的问答准备”，并且到周期结束业务确认仍未完成；因此“执行过/没执行过”存在两种可辩护解释。
  - `2026-05-16-删除演练-留给业务方的确认栏.md`: “这页只登记内部演练已经查看的三个位置：选定材料的记录页、来源跳转的观察项和状态旁的回复位置。”
  - `2026-05-16-删除演练-留给业务方的确认栏.md`: “它只是演练前的问答准备：内部查看可以存在，业务侧结论尚不存在。”
  - `2026-05-24-周期结束时的待办状态.md`: “删除演练我还在看范围和回告格，暂时没有一格可以确认。”
  - proposed: 将 question 改为：“删除演练是什么？到周期结束时，内部查看和业务方确认分别处于什么状态？”
- **blocking / facet_superseded** (definition-04-b): 4 月 16 日“当前没有删除演练证据”只描述当时状态；5 月 16 日已出现带查看人和时间的内部演练查看记录。5 月 24 日只能证明业务确认未完成，不能证明“一次也没有执行过”。该绝对表述会把“内部查看已发生、业务确认未完成”的正确答案判错。
  - `2026-04-16-采购材料责任矩阵（未提交）.md`: “当前没有删除演练证据，也没有约定谁见证”
  - `2026-05-16-删除演练-留给业务方的确认栏.md`: “每行带内部查看人和时间；结果栏写“等待业务方确认”。”
  - `2026-05-24-未解项交接卡.md`: “内部查看记录仍可回到原处，但业务确认没有新来源”
  - `2026-05-24-周期结束时的待办状态.md`: “状态写得可以。我还没有签附录，也没有完成删除确认；尾款这边没有新日期。”
  - proposed: 将 definition-04-b 改为 core：“到周期结束时，删除演练的业务方确认尚未完成”。同时移除 expected_truth_ids 中带有“never-run”含义的 df-drill-never-run，改用表达“内部已查看、业务确认未完成”的 truth id。
- **blocking / wrong_tag** (definition-04-c): 内部查看已经发生，是回答执行进展不可缺少的事实；把它标为 detail 会允许“完全没有任何演练活动”的错误答案仅凭当前 b facet 通过。其现有文本还把“这页只登记”泛化成了“内部只登记”。
  - `2026-05-16-删除演练-留给业务方的确认栏.md`: “这页只登记内部演练已经查看的三个位置：选定材料的记录页、来源跳转的观察项和状态旁的回复位置。”
  - `2026-05-24-未解项交接卡.md`: “内部查看记录仍可回到原处，但业务确认没有新来源”
  - proposed: 将 definition-04-c 的 tag 改为 core，text 改为：“到周期结束时，内部演练已经查看过三个位置”。
- **material / compound_facet** (definition-04-g): 该 facet 同时陈述“内部查看可以存在”和“业务侧结论尚不存在”两个独立命题，违反单命题要求；两半又分别与 c、d 重叠，会重复计算 detail。
  - `2026-05-16-删除演练-留给业务方的确认栏.md`: “内部查看可以存在，业务侧结论尚不存在”
  - proposed: 删除 definition-04-g；其内部查看事实由修正后的 definition-04-c 覆盖，业务确认状态由修正后的 definition-04-b 覆盖。
- notes: 七条原始 evidence.quote 均为对应文件中的逐字子串。OWNER_DIALOGUE literal 也已核对：2026-09-01 仍称删除演练未获采购答复。问题并非时间点缺失，而是“执行”没有区分已经发生的内部查看与尚未完成的业务确认。

### definition-06 — fix
- **blocking / ambiguous_question** (definition-06): “指的是什么”既可合理理解为询问副本收录的内容，也可理解为询问其目的和只读行为。现有唯一 core 只覆盖前一种理解；回答“用于回查，不改原处、不接收补写”的读者会被判错，尽管该回答由语料直接支持。
  - `my-data/2026-03-21-云麓试点边界与只读副本清单.md`: “只读副本只收被三人选定的两类变更片段及其回查位置。原处不改写，副本不开放写入；没有被选入的相邻聊天、联系人和附件不因同属项目而自动进入。”
  - `my-data/2026-03-21-云麓来源映射读取说明.md`: “只读副本的目的只是方便回查：它不改原处、不接收补写，也不把未选材料变成默认候选。”
  - proposed: 将问题收窄并固定语境为：“根据 2026-03-21 已确认的边界，云麓试点的只读副本收哪些内容？”
- **blocking / missing_core** (definition-06-a): core 只说“两类变更”，没有指出两类是预算变更和材料替代。因而回答任意未命名的“两类变更片段”即可满足现有 facet，尽管没有给出语料所确定的类别。后续材料仍明确维持这两个类别。
  - `my-data/2026-03-21-云麓试点边界与只读副本清单.md`: “本次确认的对象是云麓公寓，范围只含预算变更与材料替代两类记录。”
  - `my-data/2026-05-13-采购阅读版-第一条链导出修订.md`: “页面顶部另写明本试点只处理预算变更和材料替代，不含供应商审批”
  - proposed: 增加 core facet：“只读副本收录的变更片段仅限预算变更与材料替代。”证据同时引用“本次确认的对象是云麓公寓，范围只含预算变更与材料替代两类记录。”和原有只读副本引文。
- **material / compound_facet** (definition-06-a): 该 facet 同时要求“收两类变更片段”和“收其回查位置”，是两个可分别陈述、遗漏或反驳的命题，不符合单一命题要求。
  - `my-data/2026-03-21-云麓试点边界与只读副本清单.md`: “只读副本只收被三人选定的两类变更片段及其回查位置”
  - proposed: 把该 core 拆成两个原子 facet：“只读副本收录的变更片段仅限预算变更与材料替代。”以及“只读副本收录这些片段的回查位置。”保留 definition-06-b 为 detail。
- notes: 两处既有 evidence quote 均为所列文件中的逐字子串。全语料后续记录继续维持预算变更和材料替代两类范围；OWNER_DIALOGUE 只更新尾款及延长条件，没有改变只读副本定义。

### history-01 — fix
- **blocking / temporal_ambiguity** (history-01): “后来怎么样了”没有确定截止时间，但语料记录了多个后续阶段：3 月 13 日自动周报被移出本轮试点目标；4 月 26 日其是否继续又被明确记为尚未正式决定；4 月 28 日周报概览和原始记录两条演示路线仍同时保留；4 月 29 日周报入口和生成路线才从主分支移出。回答其中任一后续阶段都可合理解释“后来”，而现有 core facets 只编码了 3 月 13 日的范围决定。
  - `2026-03-13-范围会前的一屏说明.md`: “我记当前决定：证据链优先，自动周报不进这轮试点目标。”
  - `2026-04-26-演示入口变更记录.md`: “自动周报是否继续仍未作正式决定，现有代码和说明不因本记录发生状态变化。”
  - `2026-04-28-演示准备-两套开场.md`: “明天上午再决定开场。今晚保留两条路线，不删功能，也不改产品入口：A 从周报概览进入，B 从一条原始决定记录进入。先写各自会让观众误会什么。”
  - `2026-04-29-林舟与贾宁.md`: “周报入口和生成路线刚从主分支移出。”
  - proposed: 将问题改为：“自动周报在 3 月 2 日最早是什么定位？在 3 月 13 日确定的这轮试点范围中，自动周报如何处理，优先方向改成了什么？”
- **material / compound_facet** (history-01-b): 该 facet 同时要求两个可分别陈述或遗漏的命题：自动周报被移出试点目标，以及试点转为证据链优先。它们必须拆开，否则无法独立判定 stated／omitted／contradicted；“它……改成证据链优先”的主语也容易被误读成自动周报本身变成了证据链。
  - `2026-03-13-范围会前的一屏说明.md`: “我记当前决定：证据链优先，自动周报不进这轮试点目标。”
  - proposed: 将 history-01-b 改为 core：“自动周报后来被移出这轮试点目标”，证据 quote 改为“自动周报不进这轮试点目标”；另增 core facet history-01-e：“这轮试点后来改为证据链优先”，证据 quote 为“我记当前决定：证据链优先”。
- notes: 所有给定 evidence.quote 均为对应文件中的逐字子串；最初的跨来源自动周报定位和 3 月 13 日的范围决定本身都有充分依据。OWNER_DIALOGUE literal 也已检查，与自动周报无关。

### history-03 — fix
- **blocking / ambiguous_question** (history-03): “这个假设后来怎么处理了”可合理地只回答“被撤回”，但现有 core facet 还强制要求新的名称匹配规则；两者在语料中是分别陈述的命题。因此，一个直接回答“假设被撤回”的答案可能被错误判为不完整。
  - `2026-04-14-名称匹配决策日志（事故后）.md`: “真正被撤回的是一个更早的假设”
  - `2026-04-14-名称匹配决策日志（事故后）.md`: “从今天起，名称只用于提出候选，不再单独触发合并”
  - proposed: 将问题改为：“事故之前，系统是按什么假设把两条来源写成同一个实体的？事故后这个假设是否保留，名称匹配改成了什么规则？”
- **material / compound_facet** (history-03-b): 该 core facet 合并了两个可独立判断的命题：旧假设被撤回；名称不再单独触发合并。答案可能只陈述其中一个，现有 facet 无法准确标记 stated/omitted/contradicted。
  - `2026-04-14-名称匹配决策日志（事故后）.md`: “真正被撤回的是一个更早的假设”
  - `2026-04-14-名称匹配决策日志（事故后）.md`: “名称只用于提出候选，不再单独触发合并”
  - proposed: 拆成两个 core facet：history-03-b：“这个更早的假设后来被撤回”；history-03-b2：“名称此后不再单独触发合并”。分别沿用对应的原文证据。
- **material / compound_facet** (history-03-c): 该 detail facet 同时断言生效日期和名称的新用途，是两个可分别出现或遗漏的命题，不应合并计数。
  - `2026-04-14-名称匹配决策日志（事故后）.md`: “从今天起，名称只用于提出候选，不再单独触发合并”
  - `2026-04-14-名称匹配决策日志（事故后）.md`: “date: 2026-04-14”
  - proposed: 拆成两个 detail facet：history-03-c：“名称匹配新规则自 2026 年 4 月 14 日起生效”；history-03-c2：“名称此后只用于提出候选”。”
- notes: 所有给定 evidence.quote 均为命名文件中的逐字子串。全语料检索及完整 OWNER_DIALOGUE 检查未发现后来撤销或改变该名称匹配决定的材料；后续记录反而继续确认候选不得自动形成关系。axis 和 difficulty 没有明显错误。

### history-04 — fix
- **blocking / compound_facet** (history-04-b): This core facet combines two independently judgeable claims: 陈放 inferred that the customer had confirmed, and he inferred that the site could resume use. Either claim alone correctly answers why the wording was misleading, but an answer stating only one would not entail the compound facet and could therefore fail incorrectly.
  - `2026-04-10-逐条更正复核-项目与状态.md`: “唯一失败不是记录又混回去，而是“已分离”把技术动作和客户状态压成一个词。”
  - `2026-04-10-逐条更正复核-项目与状态.md`: “陈放理解成客户已经确认，可以恢复使用”
  - `2026-04-10-逐条更正复核-项目与状态.md`: “我看到这个就会跟现场说可以用了”
  - proposed: Replace history-04-b with one core facet: text:「要改是因为『已分离』把技术动作和客户状态压成了一个词」, evidence quote:「唯一失败不是记录又混回去，而是“已分离”把技术动作和客户状态压成一个词。」Optionally preserve the two observed consequences as separate detail facets:「陈放把它理解成客户已经确认」and「陈放会据此跟现场说可以用了」.
- notes: All supplied evidence quotes are verbatim. The historical wording「已分离」and the reason for changing it are otherwise settled unambiguously. The later progression from「客户复核未开始」to「客户复核已完成」does not change what the status bar said before it was split.

### history-06 — fix
- **blocking / wrong_tag** (history-06-d): “另一个临时测试环境可以关”不是附带细节，而是对“云服务不能停”的修正中不可缺少的另一半。仅要求回答“最低套餐要留”，会让未说明哪些部分可以停的不完整答案通过。
  - `2026-04-28-付款核对与演示边界.md`: “最低套餐要留，试点记录和导出都在里面；另一个临时测试环境今晚可以关，数据已经回到主环境。”
  - `2026-04-28-付款核对与演示边界.md`: “我刚才把“服务要留”和“每个实例都要留”混成了一件事。”
  - proposed: 将 history-06-d 的 tag 从 "detail" 改为 "core"；text 和现有 evidence 保持不变。修正后的两个 core 应分别要求“最低套餐要留”和“另一个临时测试环境可以关”。
- notes: 所有所列引文均为命名文件中的逐字子串。全 corpus 检索未发现晚于 2026-04-28 的材料或 OWNER_DIALOGUE 对这项云服务拆分作出变更。

### history-08 — fix
- **blocking / compound_facet** (history-08-a): The core facet combines two separately gradable propositions: positive attribution to 林舟 and explicit denial that 吴岚 said it. The question only asks who said it, so the correct minimal answer “林舟” should pass without also having to state the negative claim.
  - `2026-04-28-付款核对与演示边界.md`: “林舟: 我先确认是不是我听偏了。你昨晚说“本周核对”，我记成了周五前会给付款日。”
  - `2026-04-28-付款核对与演示边界.md`: “林舟: 那是我补出来的日期，不是你说的。我先划掉。”
  - proposed: Replace the core facet text with “说出‘周五前会给付款日’的是林舟”. If the contrast is worth retaining, add a separate detail facet: “吴岚没有说过这个付款期限”.
- notes: Both supplied evidence quotes are verbatim. The corpus consistently establishes that 林舟 introduced the supposed deadline and 吴岚 denied it; later payment updates, including the owner statement, do not alter that historical attribution.

### history-09 — fix
- **material / quote_mismatch** (history-09-b): The quoted text is not an exact substring of build-record/exercise.py. It crosses two adjacent Python string tokens after “状态，”. The evaluated OWNER_DIALOGUE value contains it, but the strict named-file substring rule does not permit that normalization.
  - `build-record/exercise.py`: “库里记着尾款未到、只有「在内部流程」这句话——那是 5 月 24 日的状态，”
  - `build-record/exercise.py`: “现在不成立了。”
  - proposed: After simplifying this facet as proposed below, replace its evidence quote with the exact substring “尾款到了。”
- **blocking / compound_facet** (history-09-b): This core facet combines two separately judgeable claims: that the balance arrived and that the May 24 record was superseded. An otherwise complete answer such as “后来 8 月 29 日到账了” directly answers the question but does not entail that a record-replacement operation occurred.
  - `build-record/exercise.py`: “尾款到了。”
  - `build-record/exercise.py`: “现在不成立了。”
  - `my-data/2026-05-24-周期结束时的待办状态.md`: “试点尾款仍没有付款结果”
  - proposed: Change history-09-b to: {"tag":"core","text":"后来试点尾款到账了","evidence":[{"corpus_file":"build-record/exercise.py","corpus_source":"owner_statement","quote":"尾款到了。"}]}.
- **material / compound_facet** (history-09-c): The facet conflates provenance, statement date, receipt date, amount, and replacement of the earlier state. Receipt date and amount are independently judgeable detail propositions.
  - `build-record/exercise.py`: “尾款到了。采购 8 月 28 日付的，到账日 8 月 29 日，金额 5400 元，”
  - proposed: Split it into two detail facets: history-09-c text “尾款到账日是 8 月 29 日” with quote “到账日 8 月 29 日”; and a new detail facet text “尾款金额是 5400 元” with quote “金额 5400 元”.
- **material / quote_mismatch** (history-09-e): The evidence quote is not an exact substring of the named file because it crosses adjacent Python string tokens between “尾款，” and “六周延长”.
  - `build-record/exercise.py`: “到账的只有尾款，”
  - `build-record/exercise.py`: “六周延长的附录签字和删除演练那两项，采购一句都没提，仍然是没答复。”
  - proposed: Replace the single evidence item with two items from build-record/exercise.py, quoting exactly “到账的只有尾款，” and “六周延长的附录签字和删除演练那两项，采购一句都没提，仍然是没答复。” respectively.
- **material / quote_mismatch** (history-09-f): Its evidence repeats the same cross-token quote and therefore is not an exact substring of build-record/exercise.py.
  - `build-record/exercise.py`: “六周延长的附录签字和删除演练那两项，采购一句都没提，仍然是没答复。”
  - proposed: Replace the evidence quote with the exact substring “六周延长的附录签字和删除演练那两项，采购一句都没提，仍然是没答复。”
- **material / quote_mismatch** (history-09): The case-level quote “那是 5 月 24 日的状态，现在不成立了” also crosses the same Python string-token boundary and does not occur verbatim in the named file.
  - `build-record/exercise.py`: “那是 5 月 24 日的状态，”
  - `build-record/exercise.py`: “现在不成立了。”
  - proposed: Replace the case-level evidence item with two owner-statement evidence items, quoting exactly “那是 5 月 24 日的状态，” and “现在不成立了。”; retain as_of “2026-09-01” on both.
- notes: The underlying history is otherwise settled and temporally unambiguous: on May 24 the balance had no payment result and was still described as in the internal process; the September 1 owner statement says it arrived on August 29 for 5400 yuan and that the old current-state assertion no longer held.

### join-03 — fix
- **blocking / ambiguous_question** (join-03): “工作那一侧做过什么事”没有限定事件。语料至少支持三种不同答案：赵楠检查待发信链接、在阶段复盘中核对“有用”是否等于“买下”，以及完成一段旁白录音。原问题因此没有唯一答案。
  - `2026-05-05-邀请发出前-两个链接回查.md`: “我按待发信里的顺序从头点了一遍”
  - `2026-05-20-阶段复盘后的条件核对.md`: “先确认自己没有把“有用”听成“买下””
  - `2026-04-14-林舟-赵楠.md`: “林舟: 我回来了。电梯里有张不知道谁掉的快递标签，没动它。你那段录得顺吗？
赵楠: 第三遍才顺。你别现在磨豆，刚刚收音里全是纸箱声。”
  - proposed: 将问题改为：“替林舟保管备用钥匙的那个人是谁？2026 年 5 月 5 日小范围邀请发出前，他对待发信里的链接做了什么？”
- **blocking / over_narrow_core** (join-03-a): 原问题用“替林舟保管备用钥匙的那个人”指称主语，只问此人做过什么，并未要求答出姓名。因此，只回答具体工作动作也是完整答案，却会因遗漏核心身份 facet 而被判错。
  - `2026-04-09-保养取车窗口调整.md`: “赵楠抄送是因为他帮我保管备用钥匙”
  - `2026-05-05-邀请发出前-两个链接回查.md`: “我按待发信里的顺序从头点了一遍”
  - proposed: 若采用上述修订问题，保留 join-03-a 为 core；若保留原问题，则将 join-03-a 的 tag 改为 detail。
- **blocking / wrong_tag** (join-03-c): 问题要求说明具体做过什么，但唯一陈述具体动作的 join-03-c 被标为 detail。现有 core facet join-03-b 只要求声称“至少做过一件事”，所以“他做过一件材料记下的事”这种没有回答具体事项的答案也能通过。
  - `2026-05-05-邀请发出前-两个链接回查.md`: “我按待发信里的顺序从头点了一遍。主入口能打开，页面也只停在一条虚构链和反馈入口，没有多余导航；但下面两个链接有问题。”
  - proposed: 在将问题限定到 2026-05-05 的链接检查后，删除 join-03-b，并将 join-03-c 改为 tag “core”，text 保持“他在邀请发出前按待发信里的顺序把链接从头点了一遍”。
- notes: 三个 facet 的证据引文均为对应文件中的逐字子串。另已核对完整 OWNER_DIALOGUE literal；它只更新尾款状态，不改变本案的身份或历史动作。

### join-04 — fix
- **blocking / ambiguous_question** (join-04): “那份失效的附件”没有唯一指称。语料分别描述了失效的预算邮件附件“预算更新表 v3”和材料替代资产 AS-MAT-01，却没有明确说明二者是同一对象；最新文本又区分“第一条预算链”和第二条材料替代链。因此读者可分别作出“第一条”或“第二条”的合理回答，而当前 core 只接受前者。
  - `2026-04-03-找到-客厅预算调整邮件.md`: “正文列了客厅木作和灯具两项调整，并指向一份“预算更新表 v3”。邮件本身可以打开，但附件位置是外部跳转；我今早点过两次，都只返回“链接已失效”，归档里没有文件副本。”
  - `2026-04-26-演示资产逐项清单.md`: “`AS-MAT-01`：原附件链接，来源为旧项目记录，最后核查 2026-04-26 14:06，结果为“已失效”，没有本地副本。”
  - `2026-05-18-材料替代链的最后状态.md`: “第一条预算链之前已能回源，第二条现在也有它自己的来源和确认；两条的状态不要合成一个总的通过标记。”
  - proposed: 将 question 改为：“那封改预算邮件所指的‘预算更新表 v3’附件已失效；它当前属于哪条链？可以用别的摘录顶上吗？”
- **material / probe_basis_wrong** (join-04-a): 现有 quote 虽逐字匹配，但只说明某个当时称作“第一条记录链”的序列含有“失效附件的说明”；它没有识别“预算更新表 v3”，也没有说明该链是预算链。同日相关材料反而把附件称为“材料附件”，所以该证据不足以排除实体混淆。
  - `2026-04-27-第一条记录链-编排状态，不请验收.md`: “我把第一条记录链排成了一个尚未完成的工作序列：原始变更提出、现场会的口头确认位置、失效附件的说明、以及仍待比较的颜色样和预算差异。”
  - `2026-04-27-材料替代-现场会位置请确认.md`: “原来那份材料附件现在打不开，但会议里有人问能不能把原计划的板材换成另一种，吴岚当时说可以按替代材料继续，前提是把颜色样和预算差异留在项目记录。”
  - `2026-05-12-预算变更状态与晚饭.md`: “林舟: 已按这个分工编排。现在是一条可用链：能从状态回到你的确认，再到现场会和预算邮件；缺失附件单独显示。它还没经过吴岚认可，第二条链也不在这里。
陈放: 我能从你发的内部位置回到三项材料，状态没有混。先叫可用，不叫验收；吴岚还没看，附件也还是缺的。第二条材料替代链另算，别借这个结果带过去。”
  - proposed: 保留修正后的明确问题，并将 join-04-a.text 改为“它当前属于第一条预算链”。其 evidence 应改引 2026-04-03 对“预算更新表 v3”及其失效状态的原文、2026-05-12 对预算邮件附件与第二条材料替代链分离的原文，以及 2026-05-18 的“第一条预算链”原文。
- notes: 案例中的两条原始 evidence.quote 均为逐字匹配。join-04-b 是问题明确要求的单一 core 命题，且后续语料没有授权用其他摘录替代失效位置。OWNER_DIALOGUE 中没有附件或链归属的更新。

### join-05 — fix
- **blocking / over_narrow_core** (join-05-a): 问题只问两条来源分别属于哪个项目，并未要求房号。将“7 栋 1604”写入 core 会使只回答“云麓”的正确答案被判遗漏。
  - `2026-04-05-同姓候选关系核对表.md`: “| 项目与房号 | 云麓 7 栋 1604 | 澄湾 3 栋 1202 | 项目和房号不同 |”
  - `2026-04-11-受限只读恢复协调.md`: “我从列表进了云麓，卡里只剩云麓两条；点来源都回云麓。澄湾那边也各回各的。”
  - proposed: 将该 core facet 的 text 改为“一条属于云麓项目”。如需保留房号，另增 detail facet：“云麓来源对应 7 栋 1604”。”
- **blocking / over_narrow_core** (join-05-b): 问题只要求项目名称，不要求房号；“3 栋 1202”不应成为通过本题所必需的 core 信息。仅回答“澄湾”的答案已经完整回答这一部分问题。
  - `2026-04-05-同姓候选关系核对表.md`: “| 项目与房号 | 云麓 7 栋 1604 | 澄湾 3 栋 1202 | 项目和房号不同 |”
  - `2026-04-11-受限只读恢复协调.md`: “我从列表进了云麓，卡里只剩云麓两条；点来源都回云麓。澄湾那边也各回各的。”
  - proposed: 将该 core facet 的 text 改为“一条属于澄湾项目”。如需保留房号，另增 detail facet：“澄湾来源对应 3 栋 1202”。”
- notes: 所有证据引文均为对应文件中的逐字子串。后续记录确认两条来源仍分别属于云麓和澄湾，并确认由吴岚作出限定恢复决定；join-05-c 与 join-05-d 无需修改。

### join-06 — fix
- **blocking / ambiguous_question** (join-06): “是谁转达的”询问的是传话者，但 join-06-a 回答的是回复的来源角色。记录只明确说采购给出了回复；该句在记录中由林舟说出，同时吴岚又被称为材料传递者，因此无法从措辞唯一判断“转达者”指林舟、吴岚还是原回复方采购。正确回答字面问题可能因此无法满足核心 facet。
  - `2026-04-25-报价材料进入内部处理的核对.md`: “林舟: 我刚跑回来，鞋带还是湿的，先不绕弯。采购只回了“材料可进入内部流程”，但没有说下一站是谁。”
  - `2026-04-25-报价材料进入内部处理的核对.md`: “吴岚是传递材料的人，不自动成为确认所有字段的人”
  - proposed: 将 question 改为：「材料可进入内部流程」是哪个角色给出的回复？按这次核对，它允许什么、不允许什么？
- notes: 所有 facet 引文均与指定文件逐字相符。其余 facet 都由语境支持且是单一命题。2026-09-01 的 OWNER_DIALOGUE 更新了尾款到账结果，但没有改变 2026-04-25 这句回复本身未授予付款许可、未表示接受报价或形成长期合同的含义。

### miss-fp-05 — fix
- **blocking / facet_superseded** (miss-fp-05): 核心 false_premise 成立：语料没有记录客户批准恢复写入，4 月 11 日明确只恢复受限只读。但 absent 的“新导入自 4 月 7 日起一直保持暂停”被后续事实推翻：5 月 15 日一条材料替代记录确实导入了内部试用区。该无范围限定的断言会把指出这次后续内部导入的正确回答判错。
  - `2026-04-11-受限只读恢复协调.md`: “吴岚: 我确认这两条错误归并的更正结果。允许恢复云麓授权试点账号的受限只读查看，仅限现有项目；不恢复写入、导入或原分享链接。执行后把三类账号结果留档。”
  - `2026-04-13-错误关联复盘-候选、出处与旧批次.md`: “吴岚: 把这句话放进结论里：今天没有恢复写入，也没有批准历史迁移。”
  - `2026-05-15-材料替代记录-导入结果与待确认项.md`: “按今天简化后的入口，我把材料替代这条记录导入了内部试用区。”
  - `2026-05-15-材料替代记录-导入结果与待确认项.md`: “材料是我下午那段，来源位置也是我从页面里选的那一个，导入本身没有问题。”
  - proposed: 保留 question 和 shape，将 absent 改为：“语料没有记录客户批准恢复写入。4 月 11 日获准恢复的只有云麓授权试点账号的受限只读查看，并明确不恢复写入、导入或原分享链接；4 月 13 日仍明确没有恢复写入。5 月 15 日后来确有一条材料替代记录导入内部试用区，但语料没有把它记为客户批准后的写入或导入恢复，因此不存在所问的‘批准之后第一批’。”同时用上述 4 月 11 日、4 月 13 日和 5 月 15 日引文替换或补充 evidence。
- notes: 原 evidence.quote 在指定文件中逐字存在，但只反映 4 月 12 日当时的条件，不能支持贯穿整个后续语料的“一直保持暂停”。OWNER_DIALOGUE literal 已检查，与该事故及恢复状态无关。

### miss-fp-06 — fix
- **blocking / ambiguous_question** (miss-fp-06): “那项材料变更”没有日期或可识别的前件。3月11日记录的是一项未被称为“材料变更”的“变化/方案”，陈放纠正的是“有人提到”与“可以照着做”被混同；5月2日又有一项明确涉及换样板的变化，陈放纠正的是“先换样板”被扩大成“整套都换”。两者都是否定“陈放反对”的合理指向，却对应不同的纠正事实，因此当前 question 与 absent 不能唯一对应。
  - `2026-03-11-两次更正摘录（未判明）.md`: ““不是这个意思，方案本身我没意见。我说你把‘有人提到’和‘可以照着做’写成同一件事了。””
  - `2026-05-02-状态词回看-一句纠正到底改了什么.md`: “陈放: 对，问题就在这儿。我说“不是这个意思”，是你把“先换样板”讲成了“整套都换”。我在纠正范围，不是把同意过的那一步取消。你一写已撤回，别人会以为什么都没说过。”
  - `2026-04-27-材料替代-现场会位置请确认.md`: “会议里有人问能不能把原计划的板材换成另一种，吴岚当时说可以按替代材料继续，前提是把颜色样和预算差异留在项目记录。”
  - proposed: 将问题明确锚定为3月11日，并删除没有来源依据的“材料”限定：question 改为「在2026年3月11日记录的两次更正中，陈放反对『这条变化』的理由是什么？」absent 改为「陈放没有反对这条变化。他明确表示这条变化并非不该做、方案本身没有意见；他纠正的是页面把『有人提到』和『可以照着做』写成了同一件事。『陈放不同意这项变化。』只是失败的草稿句。」evidence 应增加《2026-03-11-两次更正摘录（未判明）.md》中的两句完整原话，而不只引用泛化的「失败的草稿句」。
- notes: 原 evidence.quote「失败的草稿句」确为指定文件中的逐字子串；OWNER_DIALOGUE 已核查，不涉及或改写本案事实。

### miss-fp-07 — fix
- **blocking / facet_superseded** (miss-fp-07): The cited evidence establishes only the 2026-04-25 state. The later owner statement says procurement paid the 云麓 limited-pilot balance and expressly says the earlier “only in internal process” state is no longer current. Because the question has no cutoff, “采购从未接受报价” and “它只回了……” are stale overclaims that could cause a correct answer mentioning the later payment while denying any recorded contract-total adjustment to be graded wrong.
  - `my-data/2026-04-25-报价材料进入内部处理的核对.md`: “回复只允许材料在内部被查阅，不是接受报价，没有付款许可，也没有长期合同”
  - `build-record/exercise.py`: “尾款到了。采购 8 月 28 日付的，到账日 8 月 29 日，金额 5400 元，”
  - `build-record/exercise.py`: “库里记着尾款未到、只有「在内部流程」这句话——那是 5 月 24 日的状态，”
  - `build-record/exercise.py`: “现在不成立了。”
  - proposed: Use a current-aware replacement: shape = "unanswerable_detail"; question = "采购接受报价之后，合同金额调整成了多少？"; absent = "语料没有记录采购接受四月二十二日的报价，也没有记录合同金额被调整。四月二十二日的报价为一万八千元；后来采购于八月二十八日支付的 5400 元，付款说明标作「云麓受限试点尾款」，并于八月二十九日到账。5400 元是尾款，不是调整后的合同金额。" Add evidence from the 2026-04-22 quotation and the 2026-09-01 OWNER_DIALOGUE.
- **material / premise_not_false** (miss-fp-07): At the corpus's latest point, acceptance of the April 22 quotation is not explicitly recorded or explicitly contradicted; the later final-payment fact makes either inference defensible. No source records an adjusted contract total. The rigorous negative is therefore absence of the requested detail, not the settled corrective claim that procurement never accepted the quotation.
  - `my-data/2026-04-22-试点报价与范围口头澄清.md`: “报价写的是一万八千元、六周：一个项目、两名使用者、一次导出。”
  - `build-record/exercise.py`: “付款说明写的是「云麓受限试点尾款」，我这边看到的是银行流水第 4 行。”
  - proposed: Change shape from "false_premise" to "unanswerable_detail" and state that neither quotation acceptance nor an adjusted contract amount is recorded; distinguish the 一万八千元 quotation from the later 5400 元 final payment.
- **material / quote_mismatch** (miss-fp-07): The absent field writes 「材料可进入内部流程」, but the source uses Chinese double quotation marks: “材料可进入内部流程”. Under the exact-substring rule, the quoted form in absent is not verbatim. The evidence[].quote itself is verbatim.
  - `my-data/2026-04-25-报价材料进入内部处理的核对.md`: “采购只回了“材料可进入内部流程”，但没有说下一站是谁。”
  - proposed: If retaining this historical wording, replace 「材料可进入内部流程」 with “材料可进入内部流程”.
- notes: Corpus-wide searches found no recorded adjusted contract amount. The two relevant monetary facts are the 一万八千元 quotation and the later 5400 元 final payment; neither supports answering 5400 元 as an adjusted contract total.

### miss-ns-07 — fix
- **blocking / facet_superseded** (miss-ns-07.absent): “Seamflow”确实未出现在语料或 OWNER_DIALOGUE 中，近似实体也确实是 Seamlog；但 absent 中“它只是一个纸面工作名”只符合 2026-03-02 的状态。后续材料明确记录了 Seamlog 项目页，并给出了小范围查看地址。问题没有限定到 2026-03-02，因此把早期状态作为当前事实交给裁判会造成评分错误。
  - `2026-03-02-问题先于界面.md`: “今天先把纸上工作名写成 **Seamlog**。只是桌面上的标签，不是项目，也不是承诺。”
  - `2026-04-01-录制条目跨到前一天.md`: “核对时要分开看三个对象。第一是录制文件及其来源时间，第二是处理后转写里的段落定位，第三是 Seamlog 项目页给条目分配的日期。”
  - `2026-05-05-小范围邀请-只看一条证据链与反馈入口.md`: “查看地址：<https://circle.seamlog.test/evidence-start>”
  - proposed: 将 absent 改为：“材料里没有叫 Seamflow 的东西。名字相近的是 Seamlog。”并将 evidence.quote 改为：“今天先把纸上工作名写成 **Seamlog**。”其余问题、shape 和 absence_proof 可保持不变。
- notes: 已检索整个 my-data/ 的 Seamflow、Seam flow、Seamlog、中文音译/意译近似形式以及版本、上线、发布、开放、工作名和项目页等相关词；未发现 Seamflow，Seamlog 出现在上述五个文件中。已完整检查 build-record/exercise.py 的 OWNER_DIALOGUE literal；其中不含 Seamflow 或 Seamlog，也未改变这一结论。原 evidence.quote 在指定文件中逐字存在。

### miss-ud-05 — fix
- **blocking / probe_basis_wrong** (miss-ud-05): 具体哪一天确实没有记录，因此负例方向正确；但 absent 中“材料只给出……10:36 附近这个位置”不实。定位候选会议时，陈放还给出了“四月中旬”这一近似时间。当前写法可能把正确回答“只知道四月中旬，具体日期不明”判成捏造。
  - `2026-04-26-林舟-陈放.md`: “四月中旬，吴岚应该在，标题可能只写了项目例会。现场提到“替代材料”，后面还跟颜色样和预算差异，这三个词可以一起搜。先给我原始会议候选，不要给后来转发的摘要。”
  - `2026-04-27-材料替代-现场会位置请确认.md`: “那句话在会议记录的 10:36 附近”
  - proposed: 将 absent 改为：“材料没有写出这场现场会具体是哪一天。定位候选会议时，陈放只回忆为‘四月中旬’；找到记录后，正文给出的时间信息是会议记录 10:36 附近的播放位置。”并把 2026-04-26 的“四月中旬”原话加入 evidence。
- **material / ambiguous_question** (miss-ud-05): 问题中的“确认了预算调整”沿用了后来被明确纠正的宽泛表述。语料认为“预算变更在会上得到确认”混合了预算提议、会议处理和后来保存的项目状态；最终核准的会议表述是参会人收窄提议并确认调整后的数额。应采用该表述来唯一指认会议。
  - `2026-05-12-现场会节点-REV-02-措辞与归属复核.md`: “我回读时发现，现场会节点目前显示“预算变更在会上得到确认”，这句话把提议、会议中的处理和后来保存的项目状态挤在了一起。”
  - `2026-05-12-现场会节点-REV-02-措辞与归属复核.md`: “建议最终显示：“现场会记录显示，参会人把邮件中的预算提议收窄为可执行范围，并确认调整后的数额。””
  - proposed: 将 question 改为：“参会人把邮件中的预算提议收窄为可执行范围并确认调整后数额的那场现场会，具体是哪一天开的？”
- notes: 已检索全部 190 个 my-data 文件及 OWNER_DIALOGUE；没有找到该现场会的具体日号。2026-04-27 是找到并转述会议位置的邮件日期，不是现场会日期。原 evidence quote 逐字匹配。修正后仍应保持 unanswerable_detail。

### miss-ud-08 — fix
- **blocking / facet_not_entailed** (absent): The core absence is correct, but “六周始终只是附条件的口头意向” is false as written. A six-week term first appeared in a written quotation on 2026-04-22; the distinct conditional oral statement was the later proposal to extend for another six weeks. A correct answer mentioning the written quotation could conflict with the supplied truth statement.
  - `2026-04-22-试点报价与范围口头澄清.md`: “报价写的是一万八千元、六周：一个项目、两名使用者、一次导出。”
  - `2026-04-22-试点报价与范围口头澄清.md`: “我今天只发修正后的说明，不做单据，不排开始时间。”
  - `2026-04-25-报价材料进入内部处理的核对.md`: “回复只允许材料在内部被查阅，不是接受报价，没有付款许可，也没有长期合同。”
  - `2026-05-20-阶段复盘后的条件核对.md`: “可以讨论再延六周，但那只是口头意向”
  - proposed: Replace `absent` with: “截至2026年9月1日，材料从未给出云麓六周延长的起算日。4月22日的书面报价虽然写了‘六周’，但当时未被接受，且明确不排开始时间；5月20日提出‘再延六周’时，它是以数据处理附录签署、删除演练获得业务确认和尾款处理为条件的口头意向。5月24日该延长仍未生效。9月1日业主虽确认尾款到账，但同时说明附录签字和删除演练仍无答复，所以依然不能推出起算日。3月29日定下的‘从明天开始，先按两周算’只确定两周观察从3月30日开始，不是六周延长的起点。”
- **material / ambiguous_question** (miss-ud-08): “云麓试点的六周” does not distinguish the six-week term in the 2026-04-22 written quotation from the conditional “再延六周” discussed on 2026-05-20. Neither has a recorded start date, but they are different records with different statuses, so the question should identify the intended extension.
  - `2026-04-22-试点报价与范围口头澄清.md`: “报价写的是一万八千元、六周：一个项目、两名使用者、一次导出。”
  - `2026-05-20-阶段复盘后的条件核对.md`: “可以讨论再延六周，但那只是口头意向”
  - `build-record/exercise.py#OWNER_DIALOGUE`: “六周延长的附录签字和删除演练那两项，采购一句都没提，仍然是没答复。”
  - proposed: Replace `question` with: “截至2026年9月1日，云麓后来讨论的六周延长是从哪一天开始算的？”
- notes: All three supplied evidence quotations are verbatim. Whole-corpus searches found no six-week start date in Chinese, Arabic, or synonymous duration forms. The 2026-03-30 start applies only to the two-week observation. The owner statement changes the tail-payment status but leaves the other two extension conditions unanswered.

### set-02 — fix
- **blocking / temporal_ambiguity** (set-02): 题目未限定时间，但使用者数量随时间发生变化：3月21日明确确认三名使用者；4月21日至25日的后续记录则反复把现有/当前试点或报价范围写为两名使用者，且没有说明三人中哪一人被移出。因此，无日期的题目不能无歧义地以三人名单为唯一答案。
  - `2026-03-21-云麓试点边界与只读副本清单.md`: “三名使用者分别是吴岚、陈放和林舟。”
  - `2026-04-21-试点范围与预算的两个问题.md`: “下一次我会把现有的两名使用者、一次导出和支持工作写成一条范围”
  - `2026-04-22-试点报价与范围口头澄清.md`: “当前这份只保留一个项目、两名使用者和一次导出，其他问题单列。”
  - proposed: 将 question 改为“截至2026年3月21日，云麓试点确认的三名使用者分别是谁？”，其余三个 core facets 和证据保持不变。
- notes: 三个 facet 的引文均为指定文件中的逐字子串，且各 facet 都是单一命题；问题仅在于未固定时间。OWNER_DIALOGUE 未提及使用者，不能消除后续两人范围与早期三人名单之间的歧义。

### set-03 — fix
- **blocking / temporal_ambiguity** (set-03): 问题既未指定日期，也未说“当前/现在”，但语料记录了多个阶段的字段方案。2026-03-26 的最小证明描述与七字段清单不同；2026-03-27 明确说“暂列为”；2026-03-28 仍称其为草案，并继续提出“结果说明”的修改建议。证据对象中的 as_of 不会替问题本身消除时点歧义，因此读者可以合理地给出不同阶段的答案。
  - `2026-03-26-保留说明与删除证明的口头核对.md`: “若有人提出按项目删除，至少要留下最小证明：谁在什么时间提出、针对哪个项目、处理动作何时结束、结果是否仍有待确认。”
  - `2026-03-27-删除处理证明-字段草稿.md`: “最小证明字段暂列为：请求标识、项目代号、收到请求的时间、请求范围、处理状态、处理完成时间以及需要补问的说明。”
  - `2026-03-28-删除处理证明草案-字段与范围.md`: “字段方向可以保留。最小证明日志只在具体删除请求被处理时写相应记录，不能反过来成为保存原内容的理由。”
  - `2026-03-28-删除处理证明草案-字段与范围.md`: “建议把“结果说明”限定为一句动作摘要，例如“已按确认范围处理”或“等待范围确认”；不要放处理前后内容的比较、文件名清单或任何可还原内容的描述。”
  - proposed: 将 question 改为：“截至 2026 年 3 月 27 日，《删除处理证明：字段草稿》中暂列的最小证明字段有哪些？”其余七个 core facets 可保持不变。
- notes: 所有 facet 引文均为指定文件中的逐字子串，七个 facet 也都是单一命题。问题在于未把预期答案限定到 2026-03-27 的暂列清单。

### set-04 — fix
- **blocking / ambiguous_question** (set-04): “那次保养”没有用日期、养护机构或其他上下文限定所指事件。语料中先后出现不同名称的保养机构：桥桥保养站记录了一次尚未交车的保养，常青养护则记录了另一封完成并取车的通知；语料没有明确说明二者是同一机构或同一次工单。因此，回答桥桥保养站那次的项目“语料未说明”和回答常青养护的五项内容都可得到合理辩护。
  - `2026-03-15-保养报价中的基础项目.md`: “我现在只是把两家报价并排看”
  - `2026-03-31-今日取车未能交付.md`: “## 2026-03-31 18:37 · 桥桥保养站 → 林舟”
  - `2026-03-31-今日取车未能交付.md`: “原先预计今天可以交付的保养项目还差一个到货件，车目前不能交还。”
  - `2026-04-09-保养取车窗口调整.md`: “## 2026-04-09 11:26 · 常青养护前台 → 林舟”
  - `2026-04-09-保养取车窗口调整.md`: “车辆的常规保养和复查已经结束，可以今天取回。”
  - proposed: 将问题改为：“2026 年 4 月 9 日从常青养护取车时确认的那次保养，实际做了哪几项？”
- **material / compound_facet** (set-04-a): “机油与滤芯更换”同时要求机油更换和滤芯更换，包含两个可被分别陈述、遗漏或否认的事实，不符合单一命题要求。虽然原文把两者写成一个项目短语，评分 facet 仍应原子化。
  - `2026-04-09-保养取车窗口调整.md`: “本次实际项目为机油与滤芯更换、轮胎换位、液位检查、制动液更换和后雨刷片更换”
  - proposed: 删除 set-04-a，改为两个 core facet：set-04-a1，text 为“机油更换”；set-04-a2，text 为“滤芯更换”。两者的 evidence.quote 均可使用“本次实际项目为机油与滤芯更换”。
- notes: 所有给定 evidence.quote 均为对应文件中的逐字子串；常青养护列出的五项也在当日晚些时候被林舟以“与你邮件中的项目一致”确认，后续输入中未发现更改或撤回。

### set-07 — fix
- **blocking / ambiguous_question** (set-07): 问题未限定日期、文件或批次，却用“哪些”要求一个闭合集合。被引判据明确只适用于当时这一批记录；全库另有同日及更晚材料列出其他不能代表首链完成的动作。因此，既可把问题理解为提取所引文件中的四项，也可理解为汇总全语料中的所有明确排除项，两种答案均可辩护。
  - `my-data/2026-05-10-账号到达与首次成功的计数边界.md`: “判据只用于这一批记录的复核，不代表稳定行为模型。”
  - `my-data/2026-05-10-首次成功失败路径核对.md`: “触达、注册、打开帮助都不能替首条链承担意义。”
  - `my-data/2026-05-14-简化路径的停表范围.md`: “终点是那一段被放进链里，并由你明确留下一次状态。不是建项目，也不是读完全部说明，更不是把后续材料一起整理完。”
  - proposed: 将 question 改为：“按 2026 年 5 月 10 日《账号到达与首次成功的计数边界》中用于这一批记录复核的判据，哪四种动作明确不记为完成？”现有四个 core facets 可保持不变。
- **blocking / missing_core** (set-07): 若保留当前宽泛问题，“注册”至少也是语料明确排除的动作，但没有对应 core facet；因此只答现有四项的答案会通过，即使它没有完整回答这个开放措辞的问题。
  - `my-data/2026-05-10-首次成功失败路径核对.md`: “触达、注册、打开帮助都不能替首条链承担意义。”
  - `my-data/2026-05-07-首轮数字只记到注册.md`: “注册是一个可见动作，激活得另选一个对产品有意义、而且能稳定观察的行为。开始看说明和真正完成一次核心任务也不能混成同一步。”
  - proposed: 采用限定后的问题：“按 2026 年 5 月 10 日《账号到达与首次成功的计数边界》中用于这一批记录复核的判据，哪四种动作明确不记为完成？”这样无需新增 core facet；若坚持保留原问题，则至少新增 core facet“注册（建立账号）”，并继续纳入后来明确排除的其他动作。
- notes: 四个现有 facet 的证据引文均为指定文件中的逐字子串，facet 文本也各自为单一命题。已完整检查 build-record/exercise.py 中的 OWNER_DIALOGUE literal；其中没有首链判据或相关更新。

### state-04 — fix
- **blocking / facet_not_entailed** (state-04-a): “records”只是固定名称部分；上下文同时要求加入记录日期。把完整文件名表述为恰好“records”会让不完整答案通过。
  - `my-data/2026-04-29-林舟与贾宁.md`: “改成 records，加记录日期，不加新的视图名。”
  - proposed: 将 facet 文本改为「现在的基础名是 records」。
- **blocking / missing_core** (state-04-b): 问题询问当前文件名，但“加入记录日期”被标成 detail。日期是当前命名规则的一部分，回答只说 records 仍会通过现有核心判定。
  - `my-data/2026-04-29-林舟与贾宁.md`: “改成 records，加记录日期，不加新的视图名。”
  - proposed: 新增或拆出 core facet：「文件名附加记录日期」，证据 quote 为「加记录日期」。
- **material / compound_facet** (state-04-b): 该 facet 同时断言加入记录日期和不加入新视图名，是两个可独立判定的命题。
  - `my-data/2026-04-29-林舟与贾宁.md`: “加记录日期，不加新的视图名”
  - proposed: 拆成两个 facet：「文件名附加记录日期」（core）和「文件名不添加新的视图名」（detail）。
- **material / ambiguous_question** (state-04): “文件名是什么”像是在索取一个完整、具体的文件名，但语料只确定基础名和日期组成规则，没有给出分隔符、扩展名或具体实例名。
  - `my-data/2026-04-29-林舟与贾宁.md`: “改成 records，加记录日期，不加新的视图名。”
  - proposed: 将问题改为「导出文件现在以什么作为基础名，是否附加日期？」
- notes: 所有现有 evidence.quote 均为所列文件的逐字子串。全语料检索未发现 2026-04-29 之后对该导出命名规则的撤回或替换；OWNER_DIALOGUE 也未涉及导出文件名。state-04-c 作为历史 detail 有充分依据。

### state-07 — fix
- **blocking / over_narrow_core** (state-07-b): 问题只要求列出尚未落地的事项。核心事项是“删除演练确认仍未完成”；“等吴岚逐格看完”额外规定了具体等待对象和处理方式。回答“删除演练的业务方确认尚未完成”已经完整回答问题，却不蕴含吴岚必须“逐格看完”，因而可能被错误判为遗漏。
  - `2026-05-20-阶段复盘后的条件核对.md`: “数据处理附录要签，删除演练要有业务方确认，试点尾款要处理。”
  - `2026-05-24-周期结束时的待办状态.md`: “我还没有签附录，也没有完成删除确认；尾款这边没有新日期。”
  - proposed: 将 state-07-b 的 text 改为“删除演练确认仍未完成”。现有引文仍可使用；如需测试“吴岚逐格核对”这一额外信息，应另设 detail facet。
- notes: 所有四处给定引文均与指定文件逐字匹配。三项集合由语料明确封闭。2026-09-01 的 owner statement 后来更新了尾款状态，但同时明确说明 2026-05-24 的状态在当时正确，因此不会推翻本案的 as_of 真值。

### state-08 — fix
- **blocking / temporal_ambiguity** (state-08): 问题没有指定时间点。4 月至 5 月的状态是尚未取得预计日，但 9 月 1 日的 owner statement 已说明尾款实际于 8 月 28 日支付、8 月 29 日到账。当前写法会使“当时没有预计日”和“后来已经付款”成为两个可辩护的回答方向，而评分却强制要求前者。
  - `2026-05-20-阶段复盘后的条件核对.md`: “至于尾款，我仍没有预计日”
  - `2026-05-24-周期结束时的待办状态.md`: “尾款这边没有新日期”
  - `build-record/exercise.py`: “尾款到了。采购 8 月 28 日付的，到账日 8 月 29 日，金额 5400 元”
  - proposed: 将 question 改为：「截至 2026 年 5 月 24 日，云麓受限试点尾款有没有已提供的预计付款日？」将 state-08-a 改为：「截至 2026 年 5 月 24 日，吴岚仍没有拿到试点尾款的预计日。」其证据应增加 2026-05-20 和 2026-05-24 的上述原文。
- **material / ambiguous_question** (state-08): “付款”没有指明对象。语料中同时存在试点尾款、云服务扣费和车辆保养付款；虽然“付款预计日”线程可由检索推断，独立问题仍应明确指向试点尾款。
  - `2026-04-28-4-月末现金风险表（未结项）.md`: “| 云服务 | 5 月 2 日扣费 | 作为必付项扣除 | 5 月 1 日再看一次页面 |”
  - `2026-04-09-保养取车窗口调整.md`: “最终支付 680 元，与你邮件中的项目一致，比最初 420 元估算高 260 元。”
  - `build-record/exercise.py`: “付款说明写的是「云麓受限试点尾款」”
  - proposed: 在问题中明确对象为「云麓受限试点尾款」；采用：「截至 2026 年 5 月 24 日，云麓受限试点尾款有没有已提供的预计付款日？」
- **material / compound_facet** (state-08-e): 该 facet 同时断言尾款的实际到账日，以及该日期不是先前给出的预计日。后半句是独立的日期性质判断，不应与到账事实合在一个 facet 中。
  - `build-record/exercise.py`: “采购 8 月 28 日付的，到账日 8 月 29 日”
  - proposed: 将 state-08-e 的 text 收窄为单一命题：「尾款后来于 8 月 29 日实际到账。」保留 quote「到账日 8 月 29 日」；在问题已固定为截至 2026 年 5 月 24 日后，无需再把“不是预计日”并入该 detail facet。
- notes: 所有五条 evidence.quote 均为所列文件中的逐字子串。全语料未出现一个后来提供的预计付款日；owner statement 提供的是实际支付日和实际到账日。

### aggregate-07 — fix
- **material / compound_facet** (aggregate-07-d): 该 detail facet 合并了两个可独立陈述和判定的命题：复查后追加了哪些项目，以及这些追加项目何时通过电话确认。回答可能只包含其中一项，使“stated / omitted”的判定不明确。
  - `my-data/2026-04-09-保养取车窗口调整.md`: “复查后增加的制动液与雨刷片已在 3 月 30 日电话确认”
  - proposed: 将 aggregate-07-d 改为 detail 文本“复查后追加了制动液与雨刷片”；另增一个 detail facet，文本为“制动液与雨刷片的追加于 3 月 30 日通过电话确认”。两者均可引用原有 quote。
- notes: 所有给定 evidence quote 均为命名文件中的逐字子串。核心答案“比原估算多 260 元”由最终支付记录直接确认，后续语料和 OWNER_DIALOGUE 均未改变该金额；问题及 core/detail 标签其余部分成立。

### chain-05 — fix
- **material / compound_facet** (chain-05-a): 该 facet 把两个可独立判断的前提合并成一个命题。后续同日记录明确称其为“颜色样和预算差异两个前提”。证据引文和事实本身正确，但应拆成两个原子 core facets。
  - `my-data/2026-04-27-材料替代-现场会位置请确认.md`: “前提是把颜色样和预算差异留在项目记录”
  - `my-data/2026-04-27-第一条记录链-编排状态，不请验收.md`: “现场会位置可以用，但旁边应写清原附件无法打开，以及口头确认带着颜色样和预算差异两个前提。”
  - proposed: 将 question 改为“现场会上那句允许按替代材料继续的话，附了哪两个前提？”，并将 chain-05-a 拆为两个 core facets：chain-05-a1“需要把颜色样留在项目记录”；chain-05-a2“需要把预算差异留在项目记录”。两者均引用原证据句“前提是把颜色样和预算差异留在项目记录”。chain-05-b 保持不变。
- notes: 两条 evidence.quote 均为命名文件中的逐字子串；吴岚的发言归属得到语料支持，detail 标签合适。全库检索未发现对该历史发言、发言人或两个前提的后续更正、撤回或取代；OWNER_DIALOGUE 仅更新尾款状态，与本案无关。

### definition-03 — fix
- **material / facet_not_entailed** (definition-03-c): 原文把拆分和交付写成核对表的“用途”，并未证明已经完成交付；同日记录反而说明关系审阅人尚未找到、访问请求也未发出。facet 使用“被拆成……交给……”将预定用途写成了已完成事实。
  - `my-data/2026-04-05-同姓候选关系核对表.md`: “用途：把陈放指到的 `candidate-k271` 拆成两条可回源的候选，交给有权审阅业主关系的人。”
  - `my-data/2026-04-05-个人排查日志-四月五日.md`: “我把“找关系审阅人”留到工作日，没有发访问请求，没有运行新一轮候选，也没有改页面上的任何值。”
  - proposed: 将 facet 文本改为意图态：“这份核对表旨在把 candidate-k271 拆成两条可回源的候选。”不要断言候选已经交付给审阅者。
- **material / compound_facet** (definition-03-c): 该 facet 同时断言两个可独立判断的命题：把卡拆成两条候选，以及把候选交给特定资格的审阅者，不符合单一命题要求。
  - `my-data/2026-04-05-同姓候选关系核对表.md`: “用途：把陈放指到的 `candidate-k271` 拆成两条可回源的候选，交给有权审阅业主关系的人。”
  - proposed: 拆成两个 detail facets：definition-03-c：“这份核对表旨在把 candidate-k271 拆成两条可回源的候选”；definition-03-d：“这两条候选预定交由有权审阅业主关系的人审阅”。
- notes: 三段 evidence quote 均为命名文件中的逐字子串。两个 core facets 均由语料支持且是问题所问的定义内容；definition-03-b 使用历史完成表述，4 月 11 日的后续修正没有抹去该历史事件。全库仅在该核对表中出现 candidate-k271，未发现近似标识造成实体歧义；OWNER_DIALOGUE 也未变更此事项。

### join-02 — fix
- **material / compound_facet** (join-02-c): 该 facet 合并了两个可分别判断的命题：“是人留下的状态”和“不是自动判定”。其引文只直接表达后一个命题；同一文件中已有更准确、原子化的正面描述。
  - `2026-05-08-样例里的确认是谁做的.md`: “林舟: 明白了。那张样例预先放了一次虚构人物的人工选择，程序只把记录显示出来；可界面把人物和动作都藏掉了，等于逼你替它猜。”
  - proposed: 将 join-02-c 改为：{"facet_id":"join-02-c","tag":"core","text":"「已确认」是样例中预先放入的一次虚构人物的人工选择","evidence":[{"corpus_file":"2026-05-08-样例里的确认是谁做的.md","quote":"那张样例预先放了一次虚构人物的人工选择"}]}。
- notes: 三个现有 evidence quote 均为对应文件中的逐字子串。全库检索未发现陈语近似姓名造成的实体混淆，也未发现后来材料撤回或改写这一历史事件；OWNER_DIALOGUE literal 亦无相关覆盖。其余 facets、标签、问题措辞、axis 与 difficulty 可成立。

### miss-fp-04 — fix
- **material / facet_superseded** (absent): “根因保持三个未排除的猜测”停留在 4 月 1 日的初始状态。后续核对已经确认该样本的列表读取了错误的日期字段；仍未确定的是该字段的来源及数据层原因。因此，把当前根因笼统表述为“三个猜测”会混淆已确认的显示层原因与仍未解决的数据层问题。
  - `2026-04-01-录制条目跨到前一天.md`: “目前有三个互斥不了的猜测：导入时把本地时间当成了无偏移值；存储值正确，但项目页按另一列分组；旧批次中间做过一次换算，详情页和列表页各读了一份结果。”
  - `2026-04-01-相邻录制样本.md`: “B 条还有一个不同点：详情页同时保留 `source_started_at` 和一个不带偏移的 `meeting_date`，列表分组展示的是后者。”
  - `2026-04-02-林舟-贾宁.md`: “贾宁: 那只能说明这个样本的页面读错列。拿一个更早的批次，再拿一条没有跨日的录制，对照来源、写入和展示三个值。”
  - `2026-04-02-林舟-贾宁.md`: “贾宁: 测试先留着，但别把它叫时区修复。你的历史夹具坏了，本身就是现在不能判断数据层的原因。”
  - `2026-04-02-林舟-贾宁.md`: “林舟: 记了。今天实际完成的是列表排序和两条新测试；历史回放、附件地址、名称候选都没查完。”
  - proposed: 保留原 question 和 false_premise 标签，将 absent 改为：“对该样本实际完成的是项目列表改为按来源开始时间排序，并补了两条排序测试；这只能说明页面此前读错列，不能称为时区修复。针对跨日问题的历史回放仍未完成，所以没有回放结论，数据层原因仍不能判断。”
- notes: 现有 evidence.quote 是命名文件中的精确子串。全库未发现后来把该跨日问题称为时区修复或报告其历史回放结论的材料；4 月 14 日运行的重放属于名称错误关联事故，并非该跨日排查。OWNER_DIALOGUE 也没有更新此事。

### miss-ns-05 — fix
- **material / probe_basis_wrong** (miss-ns-05): “candidate-k288”及其数字、大小写和中文数字变体在全部输入语料和 OWNER_DIALOGUE 中均未出现；唯一出现的 candidate-k 编号是 candidate-k271，因此 question、shape、absent 和 absence_proof 都成立。但 evidence.quote 仅为通用字段名“候选卡标识”，虽然逐字存在，却不能证明 absent 中的纠正事实“出现过的是 candidate-k271”。
  - `my-data/2026-04-05-同姓候选关系核对表.md`: “| 候选卡标识 | `candidate-k271` | `candidate-k271` | 页面把两行放在同一卡下 |”
  - proposed: 将 evidence[0].quote 改为：“| 候选卡标识 | `candidate-k271` | `candidate-k271` | 页面把两行放在同一卡下 |”。其余字段保持不变。
- notes: 已对 my-data/ 全库及 OWNER_DIALOGUE 检索 candidate-k288、candidate-k271、k288/k271、大小写、全角数字以及常见中文数字写法；candidate-k288 无命中，candidate-k271 仅在所列文件中出现。对 build-record/exercise.py 只读取了完整的 OWNER_DIALOGUE literal。

### miss-ud-03 — fix
- **material / facet_not_entailed** (miss-ud-03): `absent` 中“材料只给出页面短标签和联系尾号”的“只”不成立：同一材料还给出了来源定位、项目与房号、现场消息父项和候选卡标识。两位业主的全名确实从未出现，因此负例核心正确，但附带事实需要改写。
  - `2026-04-05-同姓候选关系核对表.md`: “| 来源定位 | `owner-src-104` | `owner-src-887` | 两个定位都能单独打开 |”
  - `2026-04-05-同姓候选关系核对表.md`: “| 项目与房号 | 云麓 7 栋 1604 | 澄湾 3 栋 1202 | 项目和房号不同 |”
  - `2026-04-05-同姓候选关系核对表.md`: “| 现场消息父项 | `thread-7f2` | `thread-91c` | 各自指向不同对话 |”
  - proposed: 将 `absent` 改为：“材料把两条受影响记录的页面短标签都写作‘周女士’，联系尾号分别为 2618 和 9043；没有给出这两位业主的全名。”
- notes: 全库检索未发现与“周女士”、2618、9043、candidate-k271、owner-src-104 或 owner-src-887 关联的全名；OWNER_DIALOGUE 也未提及这些对象。现有 evidence.quote“页面短标签”在指定文件中逐字存在。

### miss-ud-04 — fix
- **material / facet_not_entailed** (absent): 核心的不可回答判断正确：语料没有给出七个账号与七位姓名的完整对应。但“材料只记账号建立数”过强。5 月 8 日至少明确记录了陈语已经注册；语料却没有说明她是否属于 5 月 7 日 09:30 截止时统计的七条记录。因此应表述为“没有完整七人名单或逐一对应”，而不是暗示材料完全没有记录任何注册者身份。
  - `my-data/2026-05-07-首轮数字只记到注册.md`: “这里的注册只认账号建立记录，再按受邀地址去重；同一个人重试不加一。周二实际发出十二份小范围邀请，截至今天九点半，七位受邀对象留下了这样的记录。”
  - `my-data/2026-05-08-样例里的确认是谁做的.md`: “陈语: 那下面三个状态是让我体验选择吗？我已经注册进来了，看得到按钮，但不知道这是否表示我有资格点“已确认”。”
  - `my-data/2026-05-10-账号到达与首次成功的计数边界.md`: “本页只保存五月十日复核时能重新找到的两类记录：七个已建立账号，以及其中两条包含来源片段、回查位置和状态项的首链。”
  - proposed: 将 absent 改为：“材料确认截至 5 月 7 日 09:30，有七位受邀对象留下按受邀地址去重的账号建立记录，5 月 10 日仍记为七个已建立账号；但材料没有给出七个账号与七位姓名的完整对应，因此无法列出七人名单。陈语后来明确说自己已经注册，但材料没有说明她是否属于 5 月 7 日截止时统计的七条记录。”
- **material / probe_basis_wrong** (evidence[0]): 现有引文逐字匹配，但只定义了“注册”，没有包含十二份邀请、七位受邀对象或统计截止点，不能充分锚定问题所指的七人群体。
  - `my-data/2026-05-07-首轮数字只记到注册.md`: “这里的注册只认账号建立记录，再按受邀地址去重；同一个人重试不加一。周二实际发出十二份小范围邀请，截至今天九点半，七位受邀对象留下了这样的记录。建立账号之后有没有开始引导、走到哪一页，这张表都没有回答。”
  - proposed: 将 evidence[0].quote 改为：“这里的注册只认账号建立记录，再按受邀地址去重；同一个人重试不加一。周二实际发出十二份小范围邀请，截至今天九点半，七位受邀对象留下了这样的记录。建立账号之后有没有开始引导、走到哪一页，这张表都没有回答。”
- notes: 已检索全部 my-data/ 中“七位/七人/7位/七个账号”、注册、账号建立、受邀者、邀请名单及相关同义写法，并检查完整 OWNER_DIALOGUE literal；未发现完整七人身份名单或后来补齐的账号—姓名对应。问题本身仍适合作为 unanswerable_detail，所需修正是收窄 absent 并加强证据引文。

### set-06 — fix
- **material / temporal_ambiguity** (set-06): 题干把“三样”写成未限定时间和批次的通用首链标准，但原文明确说该判据只适用于 5 月 10 日这一批记录，不是稳定模型；后续记录又采用了更细的四项留存方式。虽然三个 facet 均有逐字证据且彼此为单一命题，题干仍应固定到 5 月 10 日的复核语境。
  - `2026-05-10-账号到达与首次成功的计数边界.md`: “判据只用于这一批记录的复核，不代表稳定行为模型。”
  - `2026-05-18-材料替代链的最后状态.md`: “我会在两个链旁各留四样东西：原材料入口、谁在何时留下状态、这次确认对应哪段材料、以及仍另行追踪的定位问题。”
  - proposed: 将 question 改为：「在 2026 年 5 月 10 日对这一批记录的复核中，一条『首链』要同时留下哪三样可查内容？」三个 facet 及其标签和证据无需修改。
- notes: 所有 facet 引文和 case 级引文均为命名文件中的逐字子串；三个 core facet 正好覆盖题目所问的三项。OWNER_DIALOGUE 中没有首链判据的更新。

### state-03 — fix
- **material / compound_facet** (state-03-c): 该 core facet 合并了“写入未恢复”和“导入未恢复”两个独立命题。题目分别询问两项，应让 judge 能逐项标记 stated / omitted / contradicted。
  - `2026-04-11-受限只读恢复协调.md`: “不恢复写入、导入或原分享链接”
  - `2026-04-12-事故说明-同姓记录错误关联与当前处置.md`: “写入、导入和原分享链接没有恢复。”
  - proposed: 将 state-03-c 改为 core facet“写入没有恢复”，并新增一个 core facet“导入没有恢复”；两者均可引用“写入、导入和原分享链接没有恢复。”
- notes: 其余 facet 的引文均为指定文件中的逐字子串；截至 2026-04-12 的最新文件确认只读查看仅向云麓授权试点账号恢复，写入、导入及原分享链接均未恢复。问题的时间点和实体均无歧义；后置 OWNER_DIALOGUE 只更新尾款状态，与本题无关。

### state-06 — fix
- **material / facet_superseded** (state-06-c): 该表述把 5 月 15 日的阶段性记录内容写成了无时间限定的现状。5 月 18 日林舟明确表示会新增现场确认作为状态依据，并将现场确认等内容分开显示，因此记录已不再“只包含”原来的三项。
  - `2026-05-15-材料替代记录-导入结果与待确认项.md`: “记录目前只包含你选定的材料片段、它的来源位置和一个“待确认”状态”
  - `2026-05-18-材料替代链的最后状态.md`: “那我会把这句确认作为今天新增的状态依据，仍保留昨天选定的材料片段和它原来的来源位置。材料、导入动作、现场确认和状态留存人分开显示；这样以后回看时，不会把今天的答复倒写成材料一开始就带着的结论。”
  - proposed: 5 月 15 日导入时，这条记录只包含选定的材料片段、它的来源位置和一个「待确认」状态
- notes: 四处 evidence.quote 均为对应文件中的逐字子串。核心 facet 仍成立：5 月 18 日只说留下「待确认」的人“可以”改成已确认，并未记载实际改动；后续输入及 OWNER_DIALOGUE 也没有记录该状态被更新。“最后”已将问题限定为最新记录状态。

### state-09 — fix
- **material / quote_mismatch** (state-09-f): The evidence quote is not a verbatim substring of build-record/exercise.py. It joins text across two separate adjacent Python string literals; runtime concatenation does not satisfy the raw-file substring rule.
  - `build-record/exercise.py`: “对，5 月 24 日那条在它的时点上是对的，别改它。另外说清楚：到账的只有尾款，”
  - `build-record/exercise.py`: “六周延长的附录签字和删除演练那两项，采购一句都没提，仍然是没答复。”
  - proposed: Keep the facet text, but change its evidence quote to the exact substring "到账的只有尾款".
- **material / quote_mismatch** (state-09-g): Its evidence quote has the same invalid cross-literal join and therefore does not occur verbatim in the named file.
  - `build-record/exercise.py`: “六周延长的附录签字和删除演练那两项，采购一句都没提，仍然是没答复。”
  - proposed: Change the evidence quote to "六周延长的附录签字和删除演练那两项，采购一句都没提，仍然是没答复。"
- **material / compound_facet** (state-09-g): The facet combines the independently judgeable states of the appendix signature and the deletion drill. An answer could state one while omitting the other, so they cannot be scored cleanly as one proposition.
  - `build-record/exercise.py`: “六周延长的附录签字和删除演练那两项，采购一句都没提，仍然是没答复。”
  - proposed: Replace state-09-g with two detail facets: state-09-g, text "采购仍未答复六周延长所需的附录签字事项"; and state-09-h, text "采购仍未答复六周延长所需的删除演练事项". Use the exact quote "六周延长的附录签字和删除演练那两项，采购一句都没提，仍然是没答复。" for each.
- notes: The question and all three core facets are otherwise correct and unambiguous. The 2026-09-01 owner statement explicitly supersedes the 2026-05-24 outstanding-balance state and supplies the settled amount and receipt date. The earlier 18,000-yuan figure is the full pilot quotation, not the tail payment.

## Sound cases with minor notes

## Sound, no issues

aggregate-04, aggregate-05, aggregate-09, calendar-01, calendar-03, calendar-04, calendar-06, calendar-07, chain-02, chain-04, chain-07, definition-05, history-02, history-05, history-07, join-01, miss-fp-01, miss-fp-03, miss-fp-08, miss-ns-01, miss-ns-02, miss-ns-03, miss-ns-04, miss-ns-06, miss-ns-08, miss-ud-01, miss-ud-06, miss-ud-07, set-01, set-05, state-01, state-02, state-05
