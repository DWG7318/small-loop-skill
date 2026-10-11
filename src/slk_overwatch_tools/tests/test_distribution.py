"""Build contract tests use only the standard library and this standalone prefix."""
from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def builder(self):
        source = ROOT / "build_wheel.py"
        self.assertTrue(source.is_file(), "the standalone stdlib wheel builder is not implemented")
        spec = importlib.util.spec_from_file_location("standalone_ow_builder", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_wheel_is_reproducible_and_contains_only_runtime_package_and_metadata(self):
        builder = self.builder()
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / "a", Path(directory) / "b"
            name = builder.build_wheel(str(a))
            builder.build_wheel(str(b))
            self.assertEqual((a / name).read_bytes(), (b / name).read_bytes())
            with zipfile.ZipFile(a / name) as wheel:
                runtime = {item for item in wheel.namelist() if not ".dist-info/" in item}
                self.assertEqual(runtime, {"slk_overwatch_tools/__init__.py", "slk_overwatch_tools/cadence.py",
                                           "slk_overwatch_tools/native_records.py"})
                metadata = wheel.read("slk_overwatch_tools-1.0.0.dist-info/METADATA").decode()
                self.assertIn("Version: 1.0.0", metadata)
                self.assertNotIn("Requires-Dist:", metadata)
                self.assertFalse(any("slk_transport" in item for item in wheel.namelist()))

    def test_wheel_record_matches_original_bytes_and_requires_no_external_builder(self):
        builder = self.builder()
        with tempfile.TemporaryDirectory() as directory:
            name = builder.build_wheel(directory)
            with zipfile.ZipFile(Path(directory) / name) as wheel:
                record = "slk_overwatch_tools-1.0.0.dist-info/RECORD"
                rows = list(csv.reader(io.StringIO(wheel.read(record).decode())))
                self.assertEqual({row[0] for row in rows}, set(wheel.namelist()))
                for path, digest, size in rows:
                    if path == record:
                        self.assertEqual((digest, size), ("", ""))
                        continue
                    content = wheel.read(path)
                    expected = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
                    self.assertEqual((digest, int(size)), ("sha256=" + expected, len(content)))
                self.assertEqual(builder.get_requires_for_build_wheel(), [])

    def test_build_input_manifest_is_about_inputs_not_a_circular_commit_or_self_hash(self):
        builder = self.builder()
        with tempfile.TemporaryDirectory() as directory:
            builder.main(["--output", directory])
            manifest = json.loads((Path(directory) / "BUILD_INPUTS.json").read_text())
            self.assertEqual(manifest["version"], "1.0.0")
            for relative, digest in manifest["source_sha256"].items():
                self.assertEqual(digest, hashlib.sha256((ROOT / relative).read_bytes()).hexdigest())
            self.assertNotIn("BUILD_INPUTS.json", manifest["source_sha256"])
            self.assertNotIn("commit", manifest)
            self.assertEqual(manifest["artifact_sha256"], hashlib.sha256(
                (Path(directory) / manifest["artifact"]).read_bytes()).hexdigest())

    def test_build_input_manifest_uses_canonical_lf_bytes(self):
        builder = self.builder()
        with tempfile.TemporaryDirectory() as directory:
            builder.main(["--output", directory])
            content = (Path(directory) / "BUILD_INPUTS.json").read_bytes()
            self.assertTrue(content.endswith(b"\n"))
            self.assertNotIn(b"\r", content, "Git text normalization must not change the indexed build manifest")


if __name__ == "__main__":
    unittest.main()
