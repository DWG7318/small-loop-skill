#!/usr/bin/env python3
"""Compatibility wrapper for the packaged SLK role Eval validator."""

from slk_transport.role_eval import (
    EvalError,
    load_pack,
    main,
    pack_sha256,
    validate_response,
)

__all__ = ["EvalError", "load_pack", "pack_sha256", "validate_response"]


if __name__ == "__main__":
    raise SystemExit(main())
