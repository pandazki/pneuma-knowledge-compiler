# Independently evaluate a knowledge library

**English** | [简体中文](evaluating-libraries.zh-CN.md)

Use this protocol when an evaluation, rather than ordinary onboarding, is requested.
Keep source integrity, knowledge fidelity, usefulness and operating cost as separate results.

1. Before building, freeze the framework revision, source-only input hashes, contract,
   models/providers, embeddings, retrieval settings, question time policy and retry limits.
   A fresh directory must also use fresh canonical state, indexes, tenants and middleware
   namespaces. Reusing an old library is not a fresh compilation.
2. Compile from original material only. Evaluation questions, expected answers, evidence
   labels, rubrics, previous predictions and error analyses must not enter the build or its
   contract-writing agent. Use a fresh agent context when claiming an independent build.
3. Freeze the completed library and build records before releasing questions. Supply only
   question text and identifiers to answering. Never expose expected answers or gold evidence.
   Preserve the library when answering, and record any generated consultation data separately.
4. Freeze all predictions and verify unique identifiers and full coverage before judging.
   Run the requested evaluator unchanged and retain its exact command, version and outputs.
5. Report failed attempts and degradation as well as successes. Retries follow the frozen
   policy; success does not erase a failed attempt. Include per-role cost where available,
   and label unavailable provider usage rather than treating it as zero.
6. Diagnose errors only after the run is frozen. A fresh run of one version supplies an
   observation, not causal evidence of improvement. A comparison needs the same inputs,
   harness and model settings for its baseline; a single stochastic pair still has uncertainty.

A baseline includes the actual model invocation, not just its display name. Record each
role's routing ID, provider, effective reasoning effort, output limit, temperature, answer
schema and fallback behavior. Distinguish an omitted field from an explicit setting. When
comparing versions, inspect the outgoing request body: a binding fix can make a previously
ignored option start working even when the application configuration is unchanged. Keep
request hashes and, where permitted, bodies without authentication headers or credentials.

Name the variable each comparison changes. Supplying all raw material and canonical pages
versus retrieving a bounded selection changes the answer method; changing the deliberation
schema at the same time is not a retrieval-only comparison. Swapping libraries built with
different contracts or model settings changes the compiled input bundle, not just framework
code. First reproduce the baseline's method, then change one setting or explicitly named
group at a time. A frozen-library answer comparison does not test a fresh compilation, and
answering well with all raw material does not establish the value added by canonical.

Record what isolation was actually enforced. A directory boundary alone is not an access
control boundary, and a model may have encountered public benchmark material in training.
Procedural isolation does not establish absence of training contamination.
