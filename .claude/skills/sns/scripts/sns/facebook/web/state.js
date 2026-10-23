// sns-snippet: facebook.state
// What the dedicated tab is showing, who is logged in, and the tab's facebook.com requests since the last look (all of
// them since the page loaded when args.fresh: the tab was just opened). Makes no request.
return {location: location.href, user_id: kit.user(), runtime: typeof kit.load === 'function', ...(await kit.settle(0))};
