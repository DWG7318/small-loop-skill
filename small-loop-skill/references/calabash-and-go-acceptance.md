# SLK Calabash and GO Acceptance

## Definition chain

```text
Owner intent and project evidence
        ↓
Full or Minimum Calabash
        ↓
PROJECT_CALABASH_BASELINE
        ↓
GO_CALABASH_TRACE
        ↓
GO_EVIDENCE_CONTRACT
        ↓
CELL execution and Checker evidence
        ↓
GO-boundary acceptance
```

Calabash defines product meaning. SLK defines one-Worker execution, validation,
rework, recovery, and closure.

## Minimum Calabash

Minimum Calabash is the original structure reduced to:

```text
Grandpa
→ Product Architecture
→ Ontology
```

- Grandpa: purpose, Owner intent, non-negotiable judgments, success direction, and
  product/safety boundaries.
- Product Architecture: users/roles, entries, core journey, surfaces, responsibilities,
  data/evidence flow, external capabilities, and outcomes.
- Ontology: canonical concepts, names, relationships, ownership, states, lifecycles,
  and distinctions that must not collapse.

It omits Contract, Policy, Workflow, Action Catalog, Adapter, and Eval & Audit. An
omitted layer must be derived and frozen before a GO that depends on it executes.

## Calabash applicability

Product-affecting work requires Full or Minimum Calabash. A narrow technical
`CALABASH_EXEMPTION` is valid only when no user behavior, product meaning, role,
journey, state, permission, action, or acceptance can change and a frozen technical
contract uniquely defines the result.

Supervisor responsibility establishes a missing baseline from authoritative evidence.
It may reconcile terms and record uncertainty, but cannot invent Owner intent or
choose between materially different product meanings.

## GO trace schema

```text
GO_CALABASH_TRACE
GO_ID
GO_VERSION
BASELINE_ID
BASELINE_VERSION
BASELINE_HASH
GRANDPA_REFERENCES
PRODUCT_ARCHITECTURE_REFERENCES
ONTOLOGY_REFERENCES
FULL_LAYER_REFERENCES
DERIVED_OUTCOME_CLAIM
VERIFICATION_IMPLICATIONS
INVALIDATION_RULE
```

## GO evidence contract

A valid criterion cites:

1. one baseline clause;
2. a GO outcome derived from it;
3. an observable fact;
4. required evidence;
5. pass/fail and counter-evidence rules.

Checker applies the contract; it does not invent product success.

## Failure classification

Classify before modification:

```text
IMPLEMENTATION_DEFECT
GO_CONTRACT_DEFECT
CALABASH_TRACE_INVALID
CALABASH_DEFINITION_BLOCKED
CALABASH_UPGRADE_REQUIRED
GO_EVIDENCE_GAP
PRODUCT_EFFECT_GAP
```

An implementation defect routes to Worker rework. A product-effect gap returns to
Calabash analysis rather than unbounded editing.

## Invalidation

A trace or verdict becomes stale after a material change to Grandpa, Product
Architecture, Ontology, relevant Full layer, GO outcome, candidate artifact, or
environment identity. Version the new baseline/trace and preserve history.
