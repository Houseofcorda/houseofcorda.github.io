"""
House of Corda - daily Instagram auto-poster.
Reads the same JCM product feed as build_site.py, picks one product that has not been
posted yet, builds a caption, and publishes it as an image post or a Reel with music.
"""
import glob
import html
import json
import os
import random
import subprocess
import sys
import time
from io import BytesIO

import requests
from PIL import Image

IG_USER_ID = os.environ["IG_USER_ID"]
TOKEN = os.environ["IG_ACCESS_TOKEN"]
MODE = os.environ.get("POST_MODE", "image").lower()      # "image" or "reel"
RAW_BASE = os.environ.get("RAW_BASE", "")                # https://raw.githubusercontent.com/<user>/<repo>/main
API = "https://graph.facebook.com/v21.0"

FEED = "https://jcmjewellery.com/wp-json/wc/store/v1/products?per_page=100&page={}"
MARKUP = 30                      # same markup as build_site.py
MIN_PRODUCTS = 50
UA = {"User-Agent": "Mozilla/5.0 (compatible; HouseOfCordaCatalog/1.0)"}
STATE_FILE = "posted.json"

CAPTIONS = [
    "✨ {name} ✨\nLuxury look, affordable price – just ₹{price}.\n1 gram gold plated, made to shine.",
    "💛 Meet our {name}.\nElegant 1 gram gold jewellery that elevates every outfit.\nPrice: ₹{price}",
    "🌸 Today's pick: {name}\nTimeless design, everyday wear, wedding-ready.\n₹{price} only!",
    "💎 Style it your way with {name}.\nGold-look jewellery without the heavy price tag. ₹{price}",
]
CTA = "\n\n🛍️ Order on WhatsApp or shop at the link in bio.\n🚚 Delivery across India"
BASE_TAGS = "#houseofcorda #1gramgoldjewellery #goldplatedjewellery #artificialjewellery #indianjewellery #jewellerylover"
KEYWORD_TAGS = {
    "earring": "#earrings #earringsoftheday",
    "jhumk": "#jhumka #jhumkas",
    "stud": "#studearrings",
    "necklace": "#necklace #necklaceset",
    "choker": "#choker #chokernecklace",
    "haar": "#haar #longnecklace",
    "bangle": "#bangles #banglestack",
    "kada": "#kada #kadabangle",
    "bracelet": "#bracelet",
    "ring": "#ring #fingerring",
    "pendant": "#pendant #pendantset",
    "chain": "#goldchain",
    "mangalsutra": "#mangalsutra",
    "anklet": "#anklet #payal",
    "bridal": "#bridaljewellery #weddingjewellery",
    "kundan": "#kundanjewellery",
    "temple": "#templejewellery",
}


def get_json(url):
    last = None
    for attempt in range(4):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Could not fetch {url}: {last}")


def fetch_products():
    raw, page = [], 1
    while page <= 30:
        data = get_json(FEED.format(page))
        if not data:
            break
        raw += data
        if len(data) < 100:
            break
        page += 1
        time.sleep(1)

    seen, items = set(), []
    for p in raw:
        if p["id"] in seen or not p.get("images"):
            continue
        seen.add(p["id"])
        pr = p["prices"]
        price = int(pr["price"]) // 10 ** int(pr["currency_minor_unit"]) + MARKUP
        cats = [html.unescape(c["name"]) for c in p.get("categories", [])]
        items.append({
            "id": p["id"],
            "name": html.unescape(p["name"]).strip(),
            "price": price,
            "cat": cats[0] if cats else "",
            "src": p["images"][0].get("src", ""),
        })
    if len(items) < MIN_PRODUCTS:
        sys.exit(f"Only {len(items)} products came back from the feed - stopping.")
    return items


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def pick_product(items):
    posted = load_state()
    remaining = [p for p in items if p["id"] not in posted]
    if not remaining:                # everything posted once -> start the cycle again
        posted, remaining = [], items
    product = random.choice(remaining)
    posted.append(product["id"])
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(posted, f)
    return product


def build_caption(p):
    text = random.choice(CAPTIONS).format(name=p["name"], price=f'{p["price"]:,}')
    haystack = f'{p["name"]} {p["cat"]}'.lower()
    tags = []
    for key, value in KEYWORD_TAGS.items():
        if key in haystack:
            tags.append(value)
    all_tags = BASE_TAGS + " " + " ".join(tags[:4])
    return f"{text}{CTA}\n\n{all_tags}".strip()


def git(*args):
    subprocess.run(["git", *args], check=True)


def prepare_image(src_url, out_path):
    """Download the product photo, make it a clean JPEG with an Instagram-safe shape."""
    r = requests.get(src_url, headers=UA, timeout=60)
    r.raise_for_status()
    img = Image.open(BytesIO(r.content))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")

    w, h = img.size
    ratio = w / h
    if ratio < 0.8 or ratio > 1.91:          # outside Instagram's allowed range -> pad to square
        side = max(w, h)
        canvas = Image.new("RGB", (side, side), (255, 255, 255))
        canvas.paste(img, ((side - w) // 2, (side - h) // 2))
        img = canvas
    if max(img.size) > 1440:
        img.thumbnail((1440, 1440))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, "JPEG", quality=92)


def publish_file_to_repo(path):
    """Commit a file so Instagram can fetch it from a public raw.githubusercontent.com URL."""
    if not RAW_BASE:
        sys.exit("RAW_BASE is not set")
    git("add", path)
    git("commit", "-m", f"Add {os.path.basename(path)}")
    git("push")
    url = f"{RAW_BASE}/{path}"
    for _ in range(12):                       # wait until the file is publicly reachable
        try:
            if requests.head(url, timeout=20).status_code == 200:
                return url
        except Exception:  # noqa
            pass
        time.sleep(5)
    return url


def make_reel(image_path):
    """Turn the photo into an 8-second zoom video with a random track from music/."""
    tracks = glob.glob("music/*.mp3")
    if not tracks:
        sys.exit("Add at least one royalty-free .mp3 file to the music/ folder")
    for old in glob.glob("reels/*.mp4"):
        os.remove(old)
    os.makedirs("reels", exist_ok=True)
    out = f"reels/reel_{int(time.time())}.mp4"
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=white,"
        "zoompan=z='min(zoom+0.0008,1.15)':d=240:s=1080x1920:fps=30,format=yuv420p"
    )
    subprocess.run([
        "ffmpeg", "-y", "-i", image_path, "-i", random.choice(tracks),
        "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a",
        "-t", "8", "-c:v", "libx264", "-c:a", "aac", "-shortest", out,
    ], check=True)
    return out


def create_container(caption, image_url=None, video_url=None):
    data = {"caption": caption, "access_token": TOKEN}
    if video_url:
        data.update({"media_type": "REELS", "video_url": video_url, "share_to_feed": "true"})
    else:
        data["image_url"] = image_url
    r = requests.post(f"{API}/{IG_USER_ID}/media", data=data, timeout=60)
    if not r.ok:
        sys.exit(f"Instagram error while creating media: {r.text}")
    return r.json()["id"]


def wait_until_ready(container_id):
    for _ in range(30):
        r = requests.get(f"{API}/{container_id}",
                         params={"fields": "status_code", "access_token": TOKEN}, timeout=30)
        status = r.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            sys.exit(f"Instagram failed to process the media: {r.text}")
        time.sleep(10)
    sys.exit("Timed out waiting for Instagram to process the media")


def publish(container_id):
    r = requests.post(f"{API}/{IG_USER_ID}/media_publish",
                      data={"creation_id": container_id, "access_token": TOKEN}, timeout=60)
    if not r.ok:
        sys.exit(f"Instagram error while publishing: {r.text}")
    return r.json()["id"]


def main():
    items = fetch_products()
    print(f"Feed returned {len(items)} products")

    product = pick_product(items)
    caption = build_caption(product)
    print("Posting:", product["name"], "| price:", product["price"], "| mode:", MODE)

    for old in glob.glob("posts/*.jpg"):
        os.remove(old)
    image_path = f"posts/post_{int(time.time())}.jpg"
    prepare_image(product["src"], image_path)

    if MODE == "reel":
        video_path = make_reel(image_path)
        os.remove(image_path)
        video_url = publish_file_to_repo(video_path)
        container = create_container(caption, video_url=video_url)
    else:
        image_url = publish_file_to_repo(image_path)
        container = create_container(caption, image_url=image_url)

    wait_until_ready(container)
    print("Published, media id:", publish(container))


if __name__ == "__main__":
    main()
