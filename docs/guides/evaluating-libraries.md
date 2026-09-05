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

Record what isolation was actually enforced. A directory boundary alone is not an access
control boundary, and a model may have encountered public benchmark material in training.
Procedural isolation does not establish absence of training contamination.
