from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("command")
parser.add_argument("--request", required=True, type=Path)
parser.add_argument("--sha256", required=True)
args = parser.parse_args()
if args.command != "checker-recover-worker":
    sys.exit(7)
if "SLK_ROLE_CREDENTIAL" in os.environ or "SLK_OVERWATCHER_CREDENTIAL" in os.environ:
    sys.exit(8)
if not all(
    os.environ.get(name)
    for name in (
        "SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID",
        "SLK_OCRV_RECOVERY_INVOCATION_ID",
        "SLK_OCRV_RECOVERY_ENDPOINT_VERSION",
    )
):
    sys.exit(9)
request = json.loads(args.request.read_text(encoding="utf-8"))
result = {"status": "CHECKER_D1_RECORDED", "request_sha256": args.sha256}
Path(request["result_path"]).write_text(json.dumps(result), encoding="utf-8")
print(json.dumps(result))
