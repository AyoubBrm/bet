import re

with open("merged_debug.txt", "r", encoding="utf-8") as f:
    content = f.read()

# Find Rayan Ait-Nouri or Rayan At-Nouri
# Let's search for At-Nouri or Ait-Nouri and print the surrounding 200 chars
for match in re.finditer(r'A.t-Nouri|Abada|Aebischer', content):
    pos = match.start()
    start = max(0, pos - 150)
    end = min(len(content), pos + 150)
    print(f"Match '{match.group(0)}' at {pos}:")
    print(f"  ... {content[start:end]} ...")
    print("-" * 50)
