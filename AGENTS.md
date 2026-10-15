# SLK release conventions

- Owner decision, 2026-10-15: publish SLK with plain `major.minor.patch` versions and `vX.Y.Z` tags. Increment the patch version for a new repair release; do not use `build` suffixes as a substitute.
- Method, BI and independent tool versions are separate identities. Preserve historical Run versions and immutable published evidence; adopting a new method in an existing Run is a separate authorized action.
- Ordinary installation uses verified precompiled artifacts, never end-user compilation. Do not change the deferred 3.x project as part of a 4.x release.
