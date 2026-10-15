# 4.5.2 build.3 tool repositories and prepared outputs

[SLK-TOOL-MODULES.json](SLK-TOOL-MODULES.json) is the release's exact mapping of
11 source prefixes to independent repositories, commits, tags, product versions
and artifact-index hashes. The parent retains the same source and real compiled
outputs at those prefixes through Git subtree history; there is no second edited
copy or submodule checkout required for normal use.

Every independent repository starts its extraction history at tag `1.0.0`.
Repository tags and product versions are separate: this delivery uses SLK
changed tools/templates `4.5.2`, BI/WebBI `1.1.3`, OW helper `1.0.2` and native probe
`1.0.0`. The unchanged DSH integration retains product version `4.5.1`.
Changed module repositories advance without rewriting historical tags;
the exact commits, tags and artifact hashes are in the JSON map.
Build.3 retains the precompiled BI 1.1.3 Windows executable and matching WebBI
in the BI subtree and independent repository. The repaired core, its four Rust
consumers, transport, OCRV integration and Temporal templates advance together.
All four consumers pin the exact new core in their independent manifests and
lockfiles. This is a new sealed five-artifact batch; method identity remains 4.5.2.
The native OCRV executable and seven third-party runtimes are reused only after
hash verification, not described as newly compiled. Project 3.1.0 is deferred.
The shared state core remains the sole SQL/transaction authority. The OW helper
and native probe acquire no engineering write, dispatch or repair authority.

The artifact indices record actual payload hashes, source hashes and build
provenance. Large ZIPs use verifiable parts of at most 64MiB, not paid LFS or
link-only placeholders. Exact upstream source archives, patches, licenses and
compiled outputs remain in Git. See [prepared runtimes](SLK-450-PREPARED-RUNTIMES.md)
for the original runtime preparation and reproduction limitations. The 4.5.2
package reuses the hash-verified 4.5.1 third-party runtime bytes, including local
OCRV `1.12.13-slkprobe.1.0.1`, updates its integration, and rebuilds the five public SLK
artifacts. Its `BUILD-PROVENANCE.json` captures actual inputs before compilation
and seals the produced bytes; package assembly verifies that same batch.

Developer restoration uses the existing parent utility, for example:

```powershell
python scripts/tool_artifacts.py restore --artifacts integrations/dsh/artifacts/windows-x86_64 --output <new-empty-directory>
```

It checks part, complete archive and expanded payload hashes before writing the
new destination. OW's small Python wheel uses its own `BUILD_INPUTS.json` and
wheel digest. Source hashes refer to canonical source bytes; a Windows developer
clone can use `git -c core.autocrlf=false clone <repository>` to avoid local CRLF
checkout transformations. No global Git setting must be changed.

Ordinary users download the single preassembled Windows release and invoke its
existing installer. They do not build these tools, install npm/pip dependencies,
restore developer archives, pull subtrees or repeat development verification
during each Run's preparation. The offline package contains seven runtimes and
the five established public SLK artifacts; data, credentials, native Sessions
and a verified rollback remain outside ordinary managed-code replacement.

Preparation duration is an optimization target only. Neither 10 nor 20 minutes
is a timeout, forced-stop condition or admission gate. Existing OW, Temporal and
member clocks retain their separate explicitly agreed responsibilities.
