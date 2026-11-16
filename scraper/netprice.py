"""Online reference prices from the Yahoo!ショッピング item search API (free)."""
import json
import urllib.parse
import urllib.request

API = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"


def parse_hits(body, limit=3):
    offers = [{"title": h["name"], "price": h["price"], "url": h["url"],
               "shop": (h.get("seller") or {}).get("name")}
              for h in body.get("hits", []) if h.get("price")]
    return sorted(offers, key=lambda o: o["price"])[:limit]


def search(app_id, query):
    """Cheapest offers among the 10 most relevant hits for `query`."""
    qs = urllib.parse.urlencode({"appid": app_id, "query": query, "results": 10})
    with urllib.request.urlopen(f"{API}?{qs}", timeout=30) as res:
        return parse_hits(json.loads(res.read()))
