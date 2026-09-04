# Frozen executable protocol

`TASKBOOK.md` is the experiment authority. This file fixes the executable boundaries used
to implement it before production code is written.

## Phase-one interfaces

### `merge_env.py`

`merge_env.py GENERATED SECRET DESTINATION` reads generated infrastructure settings and the
operator-owned secret file, writes one private dotenv file, and prints counts only. The secret
file wins on duplicate keys except that
`PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER=openai` is forced. Empty or malformed source lines
fail loudly. The destination mode is `0600`; no value is written to stdout or stderr.

### `to_material.py`

- `count CONVERSATION_IDX` prints that conversation's session count.
- `emit CONVERSATION_IDX SESSION_NO OUTPUT_DIR --parser-app APP_PY` writes exactly one markdown
  material and verifies the file after writing.
- `verify-all OUTPUT_ROOT --parser-app APP_PY` writes and verifies all 272 session files and
  emits only aggregate counts.

Each source message becomes one conversation turn and its source `(speaker, text)` is preserved
byte-for-byte. Image URLs, captions, and queries are independently attached to the verified
`Context` turn using message ordinals; they therefore remain compiler-visible without mutating
source text, and captions/queries never depend on an image being present. The generated harness
receives one deterministic compatibility patch because the commit's parser otherwise discards
internal blank continuation lines (two source messages contain one). The framework worktree is
untouched. Verification loads the resulting generated project's real `split_frontmatter` and
`parse_conversation_turns`, compares the recovered source tuples directly, and checks an
independent SHA-256 sequence digest. Any mismatch is a hard error and the session is not accepted.

### `00-setup.py`

Generate ten independent scaffold projects named `lcr2609-NN`, with tenant ids
`u-lcr2609-NN` and scaffold-assigned ports/subnets. Install the corresponding frozen contract
and shared engine configuration, merge `secrets/.env` without exposing values, force the
official OpenAI provider, and commit the engine repository. An already conforming project is
left in place; a non-conforming existing project fails rather than being overwritten.

### `01-build.sh`

Verify FREEZE#1 hashes before doing work. At most two conversation projects are active at once;
within one project, sessions are materialized, ingested, and drained strictly in source order.
A session `.done` marker is written only after `app.py compile` returns zero and `status` reports
no pending jobs. Evolution fires after at least 80 new claims and six new sessions, plus one
forced final round, through `evolve step --policy adopt-clean`. Retryable operations use bounded
exponential backoff. Every Docker-mutating app command is preceded by an exact compose-prefix
guard and targets only that project; teardown preserves volumes.

The scope guard checks the scaffold's `PNEUMA_APP_COMPOSE_PROJECT` value against the exact
`pneuma-lcr2609-NN-` prefix before every app operation. Progress CSVs, individual logs, PID
files, and atomic `.done` markers live under
`build-record/`. At 136 completed sessions a conservative full-price projection is recorded.
After that, every completed session is checked against the combined build-and-answer budget;
estimated spend at or above USD 60 stops new work. USD 50 is a soft ceiling and is disclosed,
not silently ignored.

## Phase-two interfaces

Answering and scoring code is deliberately unspecified until FREEZE#1. It must mechanically
project only `qa_id`, `conversation_idx`, and `question`, ask as a silent visitor, verify the
frozen hashes, and keep gold-bearing scorer artifacts outside the evidence repository until a
post-score sanitizer removes prohibited fields.
