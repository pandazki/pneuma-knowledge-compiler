"""The shared recall answer-contract spine (fast / deep / briefing).

One worldview written ONCE: 本人画像 → 眼前证据即全部可见范围 + 主体身份分辨 → 转录音近
容错 → 红线（断言强度＝证据强度、不编造）→ 回链出处用 `[cite:]` 标记 → 作答姿态（语言 /
相对时间 / 诚实未知）。每个模式 = 一个「角色 + 证据形态 + 工具面」的头 + 这段 spine（注入
它自己的引用粒度）。

集中在这里是为了三个契约不再漂移：它们本是同一套姿态的复制，早先逐个打补丁时 briefing 这条
就先漏了红线、又漏了 `[cite:]` 指令（模型转而写「来源 s-010」这类人类标签，API 引用全空）。
`spine(...)` 在模块加载时产出定值，每个模式仍是逐字节稳定的 System（I5 / prompt-cache）。"""

from __future__ import annotations

# The one differing clause: fast cites to the source (¶ optional); deep/briefing cite the
# exact block span. Injected into the spine's citation bullet.
CITE_SOURCE_LEVEL = (
    "本场景到来源级即可（`[cite: <source_id>]`，可省去 ¶ 段落，有可靠来源就带、没有也不硬凑），"
    "它是给日后回溯留的线索、不是本场景的硬指标。"
)
CITE_PRECISE = "精确到段落（`[cite: <source_id> ¶a-b]`）。"

# The second injection point: the closing clause of 作答形态. Q&A modes (fast/deep/briefing)
# close on "nothing found is a faithful answer" — right when a owner ASKED something. A
# listening mode (cue) has no question, so that clause would make it push a card reading
# 「无相关记录」onto the lens; it needs its own close. Same mechanism as `{cite}`: one spine,
# one differing clause per mode, never a forked copy.
CLOSE_ANSWER_HONESTLY = (
    "- 眼前证据覆盖不到本人所求时，「无相关记录」就是忠实的答案；不要复述输入或添加\n"
    "  「根据记录」类前缀。"
)

_SPINE = """\
每次提问的最上方，先摆着本人的基本画像——是谁、做什么、惯用什么语言。它是你对面
这个人的底色，帮你把话与所指对上号，本身不是证据。

眼前这批证据就是你此刻对本人知识库的全部可见范围。它来自宽召回，天然混有与本人
所指主体仅仅相近的条目（同名近似的人、结构相仿的另一条记录）：出处与主体身份是分辨
它们的依据——属于其他主体的证据再相似也是另一条记录，不属于这个答案。

输入可能来自转录，夹带同音、近音的听写偏差（人名与术语最容易中招）。认主体时考虑
这种音近出入，别为一两字之差把本该作答的记录错认成另一个主体。

作答形态：

- 断言的强度必须与证据的强度对齐——这是红线：证据只是描述性地讲了个过程 / 东西，别替它
  安上确定专名；一方的交代或提议、没见对方接受或拍板的，别写成已定的事实；证据存疑或相互
  矛盾的，把不确定与分歧如实留着；听不清的关键值不坐实。宁可把话说得虚一点，也不编一个
  证据没给的确定。
- 回链出处一律照抄证据里的 `[cite: …]` 标记——它是给前端提取成组件用的**固定英文标记、
  不随作答语言翻译**（证据里的来源标记本就为本次作答生成，直接抄）；{cite}
- 除非本人这次明确要求换一种语言，都用画像里的惯用语言作答。
- 相对时间（昨天、上周、下个月）按输入旁标注的 as_of 换算成绝对日期表述。
{close}
"""


def spine(cite: str, close: str) -> str:
    """The shared spine with a mode's citation-granularity + closing clauses injected.

    Both are REQUIRED, deliberately: a default `close` would silently hand the Q&A
    closing to a mode that has no question (see CLOSE_ANSWER_HONESTLY). Making it
    positional forces every mode to state which closing it is."""
    return _SPINE.format(cite=cite, close=close)
