import json
from pathlib import Path
from e2k_reader import E2KReader

p = Path("D:/Projects/TKAG/Floor_Exporter/sample_models/P-796-ULT-V22.3-UPDATED-01-06-2026.$et")
cfg = json.loads(Path('config.json').read_text())
r = E2KReader(cfg).read(str(p))

print("POINT COORDINATES LINES:")
for s, lines in r.sections.items():
    if 'POINT COORD' in s or 'JOINT COORD' in s:
        for line in lines[:15]:
            print("  ", line)
