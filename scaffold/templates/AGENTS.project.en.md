# Working in {{PROJECT_NAME}}

This is a generated knowledge-library application. The framework is at `{{FRAMEWORK_REPO}}`.
Read this project's README first. For library building and validation, use the framework's
`scaffold/AGENT-GUIDE.md`; consult `docs/guides/compile-contract.md` when specializing the contract.

- Preserve raw sources and structured identity/time/media fields. Unknown profile facts stay
  unknown; a tenant can represent a team or topic without being a person in its sources.
- Start from the executable contract. Adapt subject boundaries and admission to actual future
  uses. Keep concrete useful facts in the ledger and a faithful current picture in the overview.
- Validate source integrity, canonical fidelity and answer usefulness separately. Read exact
  evidence with `ask --sources`; report failures and degradation, not just successful commands.
- Put strategy in `engine/` and commit intentional states. Keep credentials, private inputs and
  runtime receipts out of Git. Process environment overrides engine files for one run.
- Use existing user authorization. Do not repeatedly ask for approval of reversible work; ask
  when a consequential choice genuinely lacks necessary information or authorization.
- Do not edit canonical knowledge by hand to improve a result. A derived rebuild does not
  recompile it. Preserve the original library when testing a new contract in a fresh project.
- Do not run the console worker and CLI compile/build concurrently against the same stack.
- `app.py`, `start.sh`, `server.py`, `worker.py` and `docker-compose.yml` are generated machinery.
  Improve the framework templates and replace machinery while preserving this engine and data.

Default path: `./start.sh` → `glance` → `ask --sources` → inspect `data/run-reports/`.
A passed gate checks structure and provenance addresses; it does not prove a claim's meaning.
