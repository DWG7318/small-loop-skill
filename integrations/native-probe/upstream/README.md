# OCRV native hook input

The source ZIP is `git archive` of official `alibaba/open-code-review` commit
`fabbdb296b0d97e2140ada8d54ca7d6d6d1d7ad4` (tag v1.12.13). It contains its Apache-2.0
LICENSE and original notices. `ocrv-native-probe.patch` changes only the original
CLI lifecycle and successful native session-writer open. The developer build
recipe supplies this repository's single Go module as an explicit local build
dependency; users receive the compiled, clearly modified executable.
