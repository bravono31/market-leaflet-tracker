"""Leaflet discovery for each store.

Every fetcher returns a list of leaflet dicts:
  {id, store, title, source_url, start, end, pages: [page, ...]}
A page is {"kind": "image", "url": ...} or
{"kind": "tiles", "urls": [...], "w": px, "h": px, "tile": px} (row-major tiles).
start/end are "YYYY-MM-DD" or None when the site does not expose them.
"""
import html
import io
import json
import math
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
JST = timezone(timedelta(hours=9))

STORES = {
    "keio": {"name": "京王ストア 府中店",
             "url": "https://chirashi.kurashiru.com/stores/9364f453-e760-47b4-ac60-49468c163751/limit_excursion"},
    "summit": {"name": "サミット ミナノ分倍河原店",
               "url": "https://www.summitstore.co.jp/store/tokyo/post/?id=151"},
    "yaoko": {"name": "ヤオコー 府中フォーリス店",
              "url": "https://www.yaoko-net.com/store/store06/208.html"},
    "ozeki": {"name": "オオゼキ 府中店",
              "url": "https://www.ozeki-net.co.jp/shop/tokyo/fuchu/fuchu/"},
}

SHUFOO_SHOP_ID = "264241"   # サミット ミナノ分倍河原店
YAOKO_SHOP_CODE = "1208"    # ヤオコー 府中フォーリス店
YAOKO_BASE = "https://yap-pd.yaoko-net.com/"
SHUFOO_SCALE = 4            # 4x of the base size (~3000px wide)
SHUFOO_TILE = 512
MECLIB_SCALE = 2            # オオゼキ viewer: 2x of the thumbnail (~3000px wide)


def http_get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read()


# --- 京王ストア (クラシルチラシ) -------------------------------------------

def parse_kurashiru(page_html):
    found = re.findall(
        r'leafletItem" data-leaflet-id="(\d+)".*?alt="([^"]*)" src="([^"]+)"',
        page_html, re.S)
    leaflets = {}
    # Front and back share a title but have separate ids: group them.
    for lid, title, src in found:
        title = html.unescape(title)
        leaf = leaflets.setdefault(title, {
            "id": f"keio-{lid}", "store": "keio", "title": title,
            "source_url": STORES["keio"]["url"], "start": None, "end": None,
            "pages": []})
        leaf["pages"].append({"kind": "image", "url": html.unescape(src)})
    return list(leaflets.values())


def fetch_keio():
    return parse_kurashiru(http_get(STORES["keio"]["url"]).decode("utf-8"))


# --- オオゼキ ---------------------------------------------------------------

def parse_ozeki(page_html):
    """Leaflets of this shop, each pointing at its digital-leaflet viewer.

    The PDF links on the page are served by a host that refuses non-Japanese
    IPs (GitHub Actions), so pages are read from the viewer's image tiles.
    """
    a = page_html.find('id="shop_flyer"')
    b = page_html.find("shop_flyer end", a)
    section = page_html[a:b if b > 0 else None]
    leaflets = []
    for block in section.split('class="shop_flyer_data_list"')[1:]:
        viewer = re.search(r'href="(https://ozeki\.meclib\.jp/library/books/([^/"]+)/book/)', block)
        if not viewer:
            continue
        title = re.search(r"<p>(.*?)</p>", block, re.S)
        data_id = viewer.group(2).split("_")[1].zfill(8)
        leaflets.append({
            "id": f"ozeki-{data_id}", "store": "ozeki",
            "title": html.unescape(title.group(1)).strip() if title else "",
            "source_url": viewer.group(1) + "index.html", "book": viewer.group(1),
            "start": None, "end": None})
    return leaflets


def parse_meclib_book(book, base):
    """book: parsed data/book.txt of a meclib viewer, base: its .../book/ URL."""
    w = book["thumb_width"] * MECLIB_SCALE
    h = book["thumb_height"] * MECLIB_SCALE
    tile = book["slice_width"]
    count = math.ceil(w / tile) * math.ceil(h / tile)
    # split: these leaflets are too dense for the model to read in one image.
    return [{"kind": "tiles", "w": w, "h": h, "tile": tile, "split": 2,
             "urls": [f"{base}jpg_{MECLIB_SCALE}/{p:04d}/{i:04d}.jpg" for i in range(1, count + 1)]}
            for p in range(1, book["total_page"] + 1)]


def fetch_ozeki():
    out = parse_ozeki(http_get(STORES["ozeki"]["url"]).decode("utf-8", "replace"))
    for leaf in out:
        base = leaf.pop("book")
        leaf["pages"] = parse_meclib_book(json.loads(http_get(base + "data/book.txt")), base)
    return out


# --- ヤオコー ---------------------------------------------------------------

def _utc_to_jst_date(s):
    dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.astimezone(JST).strftime("%Y-%m-%d")


def parse_yaoko(summary, detail):
    """summary: one entry of /api/flyers, detail: `data` of /api/flyer."""
    keys = sorted((k for k in detail if re.fullmatch(r"image\d*", k) and detail[k]),
                  key=lambda k: int(k[5:] or 1))
    return {
        "id": f"yaoko-{summary['flyer_id']}", "store": "yaoko",
        "title": summary["title"], "source_url": summary["viewer_url"],
        "start": _utc_to_jst_date(summary["datetime_start"]),
        "end": _utc_to_jst_date(summary["datetime_end"]),
        "pages": [{"kind": "image", "url": YAOKO_BASE + detail[k]} for k in keys]}


def fetch_yaoko():
    api = f"{YAOKO_BASE}api/"
    flyers = json.loads(http_get(f"{api}flyers?shop_code={YAOKO_SHOP_CODE}"))["data"]["flyers"]
    out = []
    for f in flyers:
        detail = json.loads(http_get(
            f"{api}flyer?shop_code={YAOKO_SHOP_CODE}&flyer_id={f['flyer_id']}"))["data"]
        out.append(parse_yaoko(f, detail))
    return out


# --- サミット (Shufoo) -------------------------------------------------------

def _shufoo_xml(xml_bytes):
    # Shufoo serves Shift_JIS, which expat cannot decode by itself.
    text = xml_bytes.decode("cp932", "replace")
    return ET.fromstring(re.sub(r"^<\?xml[^>]*\?>", "", text))


def parse_shufoo_shop(xml_bytes):
    root = _shufoo_xml(xml_bytes)
    out = []
    for c in root.iter("chirashi"):
        day = lambda tag: c.findtext(tag)[:10].replace("/", "-")
        out.append({
            "id": f"summit-{c.findtext('id')}", "store": "summit",
            "title": c.findtext("title"), "source_url": c.findtext("portal"),
            "start": day("publishStartTime"), "end": day("publishEndTime"),
            "content_uri": c.findtext("contentURI")})
    return out


def parse_shufoo_contents(xml_bytes, content_uri):
    conf = _shufoo_xml(xml_bytes).find("configration")  # sic: Shufoo's spelling
    w = int(conf.findtext("bookW")) * SHUFOO_SCALE
    h = int(conf.findtext("bookH")) * SHUFOO_SCALE
    base = f"{content_uri}index/{conf.findtext('imgPrefix').split('/')[-1]}/"
    count = math.ceil(w / SHUFOO_TILE) * math.ceil(h / SHUFOO_TILE)
    return [{"kind": "tiles", "w": w, "h": h, "tile": SHUFOO_TILE,
             "urls": [f"{base}{p}_{SHUFOO_SCALE * 100}_{i}.jpg" for i in range(count)]}
            for p in range(int(conf.findtext("totalPages")))]


def fetch_summit():
    out = parse_shufoo_shop(http_get(
        f"https://www.shufoo.net/api/shopDetailNewXML/{SHUFOO_SHOP_ID}/"))
    for leaf in out:
        uri = leaf.pop("content_uri")
        leaf["pages"] = parse_shufoo_contents(http_get(f"{uri}index/contents.xml"), uri)
    return out


def stitch_tiles(page):
    from PIL import Image
    cols = math.ceil(page["w"] / page["tile"])
    canvas = Image.new("RGB", (page["w"], page["h"]), "white")
    for i, url in enumerate(page["urls"]):
        tile = Image.open(io.BytesIO(http_get(url)))
        canvas.paste(tile, ((i % cols) * page["tile"], (i // cols) * page["tile"]))
    return canvas


def split_boxes(w, h, parts, overlap=0.06):
    """Vertical strips covering the image, overlapping so no product is cut in two."""
    step, pad = w / parts, int(w * overlap / 2)
    return [(max(0, round(i * step) - pad), 0, min(w, round((i + 1) * step) + pad), h)
            for i in range(parts)]


def _jpeg(image):
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def period_from_title(title, today):
    """(start, end) from titles like "…（11/14～11/20）", "11/14(土)～17(火)", "11月21日(土)"."""
    m = re.search(r"(\d{1,2})/(\d{1,2})(?:\([^)]*\))?\s*[～〜~－-]\s*(?:(\d{1,2})/)?(\d{1,2})", title)
    if m:
        m1, d1, m2, d2 = int(m[1]), int(m[2]), int(m[3] or m[1]), int(m[4])
    else:
        m = re.search(r"(\d{1,2})月(\d{1,2})日", title)
        if not m:
            return None, None
        m1, d1 = m2, d2 = int(m[1]), int(m[2])
    year, month = int(today[:4]), int(today[5:7])
    # Leaflets are always near today: a far-off month belongs to the adjacent year.
    fix = lambda mm: year + (1 if mm - month < -6 else -1 if mm - month > 6 else 0)
    return f"{fix(m1)}-{m1:02d}-{d1:02d}", f"{fix(m2)}-{m2:02d}-{d2:02d}"


# ---------------------------------------------------------------------------

FETCHERS = {"keio": fetch_keio, "summit": fetch_summit,
            "yaoko": fetch_yaoko, "ozeki": fetch_ozeki}


def load_page(page):
    """Return the images to send for one leaflet page as [(bytes, mime_type), ...]."""
    if page["kind"] != "tiles":
        return [(http_get(page["url"]), "image/jpeg")]
    image = stitch_tiles(page)
    boxes = split_boxes(image.width, image.height, page.get("split", 1))
    return [(_jpeg(image.crop(box)), "image/jpeg") for box in boxes]
