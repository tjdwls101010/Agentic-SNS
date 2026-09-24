"""Market-wide insider trades with owner pages and SEC Form 4 links."""

from urllib.parse import urlencode, urljoin

import markup
from contract import Collection, condition, leaf

TRANSACTIONS = {"all": "7", "buy": "1", "sale": "2"}
SORTS = ["ticker", "transactiondate", "transactionpricepershare", "transactionshares", "transactionvalue", "sharesownedfollowingtransaction", "accepted"]
# Each preset is the source's own recent-week button: its relationship filter, value threshold and order.
PRESETS = {"top-insider": ({"or": "-10", "tv": "100000", "o": "-transactionValue"}, "Top Insider Trading Recent Week"), "top-owner": ({"or": "10", "tv": "1000000", "o": "-transactionValue"}, "Top 10% Owner Trading Recent Week")}


@leaf(
    "insiders",
    "trades",
    help="Latest insider trades across the market, with owner pages and SEC Form 4 links.",
    args=[
        (("--transaction",), dict(default="all", choices=list(TRANSACTIONS), help="Transaction type.")),
        (("--owner",), dict(default=None, help="Owner id from a row's owner_url to list one insider's trades.")),
        (("--sort",), dict(default=None, choices=SORTS + ["-" + k for k in SORTS], metavar="KEY", help="Source order: " + ", ".join(SORTS) + "; write --sort=-transactionvalue for descending.")),
        (("--value",), dict(type=int, default=None, help="Keep trades whose value is at least this many dollars (source filter).")),
        (("--preset",), dict(default=None, choices=list(PRESETS), help="The source's recent-week buttons: top-insider (Top Insider Trading Recent Week, trades of $100,000 or more) or top-owner (Top 10% Owner Trading Recent Week, 10% owners' trades of $1,000,000 or more), largest first; --value and --sort override the threshold and order.")),
    ],
    collections={"trades": Collection("rows keyed by the table headers plus ticker, url (stock page), owner_url and filing_url, in the source's order (newest first unless --sort)", default=20)},
    context={"sort_keys": "column label -> the key --sort accepts for it, from this table's header links"},
)
def trades(ctx, args, target):
    preset = dict(PRESETS[args.preset][0]) if args.preset else {}
    query = dict(preset, tc=TRANSACTIONS[args.transaction], oc=args.owner) | {k: v for k, v in (("o", args.sort), ("tv", args.value)) if v is not None}
    obs = ctx.observe("https://finviz.com/insidertrading?" + urlencode({k: v for k, v in query.items() if v is not None}))
    page = markup.soup(obs)
    node = page.select_one("table#insider-table")
    if node is None:
        raise obs.fail("structure_changed", "No insider table was found.", "Read the saved raw page with read ID --raw.")
    rows = markup.table_records(node, obs.url)[1]
    trs = [tr for tr in node.select("tr") if tr.find_all("td", recursive=False)]
    for row, tr in zip(rows, trs):
        links = [urljoin(obs.url, a["href"]) for a in tr.select("a[href]")]
        row["owner_url"] = next((u for u in links if "insidertrading" in u), None)
        row["filing_url"] = next((u for u in links if "sec.gov" in u), None)
    controls = markup.selects(page)
    chosen = [o["label"] for o in controls.get("transactionFilter", []) if o["selected"]]
    conditions = {"transaction": condition(args.transaction, ("confirmed" if chosen and chosen[0].lower().startswith(args.transaction) else "not_applied") if chosen else "unverified", chosen[0] if chosen else None)}
    for name in ("owner", "sort", "value"):
        if getattr(args, name):
            conditions[name] = condition(getattr(args, name))
    if args.preset:
        active = [markup.text(a) for a in page.select("a.is-active[href*='or=']")]
        wanted = PRESETS[args.preset][1]
        conditions["preset"] = condition(args.preset, ("confirmed" if active == [wanted] else "not_applied") if active or page.select("a[href*='or=']") else "unverified", active[0] if active else None)
    obs.result["target"], obs.result["conditions"] = args.transaction, conditions
    obs.result["context"], obs.result["collections"] = {"sort_keys": markup.sort_keys(node)}, {"trades": rows}
    return obs.result
