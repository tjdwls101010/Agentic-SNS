from pages import insiders_page


def test_insider_trades_keep_ticker_owner_and_filing_links_and_confirm_the_transaction_filter(client):
    client.add("https://finviz.com/insidertrading?tc=2", insiders_page(transaction="insidertrading?tc=2"))
    result = client.one("insiders", "trades", "--transaction", "sale")
    row = result["data"]["trades"][0]
    assert row["Ticker"] == "ENLT" and row["ticker"] == "ENLT" and row["Owner"] == "Paz Amit" and row["Transaction"] == "Sale"
    assert row["owner_url"] == "https://finviz.com/insidertrading?oc=2108367&tc=7&b=2" and row["filing_url"] == "http://www.sec.gov/Archives/edgar/data/1/x.xml"
    assert result["conditions"]["transaction"] == {"requested": "sale", "status": "confirmed", "evidence": "Sale Transactions"}
    assert result["data"]["sort_keys"] == {"Ticker": "ticker"}
    client.add("https://finviz.com/insidertrading?tc=7&oc=2108367", insiders_page())
    assert client.one("insiders", "trades", "--owner", "2108367")["conditions"]["owner"]["status"] == "unverified"


def test_the_default_is_one_screenful_of_trades(client):
    rows = tuple(("T%d" % n, "Owner %d" % n, str(n), "Director", "Sep 12 '26", "Sale", "42.10", "10,000", "421,000", "50,000", "Sep 14 09:55 PM", "http://www.sec.gov/x.xml") for n in range(40))
    client.add("https://finviz.com/insidertrading?tc=7", insiders_page(rows=rows))
    trades = client.one("insiders", "trades")
    assert trades["coverage"] == {"received": 40, "matched": 40, "shown": 20, "start": 0, "cut": "default"}


def test_a_preset_is_the_sources_own_recent_week_view_and_its_active_button_confirms_it(client):
    buttons = '<a class="fv-button is-small is-border" href="insidertrading?or=-10&tv=100000&tc=7&o=-transactionValue">Top Insider Trading Recent Week</a><a class="fv-button is-small is-border is-active" href="insidertrading?or=10&tv=1000000&tc=7&o=-transactionValue">Top 10% Owner Trading Recent Week</a>'
    client.add("https://finviz.com/insidertrading?or=10&tv=1000000&o=-transactionValue&tc=7", insiders_page().replace("<body>", "<body>" + buttons))
    result = client.one("insiders", "trades", "--preset", "top-owner")
    assert result["conditions"]["preset"] == {"requested": "top-owner", "status": "confirmed", "evidence": "Top 10% Owner Trading Recent Week"}
    client.add("https://finviz.com/insidertrading?or=-10&tv=100000&o=-transactionValue&tc=7", insiders_page().replace("<body>", "<body>" + buttons))
    assert client.one("insiders", "trades", "--preset", "top-insider")["conditions"]["preset"]["status"] == "not_applied"
    assert client.one("insiders", "trades", "--sort", "bogus", code=2)["error"]["code"] == "invalid_argument"


def test_a_value_threshold_and_an_order_go_to_the_source(client):
    client.add("https://finviz.com/insidertrading?tc=7&o=-transactionvalue&tv=1000000", insiders_page())
    result = client.one("insiders", "trades", "--value", "1000000", "--sort=-transactionvalue")
    assert result["conditions"]["value"]["requested"] == 1000000 and result["conditions"]["sort"]["requested"] == "-transactionvalue"
