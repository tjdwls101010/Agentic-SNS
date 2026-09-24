from pages import article_page, news_page, pulse_page


def test_news_headlines_by_time_by_source_and_stock_badges(client):
    client.add("https://finviz.com/news", news_page())
    assert client.one("news", "headlines")["data"]["headlines"] == [{"time": "06:56AM", "title": "Stocks Fall as Oil Rally", "url": "https://www.bloomberg.com/a", "source": "Bloomberg", "section": "News", "tickers": []}, {"time": "06:30AM", "title": "Paramount Dividend Analysis", "url": "https://finance.yahoo.com/b", "source": "GuruFocus.com", "section": "Blogs", "tickers": ["PSKY"]}]
    client.add("https://finviz.com/news?v=2", news_page(by_source=True))
    by_source = client.one("news", "headlines", "--kind", "by-source")["data"]["headlines"]
    assert [i["source"] for i in by_source] == ["Bloomberg", "GuruFocus.com"] and by_source[0]["section"] == "Bloomberg"
    client.add("https://finviz.com/news?v=3", news_page(sections=()))
    stocks = client.one("news", "headlines", "--kind", "stocks", "--filter", "PSKY")["data"]["headlines"]
    assert stocks[0]["tickers"] == ["PSKY"] and stocks[0]["section"] is None


def test_the_default_keeps_every_section_and_the_search_covers_the_whole_response(client):
    items = [("0%d:00AM" % (i % 10), "Headline %d" % i, "https://example.com/%d" % i, "Source", ()) for i in range(60)]
    client.add("https://finviz.com/news", news_page(items=tuple(items)))
    result = client.one("news", "headlines")
    assert {i["section"] for i in result["data"]["headlines"]} == {"News", "Blogs"} and len(result["data"]["headlines"]) == 40
    assert result["coverage"] == {"received": 60, "matched": 40, "shown": 40, "start": 0}
    found = client.one("news", "headlines", "--filter", "Headline 55")
    assert [i["title"] for i in found["data"]["headlines"]] == ["Headline 55"] and found["coverage"]["received"] == 60
    everything = client.one("read", result["id"], "--per-section", "0", "--start", "40", "--limit", "5")
    assert everything["coverage"]["matched"] == 60 and len(everything["data"]["headlines"]) == 5  # the store keeps what the window left out


def test_market_pulse_lists_rows_and_reads_one_explanation(client):
    client.add("https://finviz.com/news?v=6", pulse_page())
    assert client.one("news", "pulse")["data"]["entries"] == [{"id": 285611, "age": "7 min", "headline": "VEON signs memorandum", "tickers": ["VEON"]}, {"id": 285537, "age": "2 hours", "headline": "US equity futures point lower", "tickers": ["$MARKET"]}]
    detail = {"id": 285537, "ticker": "$MARKET", "dateTime": "2026-09-15T05:36:38.943", "headline": "US equity futures point lower", "summary": "- S&P 500 futures **fall 0.59%**", "source": "market_summary", "sentiment": "bad", "catalyst": False, "instrument": 0, "bulletPointsList": None}
    client.add("https://finviz.com/api/stocks-why-moving/by-id/285537", detail)
    assert client.one("news", "pulse", "285537")["data"]["entries"] == [detail]
    assert client.one("news", "pulse", "abc", code=2)["error"]["code"] == "invalid_argument"


def test_an_article_is_paragraph_records_and_other_hosts_are_refused(client):
    client.add("https://finviz.com/news/123/fed-decision-preview", article_page())
    data = client.one("news", "article", "https://finviz.com/news/123/fed-decision-preview")["data"]
    assert data == {"title": "Fed Decision Preview", "links": [{"text": "SEC filing", "url": "https://www.sec.gov/x"}], "images": ["https://finviz.com/img/chart.png"], "paragraphs": [{"text": "First paragraph."}, {"text": "Second paragraph."}]}
    assert client.one("news", "article", "https://www.marketwatch.com/story/x", code=2)["error"]["code"] == "unsupported_url"
    assert client.one("news", "article", "https://finviz.com/screener", code=2)["error"]["code"] == "unsupported_url"


def test_a_tickers_newest_pulse_is_one_entry_or_empty(client):
    entry = {"id": 292108, "ticker": "NVDA", "dateTime": "2026-09-23T08:30:20.06", "headline": "Nvidia director sold stock", "summary": None, "source": "news_summary", "sentiment": "neutral", "catalyst": False, "instrument": 0, "bulletPointsList": None}
    client.add("https://finviz.com/api/stocks-why-moving/NVDA", entry)
    result = client.one("news", "pulse", "--ticker", "NVDA")
    assert result["data"]["entries"] == [entry] and result["conditions"]["ticker"]["status"] == "confirmed"
    client.add("https://finviz.com/api/stocks-why-moving/AAPL", "", status=204)
    assert client.one("news", "pulse", "--ticker", "AAPL", code=7)["data"]["entries"] == []
