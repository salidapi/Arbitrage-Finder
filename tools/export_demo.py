"""Print clearly synthetic, current-timestamp import data; never fetches live prices."""
import json
from arbscanner.demo import demo_quotes

print(json.dumps({"quotes": [q.model_dump(mode="json") for q in demo_quotes()]}, indent=2))
