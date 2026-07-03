import json
import re

with open("real_captured_data.json", "r", encoding="utf-8") as f:
    data = json.load(f)

print(f"Captured {len(data)} items.")
for i, item in enumerate(data):
    body = item.get("body", "")
    print(f"Item {i} (Type={item.get('type')}, URL={item.get('url')[:60]}): len={len(body)}")
    
    # Check for players
    pas = re.findall(r'\|PA;ID=[^;]+;NA=([^;]+);', body)
    print(f"  Players: {len(pas)}")
    if pas:
        # Match players
        matches = [p for p in pas if any(x in p for x in ["Abada", "Aebischer", "Chaibi", "Muheim", "Bensebaini", "Zakaria", "Kobel", "Benbot"])]
        print(f"  Matched Players: {matches}")
        
    # Search for |MA;
    mas = re.findall(r'\|MA;[^|]+', body)
    if mas:
        print(f"  Markets count: {len(mas)}")
        for m in mas[:15]:
            na = re.search(r'NA=([^;]+)', m)
            if na:
                print(f"    Market Name: {na.group(1)}")
