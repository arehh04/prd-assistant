import json
import unittest
from pathlib import Path

from prd_assistant import gate, pipeline

CALIBRATION = Path(__file__).resolve().parent.parent / "calibration" / "calibration.json"


class CalibrationTests(unittest.TestCase):
    def test_golden_repos_keep_their_recorded_results(self):
        spec = json.loads(CALIBRATION.read_text())
        for name, entry in spec["repos"].items():
            with self.subTest(repo=name):
                if not Path(entry["path"]).is_dir():
                    self.skipTest(f"{entry['path']} not present")
                _, result = pipeline.run(entry["path"], use_adapters=entry["use_adapters"])
                self.assertEqual(gate.summary(result), entry["expect"])


if __name__ == "__main__":
    unittest.main()
