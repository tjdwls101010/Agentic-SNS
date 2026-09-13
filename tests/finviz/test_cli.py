import json


def test_lookup_preserves_identity_and_can_reread_original_response(client):
    source = {'results': [{'ticker': 'A', 'company': 'Agilent Technologies', 'exchange': 'NYSE', 'newField': 17}]}
    client.add('https://finviz.com/api/suggestions?input=Agilent', source)
    result = client.run('lookup', 'Agilent')
    assert result['data'] == source
    assert result['source']['url'].endswith('input=Agilent')
    assert result['source']['received_complete'] is True
    saved = client.run('read', result['id'], '--pointer', '/data/results/0')
    assert saved['data']['ticker'] == 'A'
    raw = client.run('read', result['id'], '--raw')
    assert json.loads(raw['data']) == source


def test_screener_keeps_ticker_identity_conditions_and_continuation(client):
    url = 'https://finviz.com/screener?ft=4&v=152&f=sec_technology&c=1%2C6%2C7&r=21'
    page = '''<select id="fs_sec"><option value="">Any</option><option selected value="technology">Technology</option></select>
    <script id="route-init-data" type="application/json">{"tableSettings":{"selectedColumns":["ticker","marketCap","PE"],"columnsMap":{"ticker":{"index":1},"marketCap":{"index":6},"PE":{"index":7}}}}</script>
    <table class="screener_table"><tr><th>Ticker</th><th>Market Cap</th><th>P/E</th></tr><tr><td><a href="/quote.ashx?t=NVDA"><span>N</span>NVDA</a></td><td>4.2T</td><td>32.1</td></tr></table>
    <a href="/screener?ft=4&v=152&f=sec_technology&c=1%2C6%2C7&r=41">Next</a>'''
    client.add(url, page)
    result = client.run('screen', '--filter', 'sec_technology', '--view', '152', '--columns', '1,6,7', '--start', '21')
    assert result['data']['tables'][0]['rows'][0]['ticker'] == 'NVDA'
    assert len(result['data']['tables'][0]['rows'][0]['cells']) == 3
    assert result['conditions']['f']['status'] == 'confirmed'
    assert result['conditions']['r']['status'] == 'unverified'
    assert result['coverage']['received'] == 1
    assert 'r=41' in result['continuation']
    assert result['coverage']['exhaustive'] is False


def test_stock_preserves_duplicate_metrics_definitions_and_initial_data(client):
    page = '''<h1>Agilent</h1><table class="snapshot-table2"><tr><td data-boxover-html="EPS estimate for next year">EPS next Y</td><td>6.74</td><td data-boxover-html="EPS growth next year">EPS next Y</td><td>8.75%</td></tr><tr><td data-boxover-html="Quarterly earnings growth (YoY)">EPS Q/Q</td><td>-</td></tr></table>
    <script id="route-init-data" type="application/json">{"currentExpiry":"2026-10-16","options":[{"volume":0,"iv":null,"newField":7}]}</script>'''
    client.add('https://finviz.com/stock?t=A&ty=oc&e=2026-10-16', page)
    result = client.run('stock', 'A', '--section', 'options', '--expiry', '2026-10-16')
    metrics = result['data']['metrics']
    assert [m['value'] for m in metrics] == ['6.74', '8.75%', '-']
    assert metrics[1]['unit'] == '%'
    assert metrics[2]['definition'] == 'Quarterly earnings growth (YoY)'
    assert result['conditions']['e']['status'] == 'confirmed'
    assert result['data']['initial']['route-init-data']['options'][0] == {'volume': 0, 'iv': None, 'newField': 7}


def test_statement_and_price_series_preserve_data_and_flag_misaligned_arrays(client):
    statement = {'currency':'USD','data':{'Period':['TTM','2025FY','2024FY','2023FY'],'EPS':[1.25,1.2,0,None]}}
    client.add('https://finviz.com/api/statement?t=A&so=F&s=IA', statement)
    result = client.run('stock','A','--section','income')
    assert result['data'] == statement
    bars = {'date':[20260910,20260911], 'open':[100,101], 'high':[103,104], 'low':[99,100], 'close':[102], 'volume':[0,20], 'lastTime':1789084800}
    client.add('https://finviz.com/api/quote?instrument=stock&ticker=A&timeframe=d&barsCount=30', bars)
    result = client.run('prices','A')
    assert result['status'] == 'partial'
    assert result['data'] == bars
    assert result['errors'][0]['code'] == 'array_alignment'
    assert client.run('read',result['id'],'--pointer','/data/date')['data'] == [20260910,20260911]


def test_calendar_continuation_uses_observed_page_and_retains_dates(client):
    url = 'https://finviz.com/api/calendar/earnings?dateFrom=2026-09-15&page=1&sort=earningsDate'
    source = {'items':[{'ticker':'A','earningsDate':'2026-09-15T08:30:00','isEarningDateEstimate':True,'epsActual':None,'epsEstimate':1.2}], 'page':1,'pageSize':50,'totalItemsCount':51,'totalPages':2}
    client.add(url, source)
    result = client.run('calendar','earnings','--date','2026-09-15')
    assert result['data'] == source
    assert result['conditions']['page']['status'] == 'confirmed'
    assert result['conditions']['dateFrom']['status'] == 'unverified'
    assert result['coverage']['source_total'] == 51
    assert result['continuation'].endswith('page=2&sort=earningsDate')
