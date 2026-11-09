"""
House of Corda - daily Instagram auto-poster.
Picks one product from products.json, builds a caption, publishes as an image post or a Reel with music.
"""
import glob
import json
import os
import random
import subprocess
import sys
import time
from urllib.parse import urljoin

import requests

IG_USER_ID = os.environ["IG_USER_ID"]
TOKEN = os.environ["IG_ACCESS_TOKEN"]
MODE = os.environ.get("POST_MODE", "image").lower()   # "image" or "reel"
SITE = "https://houseofcorda.github.io/"
RAW_BASE = os.environ.get("RAW_BASE", "")  # https://raw.githubusercontent.com/<user>/<repo>/main
API = "https://graph.facebook.com/v21.0"

STATE_FILE = "posted.json"
PRODUCTS_FILE = "products.json"

CAPTIONS = [
    "✨ {name} ✨\nLuxury look, affordable price – just ₹{price}.\n1 gram gold plated, made to shine.",
    "💛 Meet our {name}.\nElegant 1 gram gold jewellery that elevates every outfit.\nPrice: ₹{price}",
    "🌸 Today's pick: {name}\nTimeless design, everyday wear, wedding-ready.\n₹{price} only!",
    "💎 Style it your way with {name}.\nGold-look jewellery without the heavy price tag. ₹{price}",
]

CTA = "\n\n🛍️ Order on WhatsApp or shop at the link in bio.\n🚚 Delivery across India"

BASE_TAGS = "#houseofcorda #1gramgoldjewellery #goldplatedjewellery #artificialjewellery #indianjewellery #jewellerylover"
CATEGORY_TAGS = {
    "earrings": "#earrings #jhumka #studearrings #earringsoftheday",
    "necklace": "#necklace #necklaceset #chokernecklace #bridaljewellery",
    "bangles": "#bangles #kadaset #banglestack #traditionaljewellery",
}


def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def pick_product(products):
    posted = load_json(STATE_FILE, [])
    remaining = [p for p in products if p["id"] not in posted]
    if not remaining:               # everything has been posted once -> start over
        posted, remaining = [], products
    product = random.choice(remaining)
    posted.append(product["id"])
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(posted, f, indent=2)
    return product


def build_caption(p):
    text = random.choice(CAPTIONS).format(name=p["name"], price=p.get("price", ""))
    tags = BASE_TAGS + " " + CATEGORY_TAGS.get(p.get("category", "").lower(), "")
    return f"{text}{CTA}\n\n{tags}".strip()


def git(*args):
    subprocess.run(["git", *args], check=True)


def make_reel(image_url):
    """Download the image, turn it into an 8s zoom video with random music, push to repo, return raw URL."""
    if not RAW_BASE:
        sys.exit("RAW_BASE is required for reel mode")
    os.makedirs("reels", exist_ok=True)
    for old in glob.glob("reels/*.mp4"):
        os.remove(old)

    img_path = "reels/source.jpg"
    r = requests.get(image_url, timeout=60)
    r.raise_for_status()
    with open(img_path, "wb") as f:
        f.write(r.content)

    tracks = glob.glob("music/*.mp3")
    if not tracks:
        sys.exit("Add at least one royalty-free .mp3 file to the music/ folder")
    out = f"reels/reel_{int(time.time())}.mp4"
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=white,"
        "zoompan=z='min(zoom+0.0008,1.15)':d=240:s=1080x1920:fps=30,format=yuv420p"
    )
    subprocess.run([
        "ffmpeg", "-y", "-i", img_path, "-i", random.choice(tracks),
        "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a",
        "-t", "8", "-c:v", "libx264", "-c:a", "aac", "-shortest", out,
    ], check=True)
    os.remove(img_path)

    git("add", "reels")
    git("commit", "-m", "Add reel video")
    git("push")
    time.sleep(20)  # let raw.githubusercontent.com pick up the file
    return f"{RAW_BASE}/{out}"


def create_container(caption, image_url=None, video_url=None):
    data = {"caption": caption, "access_token": TOKEN}
    if video_url:
        data.update({"media_type": "REELS", "video_url": video_url, "share_to_feed": "true"})
    else:
        data["image_url"] = image_url
    r = requests.post(f"{API}/{IG_USER_ID}/media", data=data, timeout=60)
    r.raise_for_status()
    return r.json()["id"]


def wait_until_ready(container_id):
    for _ in range(30):
        r = requests.get(f"{API}/{container_id}",
                         params={"fields": "status_code", "access_token": TOKEN}, timeout=30)
        status = r.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            sys.exit(f"Instagram failed to process media: {r.text}")
        time.sleep(10)
    sys.exit("Timed out waiting for Instagram to process media")


def publish(container_id):
    r = requests.post(f"{API}/{IG_USER_ID}/media_publish",
                      data={"creation_id": container_id, "access_token": TOKEN}, timeout=60)
    r.raise_for_status()
    return r.json()["id"]


def main():
    products = load_json(PRODUCTS_FILE, [])
    if not products:
        sys.exit("products.json is empty or missing")

    product = pick_product(products)
    image_url = urljoin(SITE, product["image"])
    caption = build_caption(product)
    print("Posting:", product["name"], "| mode:", MODE)

    if MODE == "reel":
        container = create_container(caption, video_url=make_reel(image_url))
    else:
        container = create_container(caption, image_url=image_url)

    wait_until_ready(container)
    print("Published, media id:", publish(container))


if __name__ == "__main__":
    main()
