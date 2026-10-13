# SLK OCRV integration 4.5.2

Checker launcher, external-reference reader, decision bridge and exact handoff
adapters. No new character limit is imposed on external original evidence.
Requests and native state retain their exact Run, CELL and Session identity.
Checker hands off only after its work/records are finished and stopped.

The archived Windows runtime is **1.12.13-slkprobe.1.0.1**, developer-built from
official open-code-review commit `fabbdb296b0d97e2140ada8d54ca7d6d6d1d7ad4`.
It is not an unmodified official binary. Its complete original source ZIP,
maintained native integration patch, Go probe dependency and actual build recipe are in
the independent `slk-native-probe` repository and the parent subtree. OCRV's
Apache-2.0 LICENSE accompanies the binary; this integration's MIT LICENSE does
not replace it. MinGit 2.56.0.2 and component licenses are archived as the
process-local fallback when the host has no usable Git.

Ordinary use calls the complete prebuilt SLK installer, then `slk-checker.cmd`.
Account/model configuration remains Owner-controlled; installation does not
replace credentials or select another model. The delivered Python runtime,
transport zipapp and exact integration files are supplied by the same package.
Installing only these adapter source files is not a full SLK installation.

Independent developer inspection can run `python slk_checker_adapter.py --help`
without a model call. Decision/post-D1/recovery commands additionally depend on
the matching installed `slk-transport` product. The parent regression owns
cross-tool handoff, external-reader, rollback and role-host tests; native probe
and OCRV rebuild tests belong to the probe repository. Neither CLI help nor a
fixture test proves a real D1 verdict or live message delivery.

The registered Supervisor can explicitly continue a proved stopped native
Session with `slk-checker.cmd --slk-resume-review`; see the exact source/binding
arguments and rejection conditions in `OCRV-SLK-CONFIGURATION.md`. It reuses
native `--resume`, preserves the original attempt, and never turns an absent
manifest or report into a D1. Legacy implicit recovery switches stay retired.

The repository's first extraction tag is 1.0.0; SLK integration metadata stays
4.5.2 and the modified upstream executable retains its explicit version.
