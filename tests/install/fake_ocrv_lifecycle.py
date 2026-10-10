"""Offline native/MCP process fixture: a completed D1 otherwise keeps reviewing."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

if '--wrap' in sys.argv:
    raise SystemExit(subprocess.call([sys.executable, __file__, *[a for a in sys.argv[1:] if a != '--wrap']],
        stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)))

receipt = Path(os.environ['SLK_NATIVE_START_RECEIPT'])
deadline = time.monotonic() + 3
while not receipt.is_file() and time.monotonic() < deadline:
    time.sleep(0.01)
bridge = subprocess.Popen([sys.executable, '-B', os.environ['FAKE_CHECKER_BRIDGE'],
    '--transport', os.environ['FAKE_CHECKER_TRANSPORT']], stdin=subprocess.PIPE,
    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
    creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
try:
    bridge.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
        'params': {'name': 'slk_checker_decide', 'arguments': {'verdict': os.environ.get('FAKE_VERDICT', 'PASS')}}}) + '\n')
    bridge.stdin.flush()
    response = bridge.stdout.readline()
    print('D1 reply received: ' + response, flush=True)
    print('partial original native log', file=sys.stderr, flush=True)
    # No native whole-review completion exists for an ordinary MCP response.
    if '--natural-exit' not in sys.argv:
        time.sleep(4)
finally:
    bridge.stdin.close()
    bridge.wait(timeout=2)
raise SystemExit(9)
