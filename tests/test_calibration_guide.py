import json
import tempfile
import unittest
from pathlib import Path

from prd_assistant import draft, pipeline

CALIBRATION = Path(__file__).resolve().parent.parent / "calibration" / "calibration.json"


class GuideCalibrationTests(unittest.TestCase):
    def test_golden_repos_keep_their_recorded_guide_summary(self):
        spec = json.loads(CALIBRATION.read_text())
        for name, entry in spec["repos"].items():
            if "expect_guide" not in entry:
                continue
            with self.subTest(repo=name):
                if not Path(entry["path"]).is_dir():
                    self.skipTest(f"{entry['path']} not present")
                with tempfile.TemporaryDirectory() as tmp:
                    facts, result = pipeline.run(entry["path"], use_adapters=entry["use_adapters"])
                    pipeline.write_outputs(tmp, facts, result)
                    summary = draft.guide_prepare(entry["path"], tmp, today="2026-01-01")
                self.assertEqual(summary, entry["expect_guide"])


if __name__ == "__main__":
    unittest.main()
