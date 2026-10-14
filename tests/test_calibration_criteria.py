import json
import tempfile
import unittest
from pathlib import Path

from prd_assistant import criteria, draft, pipeline

CALIBRATION = Path(__file__).resolve().parent.parent / "calibration" / "calibration.json"


class CriteriaCalibrationTests(unittest.TestCase):
    def test_golden_repos_keep_their_recorded_bank_counts(self):
        spec = json.loads(CALIBRATION.read_text())
        for name, entry in spec["repos"].items():
            if "expect_criteria" not in entry:
                continue
            with self.subTest(repo=name):
                if not Path(entry["path"]).is_dir():
                    self.skipTest(f"{entry['path']} not present")
                with tempfile.TemporaryDirectory() as tmp:
                    facts, result = pipeline.run(entry["path"], use_adapters=entry["use_adapters"])
                    pipeline.write_outputs(tmp, facts, result)
                    draft.dev_prepare(entry["path"], tmp, today="2026-01-01")
                    read = lambda n: json.loads((Path(tmp) / "dev" / n).read_text())
                    bank = criteria.build_bank(facts, read("roles.json"), read("form_rules.json"), read("error_messages.json"))
                got = {"counts": bank["counts"], "universe": {k: len(v) for k, v in bank["universe"].items()},
                       "truncated": bank["truncated"]}
                self.assertEqual(got, entry["expect_criteria"])


if __name__ == "__main__":
    unittest.main()
