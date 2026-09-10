import json, sys, traceback
from pathlib import Path
from etabs_bridge import EtabsBridge

BASE=Path(__file__).resolve().parent
cfg=json.loads((BASE/"config.json").read_text())

print("ETABS API CONNECTION TEST")
print("="*60)
b=EtabsBridge(cfg)
try:
    b.connect(start_if_needed=True)
    print("SUCCESS")
    print("Connection method:", b.connection_method)
    try:
        print("Model file:", b.sap.GetModelFilename())
    except Exception as e:
        print("Model filename check:", e)
    try:
        print("Stories:", b.stories())
    except Exception as e:
        print("Story test failed:", e)
except Exception as e:
    print("FAILED")
    print(e)
finally:
    print("\nDIAGNOSTICS")
    print(json.dumps(b.diagnostics(), indent=2))
    input("\nPress Enter to close...")
