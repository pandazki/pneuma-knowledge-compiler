# 分数聚合

- 官方全量口径：1382 题，LLM judge **76.34%**，F1 0.2475，BLEU 0.1601
- 剔除烧题（2 题）：1380 题，LLM judge **76.30%**，F1 0.2475，BLEU 0.1601
- 差值：-0.0343 个百分点
- 烧题两道各自的判分：conv-26#q0000=1, conv-26#q0001=1

### 按conversation

| conversation | 题数 | LLM judge | F1 | BLEU |
|---|---:|---:|---:|---:|
| conv-26 | 138 | 74.64% | 0.2428 | 0.1548 |
| conv-30 | 72 | 75.00% | 0.2520 | 0.1677 |
| conv-41 | 136 | 79.41% | 0.2618 | 0.1675 |
| conv-42 | 179 | 77.65% | 0.2616 | 0.1697 |
| conv-43 | 162 | 69.14% | 0.2417 | 0.1591 |
| conv-44 | 114 | 75.44% | 0.2345 | 0.1533 |
| conv-47 | 137 | 81.75% | 0.2730 | 0.1784 |
| conv-48 | 165 | 74.55% | 0.2380 | 0.1517 |
| conv-49 | 135 | 80.00% | 0.2447 | 0.1578 |
| conv-50 | 144 | 76.39% | 0.2251 | 0.1435 |

### 按category

| category | 题数 | LLM judge | F1 | BLEU |
|---|---:|---:|---:|---:|
| 1 | 213 | 60.56% | 0.1748 | 0.1107 |
| 2 | 299 | 66.89% | 0.2269 | 0.1426 |
| 3 | 68 | 70.59% | 0.1606 | 0.1072 |
| 4 | 802 | 84.54% | 0.2819 | 0.1843 |

### 按模态

| 模态 | 题数 | LLM judge | F1 | BLEU |
|---|---:|---:|---:|---:|
| 多模态 | 521 | 72.17% | 0.2200 | 0.1392 |
| 纯文本 | 861 | 78.86% | 0.2642 | 0.1728 |

- 空答案：0 题；答成「no relevant record」：13 题（其中判对 4 题）

### 错题抽样（共 327 题判错，等距抽 8 道）

**conv-26#q0003**（category 1）
- 题：What did Caroline research?
- 金标：['Adoption agencies']
- 作答：Caroline researched counseling or mental-health work as a career, including working with trans people. [cite: s14]
- F1 0.000 / BLEU 0.000

**conv-30#q0019**（category 1）
- 题：What does Jon's dance studio offer?
- 金标：['one-on-one metoring and training to dancers, workshops and classes to local schools and centers']
- 作答：Jon’s dance studio offers dance classes and workshops, plus one-on-one mentoring and training to help dancers reach their full potential. [cite: s01]
- F1 0.500 / BLEU 0.394

**conv-41#q0131**（category 4，多模态）
- 题：What did Maria make for her home to remind her of a trip to England?
- 金标：['painting of a castle on a hill']
- 作答：A castle painting and a picture of a castle in a shadow box. [cite: s02 ¶13-21]
- F1 0.333 / BLEU 0.217

**conv-42#q0175**（category 4，多模态）
- 题：What did Nate share a photo of when mentioning unwinding at home?
- 金标：['a bookcase filled with dvds and movies']
- 作答：The record does not specify what photo Nate shared when discussing unwinding at home. [cite: s12]
- F1 0.000 / BLEU 0.000

**conv-43#q0125**（category 4）
- 题：How long has Tim been playing the piano for, as of December 2023?
- 金标：['about four months']
- 作答：About four months, as of 6 December 2023. [cite: s03 ¶2-16]
- F1 0.273 / BLEU 0.158

**conv-47#q0006**（category 2，多模态）
- 题：When did James adopt Ned?
- 金标：['first week of April 2022', 'last week of April 12 2022']
- 作答：James adopted Ned during the week before 12 April 2022—approximately 5–11 April 2022. [cite: s02 ¶0-7]
- F1 0.242 / BLEU 0.148

**conv-48#q0052**（category 2，多模态）
- 题：When did Deborah lead a meditation session during the sunset?
- 金标：['week before 16 August, 2023', 'From August 7, 2023 to August 13, 2023']
- 作答：During the week of **9–15 August 2023**. [cite: s02 ¶8-8]
- F1 0.207 / BLEU 0.130

**conv-49#q0061**（category 1，多模态）
- 题：How does Evan spend his time with his bride after the wedding?
- 金标：['family get-together, honeymoon in Canada to see snowy landscapes, ski, taste local cuisine and do some snowshoeing']
- 作答：After the wedding, Evan and his bride tried snowshoeing together and planned a February 2024 honeymoon in Canada featuring skiing, sightseeing, local cuisine, and poutine. [cite: s08] [cite: s04]
- F1 0.355 / BLEU 0.275

