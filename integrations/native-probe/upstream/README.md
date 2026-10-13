# OCRV native hook input

The source ZIP is `git archive` of official `alibaba/open-code-review` commit
`fabbdb296b0d97e2140ada8d54ca7d6d6d1d7ad4` (tag v1.12.13). It contains its Apache-2.0
LICENSE and original notices. `ocrv-native-probe.patch` changes the original
CLI lifecycle, successful native session-writer open, and the SLK-only final
whole-CELL judgment after settled file groups. It reuses the original runner,
provider/model and MCP; normal OCRV review is unchanged. Offline native tests
are included in the patch, including fully reused groups and inner MCP errors.
The developer build
recipe supplies this repository's single Go module as an explicit local build
dependency; users receive the compiled, clearly modified executable.
