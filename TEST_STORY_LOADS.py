import json, sys, traceback
from pathlib import Path
from tkinter import Tk, filedialog, simpledialog
from etabs_bridge import EtabsBridge

BASE=Path(__file__).resolve().parent
cfg=json.loads((BASE/"config.json").read_text())

Tk().withdraw()
edb=filedialog.askopenfilename(title="Select ETABS EDB", filetypes=[("ETABS EDB","*.edb")])
if not edb:
    raise SystemExit
b=EtabsBridge(cfg)
try:
    b.open_edb_direct(edb)
    stories=b.stories()
    print("STORIES:")
    for i,s in enumerate(stories):
        print(i, s)
    story=simpledialog.askstring("Story", "Type story name exactly:", initialvalue=stories[0] if stories else "")
    if story:
        print("\nOBJECT COUNTS:", b.story_object_counts(story))
        recs=b.extract_story(story)
        print("LOADS EXTRACTED:", len(recs))
        for r in recs[:50]:
            print(r.kind, r.load_pattern, r.object_name, r.fx, r.fy, r.fz, r.warning)
        print("\nAPI LOG:")
        for x in b.connection_log: print(x)
except Exception:
    traceback.print_exc()
input("\nPress Enter to close...")
