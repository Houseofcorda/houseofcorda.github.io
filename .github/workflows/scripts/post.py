"""
House of Corda - daily Instagram auto-poster.
Reads the same JCM product feed as build_site.py, picks one product that has not been
posted yet, builds a caption, and publishes it as an image post or a Reel with music.
"""
import glob
import html
import json
import math
import os
import random
import re
import subprocess
import sys
import time
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

def clean(value):
    """Remove spaces, line breaks and quotes that sometimes get pasted into secrets by accident."""
    return "".join(value.split()).strip("\"'")


def clean_token(value):
    """Pull just the token out, even if the whole {"access_token": ...} text was pasted."""
    m = re.search(r"EAA[A-Za-z0-9]+", value)
    return m.group(0) if m else clean(value)


IG_USER_ID = clean(os.environ["IG_USER_ID"])
TOKEN = clean_token(os.environ["IG_ACCESS_TOKEN"])
print(f"Token check: length={len(TOKEN)}, starts with EAA={TOKEN.startswith('EAA')}, user id length={len(IG_USER_ID)}")
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


def best_image_url(img):
    """Return the highest-resolution picture URL the feed offers for this image."""
    best_w, best_url = 0, img.get("src", "")
    for part in (img.get("srcset") or "").split(","):
        bits = part.strip().split()
        if len(bits) == 2 and bits[1].endswith("w"):
            try:
                w = int(bits[1][:-1])
            except ValueError:
                continue
            if w > best_w:
                best_w, best_url = w, bits[0]
    return best_url


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
            "src": best_image_url(p["images"][0]) or p["images"][0].get("src", ""),
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


def load_source_image(src_url):
    """Download the product photo at full resolution as an RGB image (transparency -> white)."""
    r = requests.get(src_url, headers=UA, timeout=60)
    r.raise_for_status()
    img = Image.open(BytesIO(r.content))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def prepare_image(src_url, out_path):
    """Photo post: clean JPEG with an Instagram-safe shape."""
    img = load_source_image(src_url)
    w, h = img.size
    ratio = w / h
    if ratio < 0.8 or ratio > 1.91:          # outside Instagram's allowed range -> pad to square
        side = max(w, h)
        canvas = Image.new("RGB", (side, side), (255, 255, 255))
        canvas.paste(img, ((side - w) // 2, (side - h) // 2))
        img = canvas
    if max(img.size) > 1440:
        img.thumbnail((1440, 1440), Image.LANCZOS)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, "JPEG", quality=95)


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


REEL_SECONDS = 20
REEL_FPS = 30
REEL_W, REEL_H = 1080, 1920          # 9:16, full HD vertical
SUPERSAMPLE = 1.5                    # work at 1.5x size so the zoom stays razor sharp
MAX_ZOOM = 1.12                      # slow zoom-in: ends 12% closer
FRAME_MODE = os.environ.get("REEL_FRAME", "blur")   # "blur" = whole product visible on a soft blurred backdrop
                                                    # "crop" = photo fills the whole 9:16 frame (sides are cropped)


HOOK_SECONDS = 4.0                   # animated visual hook at the start of every Reel
THUMB_OFFSET_MS = 2000               # Instagram uses this frame (inside the hook) as the Reel thumbnail
HOOK_LINES = ["NEW ARRIVAL", "TODAY'S PICK", "TRENDING NOW", "MUST-HAVE STYLE", "LOVE AT FIRST SIGHT"]
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
]
MAROON, GOLD, CREAM = (155, 27, 48), (245, 215, 120), (255, 244, 214)


def load_font(size):
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def has_glyph(font, ch):
    """True if the font can draw this character (so we can use the rupee sign safely)."""
    def render(c):
        im = Image.new("L", (120, 120), 0)
        ImageDraw.Draw(im).text((10, 10), c, font=font, fill=255)
        return im.tobytes()
    return render(ch) != render("\ue000")


def fit_font(text, size, max_w):
    font = load_font(size)
    while size > 24 and font.getlength(text) > max_w:
        size -= 4
        font = load_font(size)
    return font


def smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def build_hook_overlay(price):
    """Pre-draw the hook: a maroon-and-gold headline banner at the top and a price tag at the bottom."""
    ov = Image.new("RGBA", (REEL_W, REEL_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    cx = REEL_W // 2

    headline = random.choice(HOOK_LINES)
    f_head = fit_font(headline, 84, 880)
    f_sub = fit_font("HOUSE OF CORDA  \u2022  1 GRAM GOLD", 38, 880)
    sub = "HOUSE OF CORDA  \u2022  1 GRAM GOLD"
    hw, sw = f_head.getlength(headline), f_sub.getlength(sub)
    box_w = max(hw, sw) + 100
    top, box_h = 270, 210
    d.rounded_rectangle((cx - box_w / 2, top, cx + box_w / 2, top + box_h), radius=30,
                        fill=MAROON + (232,), outline=GOLD + (255,), width=4)
    d.text((cx, top + 78), headline, font=f_head, fill=GOLD + (255,), anchor="mm")
    d.text((cx, top + 158), sub, font=f_sub, fill=CREAM + (255,), anchor="mm")

    f_price = fit_font("Only \u20b9 0,000", 70, 640)
    sign = "\u20b9" if has_glyph(f_price, "\u20b9") else "Rs."
    tag = f"Only {sign}{price:,}"
    tw = f_price.getlength(tag)
    pill_cy = 1565
    d.rounded_rectangle((cx - tw / 2 - 60, pill_cy - 62, cx + tw / 2 + 60, pill_cy + 62), radius=62,
                        fill=(255, 255, 255, 240), outline=GOLD + (255,), width=4)
    d.text((cx, pill_cy), tag, font=f_price, fill=MAROON + (255,), anchor="mm")
    return ov.convert("RGB"), ov.split()[3]


def build_shimmer_band():
    """A soft, slanted band of light that sweeps across the jewellery at the very start."""
    bw, slant = 320, 0.32
    strip = Image.new("L", (bw, REEL_H), 0)
    sd = ImageDraw.Draw(strip)
    for x in range(bw):
        v = max(0.0, 1 - abs(x - bw / 2) / (bw / 2))
        sd.line((x, 0, x, REEL_H), fill=int(255 * v * v * 0.55))
    out_w = bw + int(REEL_H * slant)
    return strip.transform((out_w, REEL_H), Image.AFFINE, (1, -slant, int(REEL_H * slant), 0, 1, 0))


def apply_hook(frame, t, overlay, alpha, band):
    """Draw the hook on one frame at time t (seconds)."""
    if t < 1.6:                                           # shimmer sweep
        p = smooth((t - 0.2) / 1.3)
        if 0 < p < 1:
            x = int(-band.width + (REEL_W + band.width) * p)
            frame.paste(CREAM, (x, 0), band)
    if t < HOOK_SECONDS:                                  # headline + price tag
        e_in = smooth((t - 0.15) / 0.55)
        e_out = 1 - smooth((t - (HOOK_SECONDS - 0.5)) / 0.5)
        env = e_in * e_out
        if env > 0.01:
            a = alpha.point(lambda v, e=env: int(v * e))
            frame.paste(overlay, (0, int(70 * (1 - e_in))), a)


def build_canvas(img):
    """Compose the 9:16 picture at 1.5x resolution (1620 x 2880) so zooming never softens it."""
    cw, ch = int(REEL_W * SUPERSAMPLE), int(REEL_H * SUPERSAMPLE)
    w, h = img.size

    # cover-scale the photo over the whole canvas (centre crop)
    scale = max(cw / w, ch / h)
    cover = img.resize((max(cw, round(w * scale)), max(ch, round(h * scale))), Image.LANCZOS)
    left, top = (cover.width - cw) // 2, (cover.height - ch) // 2
    cover = cover.crop((left, top, left + cw, top + ch))
    if FRAME_MODE == "crop":
        return cover

    # blurred backdrop + sharp product photo at full width
    backdrop = cover.filter(ImageFilter.GaussianBlur(int(40 * SUPERSAMPLE)))
    backdrop = ImageEnhance.Brightness(backdrop).enhance(0.95)
    fit = min(cw / w, ch * 0.80 / h)
    fg = img.resize((round(w * fit), round(h * fit)), Image.LANCZOS)
    fg = fg.filter(ImageFilter.UnsharpMask(radius=1.6, percent=70, threshold=2))
    # soft feathered edge (top and bottom) so the photo melts into the backdrop
    feather = int(70 * SUPERSAMPLE)
    mask = Image.new("L", fg.size, 255)
    px = mask.load()
    for y in range(min(feather, fg.height // 2)):
        v = int(255 * (y / feather))
        for x in range(fg.width):
            px[x, y] = v
            px[x, fg.height - 1 - y] = v
    backdrop.paste(fg, ((cw - fg.width) // 2, (ch - fg.height) // 2), mask)
    return backdrop


def make_reel(img, product):
    """Build a 20-second 1080x1920 (9:16) HD Reel: 4-second visual hook, slow smooth zoom-in on the photo + music."""
    tracks = glob.glob("music/*.mp3")
    if not tracks:
        sys.exit("Add at least one royalty-free .mp3 file to the music/ folder")
    for old in glob.glob("reels/*.mp4"):
        os.remove(old)
    os.makedirs("reels", exist_ok=True)
    out = f"reels/reel_{int(time.time())}.mp4"

    canvas = build_canvas(img)
    cw, ch = canvas.size
    overlay, alpha = build_hook_overlay(product["price"])
    band = build_shimmer_band()
    frames = REEL_SECONDS * REEL_FPS

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{REEL_W}x{REEL_H}", "-r", str(REEL_FPS), "-i", "-",
        "-stream_loop", "-1", "-i", random.choice(tracks),          # loops the music if it is shorter than the Reel
        "-filter_complex", f"[1:a]afade=t=out:st={REEL_SECONDS - 1.5}:d=1.5[a]",
        "-map", "0:v", "-map", "[a]", "-t", str(REEL_SECONDS),
        "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
        "-profile:v", "high", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k", out,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(frames):
        p = i / (frames - 1)
        zoom = 1 + (MAX_ZOOM - 1) * (0.5 - 0.5 * math.cos(math.pi * p))   # gentle ease-in-out
        bw, bh = cw / zoom, ch / zoom
        x0, y0 = (cw - bw) / 2, (ch - bh) / 2
        frame = canvas.resize((REEL_W, REEL_H), Image.BICUBIC, box=(x0, y0, x0 + bw, y0 + bh))
        apply_hook(frame, i / REEL_FPS, overlay, alpha, band)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg failed while building the Reel")
    return out


def create_container(caption, image_url=None, video_url=None):
    data = {"caption": caption, "access_token": TOKEN}
    if video_url:
        data.update({"media_type": "REELS", "video_url": video_url, "share_to_feed": "true",
                     "thumb_offset": str(THUMB_OFFSET_MS)})
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

    if MODE == "reel":
        photo = load_source_image(product["src"])
        print("Source photo size:", photo.size)
        video_path = make_reel(photo, product)
        video_url = publish_file_to_repo(video_path)
        container = create_container(caption, video_url=video_url)
    else:
        for old in glob.glob("posts/*.jpg"):
            os.remove(old)
        image_path = f"posts/post_{int(time.time())}.jpg"
        prepare_image(product["src"], image_path)
        image_url = publish_file_to_repo(image_path)
        container = create_container(caption, image_url=image_url)

    wait_until_ready(container)
    print("Published, media id:", publish(container))


if __name__ == "__main__":
    main()
