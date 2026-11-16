import unittest

from scraper import netprice, run, stores

KURASHIRU = '''
<li class="X-leafletItem" data-leaflet-id="101"><div>cover</div>
<img class="X-leafletImage" alt="京王ストア 11/14(土)～17(火)：特売" src="https://img.example/101/a.jpg" /></li>
<li class="X-leafletItem" data-leaflet-id="102"><div>cover</div>
<img class="X-leafletImage" alt="京王ストア 11/14(土)～17(火)：特売" src="https://img.example/102/a.jpg" /></li>
<li class="X-leafletItem" data-leaflet-id="90"><div>cover</div>
<img class="X-leafletImage" alt="京王ストア ●11月カレンダー●" src="https://img.example/90/c.jpg" /></li>
<ul class="X-leafletsList"><li class="X-leafletsListItem" data-leaflet-id="102"><img src="https://img.example/102/a.jpg" /></li></ul>
'''

OZEKI = '''
<section id="other"><a href="https://ozeki.digimu.jp/data/00000001/img/thum/a1.pdf">other shop</a></section>
<section id="shop_flyer" class="shop_flyer">
<div class="shop_flyer_data_list"><div class="shop_flyer_data_date"><p>日替わり（11/14～11/20）</p></div>
 <a href="https://ozeki.meclib.jp/library/books/261114_26650_a5b5/book/index.html">デジタルチラシ</a>
 <a href="https://ozeki.digimu.jp/data/00026650/img/thum/a5.pdf">表</a>
 <a href="https://ozeki.digimu.jp/data/00026650/img/thum/b5.pdf">裏</a></div>
<div class="shop_flyer_data_list"><div class="shop_flyer_data_date"><p>お鍋フェアー</p></div>
 <a href="https://ozeki.digimu.jp/data/00026669/img/thum/a1.pdf">表</a></div>
</section><!-- shop_flyer end -->
<a href="https://ozeki.digimu.jp/data/00000002/img/thum/a1.pdf">footer</a>
'''

SHUFOO_SHOP = '''<?xml version="1.0" encoding="Shift_JIS"?><shop><shopName>サミット</shopName><chirashis>
<chirashi><id>47</id><title>11月14日(土)～11月16日(月)号</title>
<contentURI>https://ipq.example/c/2026/11/11/47/</contentURI><portal>https://shufoo.example/47/</portal>
<publishStartTime>2026/11/13 12:00:00</publishStartTime><publishEndTime>2026/11/16 23:59:59</publishEndTime>
</chirashi></chirashis></shop>'''.encode("cp932")

SHUFOO_CONTENTS = b'''<?xml version="1.0" encoding="Shift_JIS"?><libook><configration>
<imgPrefix>index/img</imgPrefix><totalPages>2</totalPages><bookW>769</bookW><bookH>540</bookH>
</configration></libook>'''


class ParserTests(unittest.TestCase):
    def test_kurashiru_groups_front_and_back(self):
        got = stores.parse_kurashiru(KURASHIRU)
        self.assertEqual([l["id"] for l in got], ["keio-101", "keio-90"])
        self.assertEqual([p["url"] for p in got[0]["pages"]],
                         ["https://img.example/101/a.jpg", "https://img.example/102/a.jpg"])
        self.assertEqual(len(got[1]["pages"]), 1)

    def test_ozeki_only_reads_this_shops_section(self):
        got = stores.parse_ozeki(OZEKI)
        self.assertEqual([l["id"] for l in got], ["ozeki-00026650"])
        self.assertEqual(got[0]["title"], "日替わり（11/14～11/20）")
        self.assertEqual(got[0]["book"], "https://ozeki.meclib.jp/library/books/261114_26650_a5b5/book/")
        self.assertEqual(got[0]["source_url"], got[0]["book"] + "index.html")

    def test_meclib_tiles(self):
        book = {"thumb_width": 1545, "thumb_height": 1105, "slice_width": 500, "total_page": 2}
        pages = stores.parse_meclib_book(book, "https://m/book/")
        self.assertEqual(len(pages), 2)
        self.assertEqual((pages[0]["w"], pages[0]["h"], pages[0]["tile"]), (3090, 2210, 500))
        self.assertEqual(len(pages[0]["urls"]), 35)
        self.assertEqual(pages[0]["urls"][0], "https://m/book/jpg_2/0001/0001.jpg")
        self.assertEqual(pages[1]["urls"][-1], "https://m/book/jpg_2/0002/0035.jpg")

    def test_yaoko_pages_and_jst_dates(self):
        summary = {"flyer_id": 1192, "title": "11月11日号", "viewer_url": "https://v/1192",
                   "datetime_start": "2026-11-09T22:00:00Z", "datetime_end": "2026-11-17T14:59:59Z"}
        detail = {"image2": "assets/b.jpg", "image": "assets/a.jpg", "thumb_image": "assets/t.jpg",
                  "image3": "", "page_count": 2}
        got = stores.parse_yaoko(summary, detail)
        self.assertEqual((got["start"], got["end"]), ("2026-11-10", "2026-11-17"))
        self.assertEqual([p["url"] for p in got["pages"]],
                         [stores.YAOKO_BASE + "assets/a.jpg", stores.YAOKO_BASE + "assets/b.jpg"])

    def test_shufoo_shift_jis_xml_and_tiles(self):
        leaf = stores.parse_shufoo_shop(SHUFOO_SHOP)[0]
        self.assertEqual((leaf["id"], leaf["start"], leaf["end"]),
                         ("summit-47", "2026-11-13", "2026-11-16"))
        self.assertEqual(leaf["title"], "11月14日(土)～11月16日(月)号")
        pages = stores.parse_shufoo_contents(SHUFOO_CONTENTS, leaf["content_uri"])
        self.assertEqual(len(pages), 2)
        self.assertEqual((pages[1]["w"], pages[1]["h"], pages[1]["tile"]), (3076, 2160, 512))
        self.assertEqual(len(pages[1]["urls"]), 35)
        self.assertEqual(pages[1]["urls"][0], "https://ipq.example/c/2026/11/11/47/index/img/1_400_0.jpg")
        self.assertEqual(pages[1]["urls"][-1], "https://ipq.example/c/2026/11/11/47/index/img/1_400_34.jpg")


class ImageTests(unittest.TestCase):
    def test_split_boxes_cover_with_overlap(self):
        self.assertEqual(stores.split_boxes(3090, 2210, 1), [(0, 0, 3090, 2210)])
        left, right = stores.split_boxes(3000, 2000, 2)
        self.assertEqual((left[0], right[2]), (0, 3000))
        self.assertEqual(left[2] - right[0], 180)  # 6% of the width is shared

    def test_period_from_title(self):
        f = lambda t, today="2026-11-16": stores.period_from_title(t, today)
        self.assertEqual(f("日替わりチラシ開催中！（11/14～11/20）"), ("2026-11-14", "2026-11-20"))
        self.assertEqual(f("京王ストア 11/14(土)～17(火)：特売"), ("2026-11-14", "2026-11-17"))
        self.assertEqual(f("【府中店】11月21日(土)　お鍋フェアー"), ("2026-11-21", "2026-11-21"))
        self.assertEqual(f("年末年始（12/28～1/3）", "2026-12-27"), ("2026-12-28", "2027-01-03"))
        self.assertEqual(f("年末年始（12/28～1/3）", "2027-01-02"), ("2026-12-28", "2027-01-03"))
        self.assertEqual(f("オオゼキオンラインセール開催！"), (None, None))


class RecordTests(unittest.TestCase):
    LEAF = {"id": "keio-1", "store": "keio", "title": "t", "source_url": "u",
            "start": None, "end": None}

    def test_dates_fall_back_item_then_leaflet_then_today(self):
        result = {"period_start": "2026-11-14", "period_end": "2026-11-17", "campaigns": [],
                  "items": [
                      {"name": "A", "key": " a ", "category": "肉", "price": 100, "packaged": False},
                      {"name": "B", "key": "b", "category": "肉", "price_tax_in": 108,
                       "start": "2026-11-15", "packaged": True},
                      {"name": "B", "key": "b2", "category": "肉", "price_tax_in": 108,
                       "start": "2026-11-15", "packaged": True},
                      {"name": "no price", "key": "c", "category": "肉", "packaged": False}]}
        record, items = run.build_records(self.LEAF, result, "2026-11-16")
        self.assertEqual((record["start"], record["end"]), ("2026-11-14", "2026-11-17"))
        self.assertEqual([i["key"] for i in items], ["a", "b"])
        self.assertEqual((items[0]["start"], items[0]["end"]), ("2026-11-14", "2026-11-17"))
        self.assertEqual((items[1]["start"], items[1]["end"]), ("2026-11-15", "2026-11-15"))

        record, _ = run.build_records(self.LEAF, {"items": []}, "2026-11-16")
        self.assertEqual((record["start"], record["end"]), ("2026-11-16", "2026-11-16"))

    def test_merge_pages(self):
        got = run.merge_pages([
            {"period_start": None, "campaigns": [{"name": "c1"}], "items": [{"name": "a"}]},
            {"period_start": "2026-11-14", "period_end": "2026-11-17", "campaigns": [],
             "items": [{"name": "b"}]}])
        self.assertEqual((got["period_start"], got["period_end"]), ("2026-11-14", "2026-11-17"))
        self.assertEqual([i["name"] for i in got["items"]], ["a", "b"])
        self.assertEqual(got["campaigns"], [{"name": "c1"}])

    def test_net_targets_only_packaged_and_stale(self):
        item = lambda key, packaged, end="2026-11-16": {"key": key, "packaged": packaged, "end": end}
        items = [item("fresh", False), item("new", True), item("recent", True),
                 item("stale", True, "2026-11-10"), item("new", True)]
        net = {"recent": {"fetched": "2026-11-12"}, "stale": {"fetched": "2026-11-09"}}
        self.assertEqual(run.net_targets(items, net, "2026-11-16"), ["new", "stale"])

    def test_yahoo_hits_sorted_by_price(self):
        body = {"hits": [{"name": "x", "price": 300, "url": "u1", "seller": {"name": "s"}},
                         {"name": "y", "price": 120, "url": "u2"},
                         {"name": "z", "price": 0, "url": "u3"}]}
        got = netprice.parse_hits(body)
        self.assertEqual([o["price"] for o in got], [120, 300])
        self.assertEqual(got[1]["shop"], "s")


if __name__ == "__main__":
    unittest.main()
