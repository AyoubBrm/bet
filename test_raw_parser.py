import urllib.request
import json
import re

url = "http://localhost:8002/stats/raw?fixture_id=197033653"
try:
    response = urllib.request.urlopen(url)
    data = json.loads(response.read().decode('utf-8'))
except Exception as e:
    print("Error querying server:", e)
    exit(1)

print(f"Captured {data['responses_captured']} responses.")

for item in data['responses']:
    # The endpoint now returns responses with a preview, but maybe we can query it or it has the full string?
    # Wait, the /stats/raw endpoint in server.py returns:
    # "preview": r[:2000]
    # Ah! The /stats/raw endpoint truncated it to 2000 characters!
    # Let's write a script that does the Playwright fetch directly, captures the full websockets/responses,
    # and dumps the full string to analyze it.
    pass
