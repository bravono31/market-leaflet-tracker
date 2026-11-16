"""Price extraction from leaflet images/PDFs with the Gemini API (free tier)."""
import base64
import json
import os
import re
import urllib.error
import urllib.request

API = "https://generativelanguage.googleapis.com/v1beta"

CATEGORIES = ["野菜・果物", "肉", "魚", "惣菜・弁当", "乳製品・卵", "パン・米・麺",
              "加工食品・調味料", "冷凍食品", "菓子", "飲料", "酒", "日用品", "その他"]

_STR = {"type": "STRING"}
_NSTR = {"type": "STRING", "nullable": True}
_NNUM = {"type": "NUMBER", "nullable": True}

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "period_start": _NSTR,
        "period_end": _NSTR,
        "campaigns": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"name": _STR, "detail": _NSTR, "start": _NSTR, "end": _NSTR},
            "required": ["name"]}},
        "items": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {
                "name": _STR, "key": _STR,
                "category": {"type": "STRING", "enum": CATEGORIES},
                "price": _NNUM, "price_tax_in": _NNUM,
                "unit": _NSTR, "start": _NSTR, "end": _NSTR,
                "note": _NSTR, "packaged": {"type": "BOOLEAN"}},
            "required": ["name", "key", "category", "packaged"]}},
    },
    "required": ["campaigns", "items"],
}

PROMPT = """\
これは日本のスーパー「{store}」のチラシ「{title}」です。今日は{today}です。
チラシに価格が明記されている商品をすべて抽出してください。

items の各項目:
- name: チラシの表記どおりの商品名（産地・メーカー・内容量を含める）
- key: 店をまたいで同じ商品を突き合わせるための正規化名。
  生鮮品は産地や修飾語を除いた一般名（例:「豚こま切れ肉」「ほうれん草」「バナナ」）。
  加工品は「メーカー 商品名 内容量」（例:「キユーピー マヨネーズ 450g」）。
  下の「既存のkey」に同じ商品があれば、必ずその文字列をそのまま使う。
- price: 税抜の本体価格（円・数値）。price_tax_in: 税込価格（円・数値）。印字が無い方は null。
- unit: 価格の単位（例:「100g」「1パック」「1袋」「1本」「2点」）。
  「よりどり2点で◯円」は2点合計の価格を入れ unit を「2点」にする。
- start / end: その価格が有効な日（YYYY-MM-DD）。日替り・◯日限りは該当日、指定が無ければ null。
- note: 「会員価格」「お1人様1点限り」「ポイント+10」などの条件。無ければ null。
- packaged: メーカー品などネット通販でも同じ物が買える商品なら true、生鮮・惣菜は false。

「◯割引」「半額」「ポイント◯倍」など価格が書かれていない企画は items に入れず、
campaigns に name（例:「冷凍食品 ポイント10倍」）、detail、start、end を入れる。
period_start / period_end はチラシ全体の有効期間（YYYY-MM-DD）。年は今日の日付から判断する。

既存のkey:
{known_keys}
"""


class QuotaExceeded(Exception):
    pass


def _call(method, url, key, body=None):
    req = urllib.request.Request(
        url, method=method, data=json.dumps(body).encode() if body else None,
        headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        if e.code == 429:
            raise QuotaExceeded(detail) from None
        raise RuntimeError(f"Gemini API {e.code}: {detail}") from None


def pick_model(key):
    """GEMINI_MODEL if set, otherwise the newest stable Flash model on offer."""
    if os.environ.get("GEMINI_MODEL"):
        return os.environ["GEMINI_MODEL"]
    best = None
    for m in _call("GET", f"{API}/models?pageSize=1000", key).get("models", []):
        name = m["name"].split("/")[-1]
        ver = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash", name)
        if ver and "generateContent" in m.get("supportedGenerationMethods", []):
            best = max(best or (0.0, ""), (float(ver.group(1)), name))
    if not best:
        raise RuntimeError("No Gemini Flash model found; set GEMINI_MODEL.")
    return best[1]


def extract(key, model, store_name, title, today, pages, known_keys):
    """pages: list of (bytes, mime_type). Returns the parsed JSON dict."""
    parts = [{"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}}
             for data, mime in pages]
    parts.append({"text": PROMPT.format(
        store=store_name, title=title, today=today,
        known_keys="\n".join(known_keys) or "（まだ無し）")})
    res = _call("POST", f"{API}/models/{model}:generateContent", key, {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 65536,
                             "responseMimeType": "application/json",
                             "responseSchema": SCHEMA}})
    cand = res["candidates"][0]
    if cand.get("finishReason") != "STOP":
        raise RuntimeError(f"Gemini stopped early: {cand.get('finishReason')}")
    return json.loads(cand["content"]["parts"][0]["text"])
