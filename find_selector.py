from bs4 import BeautifulSoup

with open("intercepted_html_4.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

# Find elements containing "Player Tackles"
tackles_el = soup.find_all(text=lambda t: t and "Player Tackles" in t)
for el in tackles_el:
    print(f"Parent: {el.parent.name}, Class: {el.parent.get('class')}")
    # Walk up parent chain
    curr = el.parent
    for _ in range(5):
        if curr:
            print(f"  -> {curr.name} | class={curr.get('class')} | id={curr.get('id')}")
            curr = curr.parent
