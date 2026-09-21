# LangGraph flow

The orchestrator uses typed Pydantic state at every graph boundary and a
SQLite-backed checkpointer so a run can resume from its stable run ID.

```text
validate recording
      |
capture normalizer (deterministic)
      |
flow planner -------- optional configured model provider
      |
scenario designer --- evidence-limited negative mutations
      |
persist draft plan -> human review/edit/approve
      |
code generation -> compile/test -> bounded repair (maximum 2)
      |
deterministic generation report
```

Exploration is a separate short loop: receive a compact accessibility snapshot,
apply policy/budget/repetition checks, select one structured action, return it
to the extension, and wait for the next snapshot. The browser enforces the
policy again before executing an action.

## Deterministic behavior

Normalization, redaction, filtering, correlation, dependency heuristics,
single-field negative mutations, generation, validation commands, and reports
do not require an LLM. With no model/API key configured, the planner uses the
same evidence-based local rules. Generated tests never contact an LLM.

## Model-provider boundary

If configured, a provider receives only the sanitized normalized summary and a
strict output schema. Environment variables select provider/model and contain
credentials. Provider output is validated; invalid or unsupported assertions
become review notes instead of executable claims.

## Planning rules

- Correlated actions and request order identify candidate user workflows.
- Matching example values infer producer/consumer dependencies.
- `Location`, returned IDs, and later path/query/body use support extraction.
- Repeated GETs with state changes support bounded polling.
- Authentication scenarios require recorded authentication evidence.
- Missing-field/type/identifier negatives each mutate one valid request fact.
- Boundary cases require an observed or documented boundary.
- Uncertain statuses or business outcomes remain explicit review notes.

## Review gate

A draft is editable but cannot generate code. Approval records the reviewed
plan version and timestamp. Any later material edit creates an unapproved
revision. Rejection preserves the plan and records its state for auditability.

## Repair limit

Validation distinguishes generator/framework defects from target behavior.
Only generated-code defects may be repaired automatically, no more than twice,
and repairs may not change approved scenario intent or expected outcomes.

