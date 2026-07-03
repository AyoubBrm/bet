with open("intercepted_html_4.html", "r", encoding="utf-8") as f:
    content = f.read()

keywords = ["tackles", "tacles", "passes", "tir", "shots", "joueur", "player", "Suisse", "Algérie", "Switzerland", "Algeria"]

print(f"HTML Length: {len(content)}")
for kw in keywords:
    count = content.lower().count(kw.lower())
    print(f"Keyword '{kw}': {count} occurrences")
