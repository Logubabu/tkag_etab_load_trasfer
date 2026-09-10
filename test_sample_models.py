import json, os, sys, unittest
from pathlib import Path
from models import LoadRecord
from e2k_reader import E2KReader
from etabs_bridge import EtabsBridge, _strip_ret
from ram_cpt import write_copy, resolve_mapping

BASE = Path(__file__).resolve().parent
CFG_PATH = BASE / 'config.json'
SAMPLE_MODELS_DIR = Path("D:/Projects/TKAG/Floor_Exporter/sample_models")

class TestSampleModels(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads(CFG_PATH.read_text())

    def test_e2k_sample_models(self):
        if not SAMPLE_MODELS_DIR.exists():
            self.skipTest(f"Sample models directory not found at {SAMPLE_MODELS_DIR}")

        e2k_files = list(SAMPLE_MODELS_DIR.glob("*.e2k")) + list(SAMPLE_MODELS_DIR.glob("*.$et"))
        self.assertGreater(len(e2k_files), 0, "No .e2k or .$et sample files found")

        for fpath in e2k_files:
            with self.subTest(file=fpath.name):
                print(f"\n--- Testing E2K Reader on: {fpath.name} ---")
                reader = E2KReader(self.cfg).read(str(fpath))
                stories = reader.stories()
                print(f"Detected {len(stories)} stories: {stories}")
                self.assertGreater(len(stories), 0, f"No stories detected in {fpath.name}")

                total_loads_found = 0
                for st in stories:
                    recs = reader.extract_story(st)
                    if recs:
                        print(f"  Story '{st}': {len(recs)} loads extracted (kinds: {set(r.kind for r in recs)})")
                        total_loads_found += len(recs)
                print(f"Total loads extracted across all stories in {fpath.name}: {total_loads_found}")

if __name__ == '__main__':
    unittest.main()
