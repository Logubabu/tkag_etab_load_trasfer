import sys, json
from ram_cpt import inspect_template
if len(sys.argv)<2:
    print("Usage: python inspect_cpt.py path\\to\\model.cpt")
    raise SystemExit(2)
print(json.dumps(inspect_template(sys.argv[1]),indent=2))
