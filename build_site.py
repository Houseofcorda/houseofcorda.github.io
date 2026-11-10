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


def add_order_patch(page_html):
    """Adds the order code (Order ID, "Payment done? Send order on WhatsApp" prompt) to the end of the page's script.
    It is added automatically on every build, so template.html itself does not need to be edited."""
    if "function ensureOid" in page_html:
        print("Order code is already inside template.html - not adding it twice")
        return page_html
    if "</script" in ORDERS_PATCH.lower():                 # would cut the page's script in half - never insert that
        print("WARNING: order code contains a closing script tag - NOT added")
        return page_html
    i = page_html.rfind("</script>")
    if i == -1:
        print("WARNING: no </script> found - order code NOT added")
        return page_html
    print("Order code added to the page")
    return page_html[:i] + "\n" + ORDERS_PATCH + "\n" + page_html[i:]


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
    index_html = add_order_patch(template.replace("__DATA__", data))
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(index_html)

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



# ---------------------------------------------------------------------------------------------
# Order code that is added to the shop page (WhatsApp-only version, no accounts or keys needed)
# ---------------------------------------------------------------------------------------------
ORDERS_PATCH = r'''/* ===== House of Corda: Order ID + "Payment done? Send order on WhatsApp" prompt
   (added to the shop page automatically by build_site.py; no keys or accounts needed) ===== */

/* --- order ID: made once per cart, kept for 12 hours, changes when the cart changes --- */
var oid = "";
try {
  var _o = JSON.parse(localStorage.getItem("ax_oid") || "null");
  if (_o && _o.id && Date.now() - _o.t < 12 * 3600 * 1000) oid = _o.id;
} catch (e) {}
function ensureOid() {
  if (!oid) {
    var d = new Date(), p = function (n) { return (n < 10 ? "0" : "") + n };
    var ch = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789", r = "";       // no 0/O/1/I, so IDs are easy to read out
    for (var i = 0; i < 4; i++) r += ch.charAt(Math.floor(Math.random() * ch.length));
    oid = "HOC" + String(d.getFullYear()).slice(2) + p(d.getMonth() + 1) + p(d.getDate()) + "-" + r;
    try { localStorage.setItem("ax_oid", JSON.stringify({ id: oid, t: Date.now() })) } catch (e) {}
  }
  return oid;
}
function resetOid() { oid = ""; try { localStorage.removeItem("ax_oid") } catch (e) {} }

/* --- the Order ID goes into the UPI payment note, so it shows in your own UPI / bank alert --- */
function upiLink(t, n) {
  var note = ("House of Corda " + ensureOid()).slice(0, 40);
  return "upi://pay?pa=" + encodeURIComponent(UPI_ID) + "&pn=" + encodeURIComponent(UPI_NAME) + "&am=" + t.toFixed(2) + "&cu=INR&tn=" + encodeURIComponent(note);
}

/* --- WhatsApp message now carries the Order ID and the (optional) UPI transaction ID --- */
function buildMsg(links, maxName) {
  var L = ["Hello House of Corda, I want to order (Order ID: " + ensureOid() + "):", ""], n = 0;
  Object.keys(cart).forEach(function (k) {
    var d = D[byId[k]], q = cart[k]; n++;
    var nm = maxName ? d[0].slice(0, maxName) : d[0];
    L.push(n + ". " + nm + " x " + q + " = " + fmt(d[1] * q));
    if (links) { var u = pageLink(d); if (u) L.push(u) }
  });
  L.push("", "Total: " + fmt(total()));
  L.push("", "DELIVERY DETAILS", "Name: " + cust.name.trim(), "Mobile: " + normPhone(), "Address: " + cust.addr.trim(), "City: " + cust.city.trim(), "State: " + cust.state, "Pincode: " + cust.pin);
  if (cust.utr) L.push("", "UPI transaction ID: " + cust.utr);
  L.push("", "I will send the UPI payment screenshot here.");
  return L.join("\n");
}

/* --- "Payment done?" prompt: shown when the customer comes back from the UPI app --- */
var PAY_WINDOW_MS = 30 * 60 * 1000;
function setPayFlag() { try { localStorage.setItem("ax_paying", JSON.stringify({ id: ensureOid(), t: Date.now() })) } catch (e) {} }
function clearPayFlag() { try { localStorage.removeItem("ax_paying") } catch (e) {} }
function payFlag() {
  try {
    var f = JSON.parse(localStorage.getItem("ax_paying") || "null");
    if (f && f.id && f.id === oid && Date.now() - f.t < PAY_WINDOW_MS) return f;
  } catch (e) {}
  return null;
}
function hidePayBar() { var b = $("paybar"); if (b) b.style.display = "none" }
function showPayBar() {
  if (!payFlag() || !Object.keys(cart).length) return;
  var b = $("paybar");
  if (!b) {
    b = document.createElement("div"); b.id = "paybar";
    b.style.cssText = "position:fixed;left:0;right:0;bottom:0;z-index:90;background:#fff;border-top:3px solid #D4A63A;box-shadow:0 -4px 16px rgba(0,0,0,.25);padding:14px 16px calc(14px + env(safe-area-inset-bottom));text-align:center";
    b.innerHTML = '<div style="font-weight:800;font-size:16px;margin-bottom:4px">Payment done?</div>' +
      '<div style="font-size:13px;color:#7A6A55;margin-bottom:10px;line-height:1.4">Send your order details to us on WhatsApp so we can pack and ship it.</div>' +
      '<button class="wa" data-a="wa">' + WA + ' Send order on WhatsApp</button>' +
      '<button class="clr" data-a="hidepay">Not now</button>';
    document.body.appendChild(b);
  }
  b.style.display = "block";
}
document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible") showPayBar() });
if (window.addEventListener) window.addEventListener("pageshow", showPayBar);

/* --- cart changes start a new Order ID --- */
function setQty(id, q) { if (q <= 0) delete cart[id]; else cart[id] = Math.min(q, 50); save(); resetOid(); refresh(id) }

/* --- button actions (same as before, plus the prompt) --- */
function act(b) {
  var a = b.dataset.a, id = b.dataset.id;
  if (a === "add") { setQty(id, qty(id) + 1); toast("Added to cart") }
  else if (a === "inc") setQty(id, qty(id) + 1);
  else if (a === "dec") setQty(id, qty(id) - 1);
  else if (a === "rm") setQty(id, 0);
  else if (a === "opencart") openCart();
  else if (a === "closecart") closeCart();
  else if (a === "clear") {
    if (confirm("Remove all items from your cart?")) {
      cart = {}; save(); resetOid(); clearPayFlag(); hidePayBar(); renderBar(); renderCart();
      document.querySelectorAll("[id^=c-]").forEach(function (e) { e.innerHTML = ctl(e.id.slice(2)) }); renderLbCtl()
    }
  }
  else if (a === "pay") { if (validate(false)) setPayFlag() }
  else if (a === "wa") { if (validate(true)) { clearPayFlag(); hidePayBar(); window.open(waLink(orderMsg()), "_blank") } }
  else if (a === "hidepay") { clearPayFlag(); hidePayBar() }
  else if (a === "copy") { try { navigator.clipboard.writeText(UPI_ID); b.textContent = "Copied!"; setTimeout(function () { b.textContent = UPI_ID }, 1500) } catch (x) {} }
}

/* --- form: optional UPI transaction ID box (helps you match the payment) --- */
function fillForm() {
  FIELDS.forEach(function (f) { $(f[0]).value = cust[f[1]] || "" });
  var u = $("cutr"); if (u) u.value = cust.utr || "";
}
(function () {
  var err = $("cerr");
  if (err && !$("cutr")) {
    err.insertAdjacentHTML("beforebegin", '<input id="cutr" type="text" inputmode="numeric" maxlength="12" placeholder="UPI transaction ID (12 digits, optional) \u2013 add after you pay" autocomplete="off">');
    $("cutr").oninput = function () { var v = this.value.replace(/\D/g, ""); if (v !== this.value) this.value = v; cust.utr = v; save() };
  }
})();
showPayBar();
'''


if __name__ == "__main__":
    main()
