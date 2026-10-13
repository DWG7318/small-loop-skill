"""Read-only native durable-Turn stop proof; no DSH constructor or boot."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

from .adapters.dsh import DshAdapter
from .contracts import Endpoint
from .process import windows_no_window_kwargs


# The shipped rc.2 backend validates concatenated checksummed frames and the
# current Session format. Calling this pure parser does not open a storage
# service, acquire a writer lease, recover a log, or instantiate an Agent.
_READ_STOP_PROOF = r"""
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
try {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const canonical = value => path.resolve(value).toLowerCase();
  const regular = (value, directory) => {
    const stat = fs.lstatSync(value);
    if (stat.isSymbolicLink() || (directory ? !stat.isDirectory() : !stat.isFile()) ||
        canonical(fs.realpathSync(value)) !== canonical(value)) throw Error('alternate path');
  };
  regular(input.sessions, true);
  const matches = [];
  for (const project of fs.readdirSync(input.sessions, {withFileTypes:true})) {
    if (!project.isDirectory() || project.isSymbolicLink()) continue;
    const projectPath = path.join(input.sessions, project.name);
    const directory = path.join(projectPath, input.session_id);
    if (!fs.existsSync(directory)) continue;
    regular(projectPath, true);
    regular(directory, true);
    matches.push(directory);
  }
  if (matches.length !== 1) throw Error('missing or ambiguous exact Session');
  const directory = matches[0];
  const generations = fs.readdirSync(directory).filter(name => /^session\.v\d+\.jsonl(?:\.zstd)?$/.test(name));
  if (generations.length !== 1 || generations[0] !== 'session.v4.jsonl.zstd')
    throw Error('unsupported or ambiguous native Session format');
  const file = path.join(directory, generations[0]);
  regular(file, false);
  const before = fs.statSync(file, {bigint:true});
  const bytes = fs.readFileSync(file);
  const {default: Native} = await import(pathToFileURL(input.parser).href);
  const parsed = await Native.prototype.readZstdPrefix.call({}, bytes);
  const header = parsed.meta;
  if (parsed.tornTruncateTo !== undefined || parsed.recoveredTail.length !== 0 ||
      header.version !== 4 || header.id !== input.session_id || canonical(header.cwd) !== canonical(input.cwd))
    throw Error('native Session identity or tail is unproved');
  let open = null, lastEnd = null;
  for (const [seq, event] of parsed.events.entries()) {
    if (event.seq !== seq) throw Error('noncontiguous native Session');
    if (event.type === 'turn/start') {
      if (open !== null || !Number.isSafeInteger(event.data.turn) || event.data.turn < 1)
        throw Error('invalid native Turn start');
      open = event.data.turn;
    } else if (event.type === 'turn/end') {
      if (open === null || event.data.turn !== open) throw Error('unmatched native Turn end');
      open = null;
      lastEnd = event;
    }
  }
  if (open !== null || lastEnd === null) throw Error('native Turn is open or absent');
  const after = fs.statSync(file, {bigint:true});
  if (before.size !== after.size || before.mtimeNs !== after.mtimeNs || before.ino !== after.ino ||
      !bytes.equals(fs.readFileSync(file))) throw Error('native Session changed during query');
  console.log(JSON.stringify({status:'NATIVE_SESSION_STOPPED', session_id:input.session_id,
    path:path.resolve(file), sha256:createHash('sha256').update(bytes).digest('hex'),
    last_seq:parsed.events.at(-1).seq, turn:lastEnd.data.turn,
    turn_end_seq:lastEnd.seq, turn_ended_at:new Date(lastEnd.time).toISOString()}));
} catch {
  console.log(JSON.stringify({status:'NATIVE_SESSION_STOP_UNPROVED'}));
  process.exitCode = 3;
}
"""


def native_session_stopped(endpoint: Endpoint | Mapping[str, Any]) -> dict[str, Any]:
    """Prove a closed original Turn from the exact bundled v4 native log.

    Launcher disappearance is checked separately by the continuation host.
    Unsupported legacy launchers/formats fail closed, without starting DSH or
    rewriting its disposable projection cache or append-only Session log.
    """
    endpoint = endpoint if isinstance(endpoint, Endpoint) else Endpoint.from_dict(endpoint)
    DshAdapter().validate_address(endpoint)
    command = endpoint.address["command"]
    launcher = Path(command[0])
    bundle = None
    if len(command) == 1 and launcher.is_absolute() and launcher.name.casefold() == "dsh-slk.cmd":
        if launcher.parent.name.casefold() == "bin":
            bundle = launcher.parent.parent
        elif launcher.parent.name.casefold() == "dsh" and launcher.parent.parent.name.casefold() == "runtime":
            bundle = launcher.parents[2]
    if (bundle is None or bundle.name.casefold() != "slk" or bundle.parent.name.casefold() != "tools"
        or not launcher.is_file() or not (bundle / "scripts/local_package_metadata.py").is_file()):
        raise ValueError("native stop proof requires the registered bundled DSH launcher")
    node = bundle / "runtime/node/node.exe"
    parser = bundle / "runtime/dsh/node_modules/@deepseek-ai/dsh-session-persistence-jsonl/lib/index.js"
    if not node.is_file() or not parser.is_file():
        raise ValueError("bundled native Session parser is unavailable")
    session = endpoint.address["session_id"]
    if not isinstance(session, str) or Path(session).name != session or any(c in session for c in '/\\:'):
        raise ValueError("native stop proof requires one exact registered Session")
    sessions = Path(endpoint.address["runtime_root"]) / "runs" / endpoint.address["instance_id"] / "home/sessions"
    request = {"sessions": str(sessions), "session_id": session, "cwd": endpoint.address["cwd"], "parser": str(parser)}
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() not in {"NODE_OPTIONS", "NODE_PATH", "SLK_ROLE_CREDENTIAL", "SLK_OVERWATCHER_CREDENTIAL"}}
    try:
        result = subprocess.run([str(node), "--input-type=module", "-e", _READ_STOP_PROOF],
            input=json.dumps(request), text=True, encoding="utf-8", capture_output=True,
            env=environment, timeout=30, **windows_no_window_kwargs())
        proof = json.loads(result.stdout)
        if result.returncode != 0 or proof.get("status") != "NATIVE_SESSION_STOPPED":
            raise ValueError("native Session has no unique intact closed durable Turn proof")
        return proof
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, AttributeError) as exc:
        raise ValueError("native Session stop proof is unavailable") from exc
