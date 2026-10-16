// threads-snippet: navigate
// Send the dedicated tab (emptied earlier) back to a Threads screen, as typing its address would. The page load that
// follows is counted by the next look at the tab, as opening a tab is.
const url = String(args.url || '');
if (!/^https:\/\/www\.threads\.com\/(search)?$/.test(url)) return {refused: 'not a start screen', explicit: 0, resources: 0, statuses: [], signals: [], location: location.href};
setTimeout(() => location.assign(url), 0);
return {navigating: true, explicit: 0, resources: 0, statuses: [], signals: [], location: location.href};
