import json, os, tempfile, unittest
from pathlib import Path
from models import LoadRecord
from e2k_reader import E2KReader
from etabs_bridge import EtabsBridge, _strip_ret
from ram_cpt import write_copy, resolve_mapping, inspect_template

BASE = Path(__file__).resolve().parent
CFG_PATH = BASE / 'config.json'

class TestAllFlows(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads(CFG_PATH.read_text())

    def test_e2k_story_extraction(self):
        # Create a synthetic E2K file with Area, Line, and Point loads
        sample_e2k = """$ STORIES - STORY DATA
  STORY "Story1" HEIGHT 3.5 ELEV 3.5
  STORY "Story2" HEIGHT 3.5 ELEV 7.0

$ POINT COORDINATES
  POINT "P1" STORY "Story1" X 0 Y 0 Z 3.5
  POINT "P2" STORY "Story1" X 5 Y 0 Z 3.5
  POINT "P3" STORY "Story1" X 5 Y 5 Z 3.5
  POINT "P4" STORY "Story1" X 0 Y 5 Z 3.5

$ AREA CONNECTIVITY
  AREA "A1" STORY "Story1" POINT1 "P1" POINT2 "P2" POINT3 "P3" POINT4 "P4"

$ LINE CONNECTIVITY
  LINE "F1" STORY "Story1" POINT1 "P1" POINT2 "P2"

$ AREA LOADS
  AREA "A1" LOADPAT "SDL" TYPE "UNIFORM" DIRECTION "GRAVITY" VALUE 2.5
  AREA "A1" LOADPAT "LIVE" TYPE "UNIFORM" DIRECTION "GRAVITY" VALUE 3.0

$ LINE LOADS
  LINE "F1" LOADPAT "SDL" DIRECTION "GRAVITY" VAL1 1.5 VAL2 1.5

$ JOINT LOADS
  POINT "P1" LOADPAT "LIVE" FX 0 FY 0 FZ -10 MX 0 MY 0
"""
        with tempfile.NamedTemporaryFile('w', suffix='.e2k', delete=False) as f:
            f.write(sample_e2k)
            tmp_path = f.name

        try:
            reader = E2KReader(self.cfg).read(tmp_path)
            stories = reader.stories()
            self.assertIn("Story1", stories)
            
            recs = reader.extract_story("Story1")
            self.assertGreaterEqual(len(recs), 4, f"Expected at least 4 load records, got {len(recs)}")
            
            kinds = [r.kind for r in recs]
            self.assertIn("area", kinds)
            self.assertIn("line", kinds)
            self.assertIn("point", kinds)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_strip_ret(self):
        raw1 = (0, 5, ("A1", "A2"))
        ret1, out1 = _strip_ret(raw1)
        self.assertEqual(ret1, 0)
        self.assertEqual(len(out1), 3)

        raw2 = (5, ("A1", "A2"))
        ret2, out2 = _strip_ret(raw2)
        self.assertEqual(ret2, 0)
        self.assertEqual(out2, raw2)

    def test_mapping_rules(self):
        act, ram_type, _ = resolve_mapping("DEAD", self.cfg)
        self.assertEqual(act, "transfer")
        self.assertEqual(ram_type, "other_dead")

        act, ram_type, _ = resolve_mapping("SELF_WEIGHT", self.cfg)
        self.assertEqual(act, "skip")

        act, ram_type, _ = resolve_mapping("LIVE", self.cfg)
        self.assertEqual(act, "transfer")
        self.assertEqual(ram_type, "live_reducible")

    def test_ram_cpt_write(self):
        template_cpt = BASE / "ram_reference_template.cpt"
        if not template_cpt.exists():
            self.skipTest("Template CPT not found")

        records = [
            LoadRecord("ETABS", "Story1", "A1", "SDL", "area", [(0,0), (5,0), (5,5), (0,5)], fx=0, fy=0, fz=-2.5),
            LoadRecord("ETABS", "Story1", "F1", "LIVE", "line", [(0,0), (5,0)], fx=0, fy=0, fz=-1.5, val2_fx=0, val2_fy=0, val2_fz=-1.5),
            LoadRecord("ETABS", "Story1", "P1", "LIVE", "point", [(0,0)], fx=0, fy=0, fz=-10, mx=0, my=0)
        ]

        with tempfile.NamedTemporaryFile(suffix='.cpt', delete=False) as f:
            out_cpt = f.name

        try:
            report = write_copy(template_cpt, out_cpt, records, self.cfg)
            self.assertEqual(report["written"], 3)
            self.assertTrue(os.path.exists(out_cpt))
        finally:
            if os.path.exists(out_cpt):
                os.remove(out_cpt)

if __name__ == '__main__':
    unittest.main()
