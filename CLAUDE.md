# NazaréNow

Predicts when Praia do Norte in Nazaré, Portugal will produce giant waves, early enough to book
travel and witness them.

Read `CONTEXT.md` for the domain vocabulary before writing anything that names a domain concept,
and `docs/adr/` for the decisions that shaped the architecture. The distinction between **Face
Height** and **Significant Wave Height** in `CONTEXT.md` is load-bearing — conflating them
silently invalidates the model's evaluation.

## Agent skills

### Issue tracker

Issues and specs live as GitHub issues, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles, each label string equal to its name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
