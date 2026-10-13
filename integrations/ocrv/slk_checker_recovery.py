"""Explicit, source-bound native --resume; old implicit recovery stays retired."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import uuid


@contextmanager
def _environment(values):
    old = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def resume(args):
    import slk_checker_adapter as adapter
    adapter._transport_import_path()
    from slk_transport import worker_completion as wc
    from slk_transport.adapters.ocrv import _native_start_context
    from slk_transport.contracts import DeliveryResult, RESULT_SCHEMA, parse_delivery
    from slk_transport.evidence import Attempt
    from slk_transport.native_activity import process_creation_time, validate_native_start
    from slk_transport.native_ocrv import ocrv_resume_identity
    from slk_transport.role_host import load_role_host

    if not args.binding.is_absolute() or adapter._sha256(args.binding) != args.sha256:
        raise ValueError("original RoleHost binding hash changed")
    if not args.source_attempt.is_absolute() or str(uuid.UUID(args.invocation_id)) != args.invocation_id:
        raise ValueError("resume requires an absolute source and one canonical invocation UUID")
    source = args.source_attempt
    endpoint = adapter._read_json(source / "endpoint.json")
    parsed = parse_delivery(endpoint, adapter._read_json(source / "envelope.json"))
    with _environment({"SLK_TRANSPORT_ROLE_HOST": str(args.binding), "SLK_TRANSPORT_ROLE_HOST_SHA256": args.sha256}):
        host = load_role_host(endpoint)
        if host is None:
            raise ValueError("resume requires the exact prepared Checker Host")
        envelope = parsed.envelope
        ocrv_resume_identity(source, host, envelope)
        source = source.resolve()
        supervisor = host.endpoint("supervisor")
        if (supervisor["adapter"] == "codex-app-server"
            and os.environ.get("CODEX_THREAD_ID") != supervisor["address"]["thread_id"]):
            raise ValueError("only the registered Supervisor may resume this Checker")
        host.inspect_recovery_authority(supervisor["role_instance_id"])
        corrections = source / "review-corrections"
        root = corrections / args.invocation_id
        if root.exists():
            ocrv_resume_identity(root, host, envelope)
            marker = adapter._read_json(root / "ocrv-resume.json")
            if marker["resume_session_id"] != args.resume_session:
                raise ValueError("repeat recovery changed the original native Session")
            if (root / "role-host/checker-decision.json").is_file():
                return host.complete_checker_handoff(root)
            response = root / "resume-result.json"
            result = adapter._read_json(response) if response.is_file() else None
            if result is not None and result.get("source_attempt") != str(root):
                raise ValueError("saved recovery response changed source")
            if result is not None and result.get("output_delivery", {}).get("status") == "OUTPUT_DELIVERED":
                return result
            # A coordinator may exit after native sealing but before recording
            # its response. Consume the existing seal; never manufacture one.
            receipt = root / "native-start.received.json"
            start = validate_native_start(receipt, adapter=endpoint["adapter"], run_id=envelope.run_id,
                cell_id=envelope.cell_id, message_id=envelope.message_id, request_sha256=envelope.payload_sha256,
                native_request_sha256=adapter._sha256(root / "ocrv-request.json"))
            terminals = [root / name for name in ("completed.json", "failed.json") if (root / name).is_file()]
            if len(terminals) != 1 or validate_native_start(root / "started.json") != start:
                raise ValueError("recovery response has no unique original native seal")
            terminal = DeliveryResult.from_dict(adapter._read_json(terminals[0]))
            review = adapter._read_json(root / "ocrv-result.json")
            if ((terminal.run_id, terminal.message_id, terminal.adapter, terminal.status) !=
                (envelope.run_id, envelope.message_id, endpoint["adapter"], terminals[0].stem)
                or review.get("review_invocation_id") != start["native_task"]["id"]
                or any(review.get(key) != value for key, value in {
                    "run_id": envelope.run_id, "cell_id": envelope.cell_id,
                    "request_sha256": start["native_request_sha256"]}.items())):
                raise ValueError("recovery response changed its original native result")
            from slk_transport.native_ocrv import require_stopped_ocrv
            require_stopped_ocrv(receipt, start)
            output = host.complete(root)
            # Keep the first response (if any) as history. Existing transport
            # owns message de-duplication of this same public-report suffix.
            return {"status": "OCRV_REVIEW_INCOMPLETE", "source_attempt": str(root),
                "native_result": terminal.to_dict(), "output_delivery": output}
        request = source / "ocrv-request.json"
        receipt = source / "native-start.received.json"
        context = _native_start_context(parsed.endpoint, envelope, adapter._sha256(request))
        saved = adapter._resume_preflight((receipt, context), request, args.resume_session)
        if saved is not None:
            # D1 remains a fact even if its original result/terminal is absent.
            # Only the existing Host suffix may inspect/deliver it; no new seal.
            return host.complete_checker_handoff(source)
        projection = host._boundary(envelope)
        if projection.get("summary", {}).get("state") in {"closed", "archived", "paused", "pause_requested"}:
            raise ValueError("Run lifecycle does not allow a new native review activation")
        native_source = adapter._read_json(source / "ocrv-native-source.json")
        repository = Path(adapter._read_json(request)["repository"])
        if adapter._session_directory(repository, adapter._child_environment()).resolve() != Path(native_source["session_directory"]).resolve():
            raise ValueError("registered native runtime no longer addresses the original Session directory")
        # One child activation per source, atomically claimed before any spawn.
        # A later continuation uses that child's verified source/checkpoint.
        corrections.mkdir(exist_ok=False)
        root.mkdir()
        attempt = Attempt(root)
        for name in ("endpoint.json", "envelope.json", "ocrv-request.json"):
            attempt.write_bytes_once(name, (source / name).read_bytes())
        attempt.write_json_once("ocrv-resume.json", {
            "schema_version": "slk.ocrv-native-resume/v1", "invocation_id": args.invocation_id,
            "original_source": str(source), "original_source_sha256": host._source_sha256(source, "checker"),
            "binding_sha256": host.digest, "resume_session_id": args.resume_session,
            "coordinator_process": {"pid": os.getpid(), "creation_time": process_creation_time(os.getpid())}})
        attempt.write_json_once("accepted.json", {"status": "NATIVE_RESUME_REQUESTED", "invocation_id": args.invocation_id})
        result_path = root / "ocrv-result.json"
        with _environment({"SLK_NATIVE_START_RECEIPT": str(root / "native-start.received.json"),
                           "SLK_NATIVE_START_CONTEXT": json.dumps(context),
                           "OCRV_SLK_RUNTIME_ROOT": endpoint["address"]["runtime_root"]}):
            code = adapter.run(root / "ocrv-request.json", result_path,
                invocation_override=args.invocation_id, resume_session=args.resume_session, resume_origin=source)
        start = validate_native_start(root / "started.json", adapter=endpoint["adapter"],
            run_id=envelope.run_id, cell_id=envelope.cell_id, message_id=envelope.message_id,
            request_sha256=envelope.payload_sha256, native_request_sha256=context["native_request_sha256"])
        terminal = DeliveryResult(RESULT_SCHEMA, envelope.message_id, envelope.run_id, endpoint["adapter"],
            "completed" if code == 0 else "failed", {"exit_code": code,
                "review_invocation_id": start["native_task"]["id"], "native_started": True},
            None if code == 0 else "OCRV_EXIT_NONZERO", ("started.json", "ocrv-result.json", "ocrv-resume.json"))
        attempt.write_json_once(terminal.status + ".json", terminal.to_dict())
        try:
            output = host.complete(root)
        except (ValueError, OSError) as exc:
            output = {"status": "HOST_HANDOFF_FAILED", "error_code": getattr(exc, "error_code", type(exc).__name__)}
        result = {"status": output["status"] if output.get("status") == "CHECKER_D1_RECORDED" else "OCRV_REVIEW_INCOMPLETE",
            "source_attempt": str(root), "native_result": terminal.to_dict(), "output_delivery": output}
        attempt.write_json_once("resume-result.json", result)
        return result


def main() -> int:
    if "--slk-resume-review" in sys.argv[1:]:
        parser = argparse.ArgumentParser(description="Explicit same-Checker native checkpoint continuation.")
        parser.add_argument("--slk-resume-review", action="store_true", required=True)
        parser.add_argument("--binding", type=Path, required=True)
        parser.add_argument("--sha256", required=True)
        parser.add_argument("--source-attempt", type=Path, required=True)
        parser.add_argument("--resume-session", required=True)
        parser.add_argument("--invocation-id", required=True)
        args = parser.parse_args()
        try:
            result = resume(args)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            print(json.dumps({"status": "REJECTED", "error_code": "OCRV_RESUME_UNPROVEN", "message": str(exc)}))
            return 4
        print(json.dumps(result, ensure_ascii=False))
        output = result.get("output_delivery", result)
        return 0 if output.get("status") == "CHECKER_D1_RECORDED" and output.get("handoff", {}).get("status") in {
            "OWNED_HANDOFF_COMMITTED", "OWNED_HANDOFF_ALREADY_COMMITTED"} else 3
    print(json.dumps({"status": "retired", "error_code": "OUTPUT_REVIEW_RECOVERY_RETIRED",
        "message": "Deliver preserved output using its exact registered transport; do not rerun review or infer D1."}))
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
