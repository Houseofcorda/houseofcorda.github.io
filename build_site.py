"""
Builds the House of Corda catalog from the JCM product feed.

Usage:
    python build_site.py              # fetch live from JCM and build into ./site
    python build_site.py --local DIR  # (testing) read page*.json files from DIR

Output (in ./site):
    index.html        the catalog
    p/<id>.html       one small page per product (gives WhatsApp a picture preview)
"""
import glob
import html as H
import json
import os
import re
import shutil
import sys
import time
import urllib.request

FEED = "https://jcmjewellery.com/wp-json/wc/store/v1/products?per_page=100&page={}"
OUT = "site"
MARKUP = 30          # rupees added to every JCM price
MIN_PRODUCTS = 100  # safety: if fewer come back, do NOT publish (keeps the old site)
UA = {"User-Agent": "Mozilla/5.0 (compatible; HouseOfCordaCatalog/1.0)"}


def get(url):
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Could not fetch {url}: {last}")


def fetch_live():
    products, page = [], 1
    while page <= 30:
        data = get(FEED.format(page))
        if not data:
            break
        products += data
        print(f"page {page}: {len(data)} products", flush=True)
        if len(data) < 100:
            break
        page += 1
        time.sleep(1)
    return products


def load_local(folder):
    def key(f):
        m = re.search(r"page(\d+)", f)
        return (int(m.group(1)) if m else 0, f)
    out = []
    for f in sorted(glob.glob(os.path.join(folder, "page*.json")), key=key):
        out += json.load(open(f, encoding="utf-8"))
    return out


def preview_image(img):
    """Pick a ~500-800px wide picture for the WhatsApp preview card."""
    best = None
    for part in (img.get("srcset") or "").split(","):
        t = part.strip().split()
        if len(t) == 2 and t[1].endswith("w"):
            w = int(t[1][:-1])
            if 480 <= w <= 800 and (best is None or w > best[0]):
                best = (w, t[0])
    return best[1] if best else img.get("src", "")


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--local":
        raw = load_local(sys.argv[2])
    else:
        raw = fetch_live()

    seen, items = set(), []
    for p in raw:
        if p["id"] in seen:
            continue
        seen.add(p["id"])
        pr = p["prices"]
        price = int(pr["price"]) // 10 ** int(pr["currency_minor_unit"]) + MARKUP
        img = p["images"][0] if p.get("images") else {}
        cats = [c["name"] for c in p.get("categories", [])]
        items.append({
            "id": p["id"], "name": p["name"], "price": price,
            "cat": cats[0] if cats else "Other",
            "thumb": img.get("thumbnail") or img.get("src", ""),
            "src": img.get("src", ""), "prev": preview_image(img),
        })

    print(f"Total unique products: {len(items)}")
    if len(items) < MIN_PRODUCTS:
        print("Too few products - stopping so the existing site is not damaged.")
        sys.exit(1)

    data = json.dumps(
        [[i["name"], i["price"], i["cat"], i["thumb"], i["src"], i["id"]] for i in items],
        ensure_ascii=False, separators=(",", ":"))
    template = open("template.html", encoding="utf-8").read()
    if "__DATA__" not in template:
        raise SystemExit("template.html is missing the __DATA__ marker")

    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(os.path.join(OUT, "p"))
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(
        template.replace("__DATA__", data))

    e = H.escape
    for i in items:
        page = (
            '<!doctype html><html><head><meta charset="utf-8">'
            f'<title>{e(i["name"])}</title>'
            f'<meta property="og:title" content="{e(i["name"])} \u2013 \u20b9{i["price"]:,}">'
            '<meta property="og:description" content="House of Corda \u2013 order on WhatsApp">'
            f'<meta property="og:image" content="{e(i["prev"])}">'
            '<meta property="og:type" content="website">'
            '<meta name="twitter:card" content="summary_large_image">'
            f'<meta http-equiv="refresh" content="0;url=../index.html#p{i["id"]}">'
            f'</head><body><script>location.replace("../index.html#p{i["id"]}")</script></body></html>'
        )
        open(os.path.join(OUT, "p", f'{i["id"]}.html'), "w", encoding="utf-8").write(page)
    print(f"Built {len(items)} products into ./{OUT}")


if __name__ == "__main__":
    main()
