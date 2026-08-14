# The engine of {{PROJECT_NAME}}

This directory is your engine. Everything in it — the model roles, how material is cut, how
answers read, when the library audits and reorganizes itself, the compile contract, your
profile, any prompt rewording — decides what this knowledge base does with your material.

It is **its own git repository**, separate from your data and from the machinery. Every
change is a version you can read back and revert. Nothing secret lives here: the API key and
this machine's ports stay in `../.env`, which is never versioned.

```
engine.yaml              model roles: compile / recall / answer / deep / embedding
intake/intake.yaml       how material is cut into semantic units
compile/contract.md      the constitution — what deserves memory, on which page
compile/challenge.yaml   the post-compile coverage audit
evolve/evolve.yaml       when the library may propose reorganizing itself
recall/recall.yaml       how answers read, and the retrieval budget per question
persona/profile.yaml     who the owner is
prompts/overlays.yaml    which language the framework's own prompts arrive in, plus
                         replacement wording for any of them (usually empty)
```

## Three things worth knowing before you edit

**The contract is a document, not a set of switches.** `compile/contract.md` teaches the
compile model to judge what deserves long-term memory in *your* domain and which page it
belongs on. That is judgement, and it is written in prose — there is no form that could
capture it. The full practice lives in the framework repository's
`docs/guides/compile-contract.md`.

**Every change states its blast radius.** Nothing you do here rewrites what is already
recorded:

| Change | What it affects |
|---|---|
| answering style, retrieval budgets | the next question you ask |
| model roles, prompt language, prompt overlays | after the next start |
| the contract, challenge, evolve | future compiles only — recorded knowledge is never rewritten |
| chunking strategy | new material at once; existing material after a derived rebuild |

`recall/recall.yaml` separates cheap retrieval breadth from final model context.
`claim_candidate_cap` and `window_candidate_cap` search broadly; `claim_cap`,
`episode_summary_cap`, and `window_cap` admit three different content faces. Episode
summaries are dense generated L2 content, shown under an explicit derived label with source
title, occurrence time, section, and exact span. They are not presented as verbatim source;
the smaller raw-window budget remains the exact-text face.

`evidence_strategy` controls how those faces are composed. `ranked` is the direct,
lowest-latency fixed-head path. `select` adds one bounded structured recall-model call over
the broad candidates; the framework validates its coordinates, retains ranked safety anchors,
and follows selected derived provenance back to L0. `answer_format` is independent: `text`
keeps the ordinary free-text answer, while `structured` separates answer kind, clean text and
precise citations so cited spans can be validated. Both can be overridden for one `ask`.

**The prompt language is the layer your overrides sit on.** `prompts/overlays.yaml` opens
with `language:` — `en` is the framework's default English catalog; `zh` swaps in the shipped
Chinese language pack, for readability and for Chinese material. Either way your
own clauses under `overlays:` are applied *after* it and win over it. It does not decide what
language this library is written in: that follows the owner profile's declared language.

**Your environment can override any of it for one run.** The order is: process environment
(`PNEUMA_KNOWLEDGE_*`) beats this directory, and this directory beats the framework default.
That supports one-off diagnosis — `PNEUMA_KNOWLEDGE_RECALL_WINDOW_CANDIDATE_CAP=80
./app.py ask '…'` checks whether missing material is a search-depth problem without dirtying
a versioned file. A durable operating decision belongs in the file.

## Editing it

Edit the files and run `./app.py …` again — the driver reads this directory on every command.
Commit when you are happy with a state:

```bash
cd engine && git add -A && git commit -m "raise the claim budget" && cd ..
git -C engine log --oneline        # every version of this engine
```

The framework's Engine Console (`/v1/engine/*`) is the same thing with a picture attached: it
renders this directory as the lifecycle it configures, shows where each value came from, and
commits every apply here with a label.
