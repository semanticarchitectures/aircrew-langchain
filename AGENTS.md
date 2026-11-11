# AGENTS.md

Conventions for AI coding tools working in this repo. `docs/PLAN.md` is the source of truth for
what is built and in what order.

## Umbrella context (Acquisition Knowledge System)

- This repo is a component of the Acquisition Knowledge System: https://github.com/semanticarchitectures/acquisition-knowledge-system.
  Before cross-component work, read its `.kiro/steering/product.md` and `portfolio.md`.
- Shared contracts and the shared ontology (BFO 2020 and CCO, pinned once in the umbrella's
  `.kiro/steering/ontology.md`) are defined in the umbrella. Do not redefine them here.
- Decision points in the governed envelope record a decision trace in the format of the umbrella's
  `decision-traces` spec before the action they decide is committed.
- Tasks tagged for this repo in umbrella specs land here; cite them by spec and task number.
