from bs4 import BeautifulSoup

with open("intercepted_html_4.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

pods = soup.find_all(class_="gl-MarketGroupPod")
for i, pod in enumerate(pods):
    print(f"--- Pod {i} ---")
    print(pod.prettify()[:1000]) # Print first 1000 chars of each pod
