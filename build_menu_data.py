"""Build menu-data.js from the scraped menu, with the signature dish on top."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
menu = json.loads((HERE / "scraped_menu.json").read_text(encoding="utf-8"))

# Your signature dish leads the main course, as on the table card.
SIGNATURE = {
    "name": "چلوگوشت آقای عادل",
    "price": 1580000,
    "desc": "چلوگوشت گوسفندی مخصوص با برنج ایرانی",
    "tag": "پیشنهاد آقای عادل",
}

main = next(c for c in menu if c["id"] == "19428")
if not any(i["name"] == SIGNATURE["name"] for i in main["items"]):
    main["items"].insert(0, SIGNATURE)

FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"


def fa_num(value: int) -> str:
    s = f"{value:,}".replace(",", "٬")
    return s.translate(str.maketrans("0123456789", FA_DIGITS))


lines = [
    "/* =============================================================================",
    "   ADEL RESTAURANT - MENU CONTENT",
    "   -----------------------------------------------------------------------------",
    "   THIS IS THE ONLY FILE YOU NEED TO EDIT.",
    "",
    "   To change a price: find the dish, edit the number after 'price'.",
    "   To hide a dish without deleting it: add   unavailable: true",
    "   To add a badge like \"محبوب\":            add   tag: \"محبوب\"",
    "   To add a new category: copy a whole { id, name, en, items: [] } block.",
    "",
    "   Prices are plain numbers in Toman. No commas, no text.",
    "   The page formats them with Persian digits automatically.",
    "   ========================================================================== */",
    "",
    "const MENU = [",
]

for ci, cat in enumerate(menu):
    lines.append("  {")
    lines.append(f'    id: "{cat["id"]}",')
    lines.append(f'    name: "{cat["name"]}",')
    lines.append(f'    en: "{cat["en"]}",')
    lines.append("    items: [")
    for it in cat["items"]:
        lines.append("      {")
        lines.append(f'        name: "{it["name"]}",')
        lines.append(f'        price: {it["price"]},')
        if it.get("desc"):
            lines.append(f'        desc: "{it["desc"]}",')
        if it.get("tag"):
            lines.append(f'        tag: "{it["tag"]}",')
        if it.get("unavailable"):
            lines.append("        unavailable: true,")
        lines.append("      },")
    lines.append("    ]")
    lines.append("  }," if ci < len(menu) - 1 else "  }")
lines.append("];")

(HERE / "menu-data.js").write_text("\n".join(lines) + "\n", encoding="utf-8")

total = sum(len(c["items"]) for c in menu)
print(f"wrote menu-data.js: {len(menu)} categories, {total} dishes")
for c in menu:
    lo = min(i["price"] for i in c["items"])
    hi = max(i["price"] for i in c["items"])
    print(f"  {c['name']:12s} {len(c['items']):3d} items   {fa_num(lo)} - {fa_num(hi)}")
