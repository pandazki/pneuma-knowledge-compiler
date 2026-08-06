# 冻结记录（FROZEN）

## 第一次冻结：十份契约 + 01-build.sh 及其依赖

冻结时间（UTC）：**2026-08-06T09:26:56Z**

此刻起，阶段 B 之前只允许追加 02/03；下方任何文件的改动都必须重新冻结并保留旧哈希。

| 文件 | SHA-256 |
|---|---|
| `01-build.sh` | `8d10fe9b6194be67d4b7c05dfc76cd892fdfbd013cbedf4a412cfbd9f98b5a1b` |
| `to_material.py` | `e3d7e52f1c60b2daa2bd59dc4e816a370eb0c27bc73fa458748e919845ccfee6` |
| `apply_env.py` | `4f466d2fe8ba09c9dce02a09c083cab9fd8b363c2da471696ee811f30e99c321` |
| `lf.py` | `afadeab0d3244466b744e4b772c7f9583dc63f2f61ceb6d5aa693636bf448e42` |
| `write-contracts.py` | `ee8489474dad37c5e4a16e7cd012078aeaf139ba3ebe6044d0ff1ec5c2d77340` |
| `app-01/engine/compile/contract.md` | `b6bc43300456b6b36c5a2938b8a8dbe2e9b697c7e08539d4967c5e63cf1b1283` |
| `app-02/engine/compile/contract.md` | `0c089b9a3f0bc358ee40a4477d55770260548b54a5ef31ee758a7a3ad86eb574` |
| `app-03/engine/compile/contract.md` | `423ffcc5246b55ef877aeb39722a9d0c37252dc4241f00bb41a266e5f59742a7` |
| `app-04/engine/compile/contract.md` | `7991b93a050acd579da83c7cb946acbf77a6766cfa158b2c561e5c8b21fcd9f9` |
| `app-05/engine/compile/contract.md` | `c7b6ecdfe8e344350c6e9175eb7463d64d8e202ed76c1bfaab2cdda3dfe60b33` |
| `app-06/engine/compile/contract.md` | `dd742385805056a6ed1d916764577f83a834ca4f20619a1fb331ecb530123bba` |
| `app-07/engine/compile/contract.md` | `603b68fec68f78af6bcf3821f97318106fd973e4413ef6304954d3edaba9fdce` |
| `app-08/engine/compile/contract.md` | `98bbc3f659a00cca1d8a03130ea710faaab281053c0456ce895b0f81e1e3a712` |
| `app-09/engine/compile/contract.md` | `acaa3eeceebbdb446781e29905bb3d844e25cdc2befd2ddc97829526bc1e0e04` |
| `app-10/engine/compile/contract.md` | `4b9f1acf488be89bd878fb6057c90344f679a12e432a97bc144e41b44dac4dd1` |

## 第二次冻结：02-answer.sh / 03-score.sh 及其依赖

冻结时间（UTC）：**2026-08-06T09:35:20Z**

先于本次冻结、后于第一次冻结发生的动作：通读官方 `README.md`、`src/llm_judge.py`、`src/evaluate.py`、`src/llm_judge_runtime.py`、`scripts/run_eval.sh`、`scripts/env.sh`、`data/public/submission_template.jsonl`。

### 烧题清单

官方 README 的预测格式示例直接给出了两道题的答案值（题面未出现，qa_id 与答案值出现）：

| qa_id | README 中出现的值 | 出处 |
|---|---|---|
| `conv-26#q0000` | `7 May 2023` | README「Prepare the prediction file」与「Prediction Format」两处 |
| `conv-26#q0001` | `2022` | README「Prepare the prediction file」 |

两题均属 conversation idx 0（app-01）。阶段 C 的双分数即以剔除这两题为口径。

| 文件 | SHA-256 |
|---|---|
| `02-answer.sh` | `21e7fcf40a6d0654d13420f8e1f08db834f98624f0cc15de8003d446a3310d4a` |
| `answer_runner.py` | `109ff88a81d91c4c3d23eabd15677349e4040798b8d8eabb924f34236675e6a2` |
| `03-score.sh` | `d9eef816cb8dc9f577d21741009ebedf4d72aed3336da9e781a663bbb2409b7a` |
