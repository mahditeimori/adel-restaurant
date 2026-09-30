# Adel Restaurant

Static site for **چلوگوشت آقای عادل** — landing page, digital menu, and the
table QR card. No build step, no framework, no dependencies. Cloudflare Pages
or GitHub Pages both serve it as-is.

## What guests see

```
QR on the table
   -> landing page          two choices: menu, or leave a review
        -> menu.html        75 dishes, light / dark / system themes
```

## Files that are published

| File | What it is |
|---|---|
| `index.html` | Landing page. **This is the site's front door.** |
| `menu.html` | The digital menu. |
| `menu-data.js` | Every dish, category and price. |
| `logo.png` | Restaurant logo. |

## Changing the menu

**`menu-data.js` is the only file you need to edit for prices or dishes.**
It is plain text, so it can be edited in GitHub's web editor or any text
editor. Push the change and the live menu updates — the printed QR cards do
not change, because they only carry the URL.

```js
{
  name: "چلو کباب نگینی",   // dish name          (required)
  price: 740000,           // bare number, Toman (required)
  desc: "optional description",
  tag: "optional badge",
  unavailable: true        // greys the dish out as sold out
}
```

## Regenerating the table QR card

The printed card points at this site's address, so it only needs rebuilding
if the address changes.

```bash
python generate_qr.py --url https://<your-site-address> --mode card
```

Writes `adel_qr-card.png` (3240×3360, print ready). The script decodes its
own output and refuses to finish if the code does not read, so a broken
card cannot be printed. `.gitignore` keeps the generated files out of the
repo.

## Repository layout notes

- **There is no `landing.html`.** `index.html` *is* the landing page. Two
  identical files drift apart, and only one would ever be deployed.
- `generate_qr.py`, `scrape_menu.py` and `build_menu_data.py` are kept for
  maintenance but are not needed to run the site.
- `_redirects` is only used by the old Cloudflare project, to forward the
  previously printed QR addresses here. See the comments inside it.

## Design notes

One palette, two modes. Every colour on the site resolves to a CSS custom
property, so light and dark stay in step. All body text clears 4.5:1
contrast in both themes; tap targets are at least 44px. The menu hero is a
3D scene built from SVG planes at different depths inside a `preserve-3d`
stage, and `prefers-reduced-motion` freezes it.

## License

Private project. All rights reserved.
