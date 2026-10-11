# 4.5.0 prepared Windows runtimes

These are pinned development/release inputs, not a compulsory latest-version
policy, per-Run download list or extra preparation gate. Ordinary installation
uses the complete offline package. Account/model configuration, native homes,
Run/Session identities and existing data are not copied from the build machine.

| Runtime | Prepared input / original provenance |
| --- | --- |
| Python | 3.14.8 official Windows x64 embed, archive SHA256 `a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310`; [official release](https://www.python.org/downloads/release/python-3148/) |
| Node | 24.21.0 official Windows x64, archive SHA256 `158f7685b44de51f6c0df1d153526cbcd3e1bc739a8dfc607721cef75de9e541`; [publisher checksums](https://nodejs.org/dist/v24.21.0/SHASUMS256.txt) |
| DSH | Official `@deepseek-ai/dsh` 0.2.0-rc.2, exact upstream `639ed015397290b3745d163aafe02ffee4aa3f84`; original source/license plus actual locked production dependency closure retained in the DSH subtree |
| OCRV | Clearly modified `1.12.13-slkprobe.1.0.0`, upstream `fabbdb296b0d97e2140ada8d54ca7d6d6d1d7ad4`; exact original archive, two-file patch and actual Go build recipe in native-probe subtree; executable SHA256 `7274c6132e78cbaede23347f2ccc2932710c125cec299814e069cc551e9070ca` |
| Temporal | Official CLI 1.9.1 Windows amd64, archive SHA256 `babb65844835045c91fb98930fe10b81de28db80c8c609180473d2c0b18c7589`; [official release](https://github.com/temporalio/cli/releases/tag/v1.9.1) |
| Git fallback | Official MinGit 2.56.0.2, archive SHA256 `da35e72aa21c005a5a0d298cfbae110bc1609a815730ea0dde84b01a1b3cd3be`; process-local fallback only; [official source/releases](https://github.com/git-for-windows/git/releases) |
| Native probe | SLK 1.0.0 helper, one sampler inside each actual native host; helper SHA256 `4caca7c731201ed2e22f4471c0a7546f8bed889a8ad769b7b3c5bc3b7d3e0842`; actual registration is PENDING_RELOAD until that host loads it |

The embedded Python carries the official binary-only five-wheel SDK closure:
`temporalio 1.34.0`, `nexus-rpc 1.4.0`, `protobuf 6.33.6`,
`types-protobuf 7.35.1.20260906`, `typing-extensions 4.15.0`.
Each wheel was checked against its exact official PyPI version metadata;
component license/dist-info records are retained. No copied global venv or
system interpreter/compiler is required by the installed product.

Per-tool `ARTIFACTS.json` records original source/build-input hashes, exact
dependency revisions, actual compressed bytes/parts and every expanded payload
hash. The OW helper uses its existing `BUILD_INPUTS.json` and reproducible wheel.
Compressed parts are real bytes, not LFS pointers. Release ZIPs are convenient
distribution; they do not replace the source-subtree artifacts.

Source hashes use the canonical LF source bytes in Git. For an independent
Windows developer checkout intended for raw-hash comparison, use
`git -c core.autocrlf=false clone <exact-tool-repository>` and the recorded
commit/tag; do not change global Git settings. Ordinary installation consumes
verified prebuilt bytes, so checkout line-ending settings are irrelevant.

Modified OCRV is not described as an official binary. Its Go metadata includes
the actual local module replacement path, so cross-root bit-for-bit rebuilding
is not promised. The recipe and behavior were independently rebuilt/tested.
Windows amd64 was executed; Linux probe code was build-tested only.
