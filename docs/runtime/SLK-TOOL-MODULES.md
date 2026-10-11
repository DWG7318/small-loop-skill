# 4.5.0 tool repositories and prepared outputs

[SLK-TOOL-MODULES.json](SLK-TOOL-MODULES.json) is the release's exact mapping of
11 source prefixes to independent repositories, commits, tags, product versions
and artifact-index hashes. The parent retains the same source and real compiled
outputs at those prefixes through Git subtree history; there is no second edited
copy or submodule checkout required for normal use.

Every independent repository starts its extraction history at tag `1.0.0`.
That tag does not downgrade existing products: SLK tools/templates are `4.5.0`,
BI/WebBI are `1.1.1`, and the new OW helper/native probe products are `1.0.0`.
OW's developer build-manifest newline correction uses repository repair tag
`1.0.1`; the original `1.0.0` remains intact and its runtime wheel is unchanged.
The shared state core remains the sole SQL/transaction authority. The OW helper
and native probe acquire no engineering write, dispatch or repair authority.

The artifact indices record actual payload hashes, source hashes and build
provenance. Large ZIPs use verifiable parts of at most 64MiB, not paid LFS or
link-only placeholders. Exact upstream source archives, patches, licenses and
compiled outputs remain in Git. See [prepared runtimes](SLK-450-PREPARED-RUNTIMES.md)
for the executed platform and reproduction limitations.

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
