# SLK DSH integration 4.5.1

SLK's exact-instance Worker launcher and native activity compatibility import.
The upstream is DeepSeek's `deepseek-harness` 0.2.0-rc.2, commit
`639ed015397290b3745d163aafe02ffee4aa3f84`; its original source ZIP and notices are
in `upstream/`. The archived production dependency closure retains the official
npm package lock, licenses and verified Node 24.21.0 Windows runtime.

The only probe implementation is the separately versioned `slk-native-probe`.
The installed layout places `dsh`, `node` and `native-probe` as sibling runtime
directories. `dsh-slk.ps1` uses the bundled Node/public DSH entry and registers
the actual native home idempotently before launch. It does not duplicate a
per-Run timer. Old in-flight runtime/Sessions must not be stopped for an update.

Ordinary use calls the prebuilt SLK package's `scripts/install_local.ps1` once,
then `dsh-slk.cmd <instance-id> <native arguments>`. The former five-file
`install.ps1` overlay is retired: it redirects without changing files instead of
claiming that an incomplete runtime is installed. `rollback.ps1` still supports
previous managed receipts. Native-home registration reports PENDING_RELOAD;
that is not evidence that an already-running host loaded new code.

Developer dependency reconstruction uses the archived exact `package.json` and
`package-lock.json` with `npm ci --omit=dev --ignore-scripts`; required native
prebuilds must be verified before packaging. Do not execute this during Run
preparation. Native probe tests and build live in its own repository; cross-tool
launcher/continuation/installation tests remain in the parent SLK repository.

The initial independent integration repository tag is 1.0.0, not a downgrade
of either SLK's method version or upstream DSH's version.
