"""Scrape dish names + prices from the existing menu so nothing is invented."""
import html as htmlmod
import json
import re
import urllib.request

URL = "https://menudigital.ir/adel"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

req = urllib.request.Request(URL, headers=UA)
raw = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")

TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")


def clean(fragment: str) -> str:
    text = TAG.sub(" ", fragment)
    text = htmlmod.unescape(text)
    text = text.replace("\u200c", "").replace("\u200f", "")
    return WS.sub(" ", text).strip()


def fa_to_int(text: str):
    """'740,000' / '۷۴۰٬۰۰۰' / '740 000 تومان' -> 740000"""
    digits = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    digits = re.sub(r"[^\d]", "", digits)
    return int(digits) if digits else None


# Category headings, in nav order.
nav = re.findall(r'<a href="#(mdg-home-section-\d+)"[^>]*>.*?'
                 r'<span[^>]*>(.*?)</span>.*?<b[^>]*>(.*?)</b>', raw, re.S)
order, en_of = {}, {}
for sec_id, fa, en in nav:
    order[sec_id] = clean(fa)
    en_of[sec_id] = clean(en)

# Split the body by section markers, preserving everything up to the next one.
marks = [(m.start(), m.group(1)) for m in
         re.finditer(r'<div class="mdg-home-section" id="(mdg-home-section-\d+)"', raw)]

menu = []
for idx, (pos, sec_id) in enumerate(marks):
    end = marks[idx + 1][0] if idx + 1 < len(marks) else len(raw)
    body = raw[pos:end]

    items = []
    for card in re.findall(r'<div class="mdg-food-item.*?(?=<div class="mdg-food-item|</main>)',
                           body, re.S):
        name_m = re.search(r'<h3><a[^>]*>(.*?)</a></h3>', card, re.S)
        if not name_m:
            continue
        name = clean(name_m.group(1))

        price_m = re.search(r'<h3 style="font-size:22px[^"]*">(.*?)</h3>', card, re.S)
        price = fa_to_int(clean(price_m.group(1))) if price_m else None

        desc_m = re.search(r'<p style="font-size:12px;opacity:0.8">(.*?)</p>', card, re.S)
        desc = clean(desc_m.group(1)) if desc_m else ""

        if price is None:
            continue
        entry = {"name": name, "price": price}
        if desc:
            entry["desc"] = desc
        items.append(entry)

    if not items:
        continue
    menu.append({
        "id": sec_id.replace("mdg-home-section-", ""),
        "name": order.get(sec_id, sec_id),
        "en": en_of.get(sec_id, ""),
        "items": items,
    })

with open("scraped_menu.json", "w", encoding="utf-8") as fh:
    json.dump(menu, fh, ensure_ascii=False, indent=2)

total = sum(len(c["items"]) for c in menu)
print(f"categories: {len(menu)}   dishes: {total}")
for c in menu:
    print(f"\n[{c['id']}] {c['name']} / {c['en']}  ({len(c['items'])})")
    for it in c["items"]:
        print(f"   {it['price']:>9,}  {it['name']}")
