"""Retired output-format/budget recovery launcher; historical evidence is untouched."""
import json
import sys


def main() -> int:
    print(json.dumps({"status": "retired", "error_code": "OUTPUT_REVIEW_RECOVERY_RETIRED",
        "message": "Deliver preserved output using its exact registered transport; do not rerun review or infer D1."}))
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
