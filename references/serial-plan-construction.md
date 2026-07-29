# Serial Plan Construction

Derive GO outcomes from the frozen LCCoding Run Feature, not from files, commands,
modules, or business workflow steps. Merge artificial micro-GOs, split multi-claim
GOs, prove one canonical successor at every transition, cover the full Run Feature,
and freeze `SERIAL_BASELINE`.

The Serial Plan carries scheduling summaries and immutable
`go_contract_ref + go_contract_version + go_contract_hash` bindings. Complete GO
meaning remains in the referenced frozen GO Contract.

`current_go_id` and `active_go_id` are singular Run pointers, not lifecycle states.
