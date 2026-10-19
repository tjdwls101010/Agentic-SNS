// twitter-snippet: close
// Report what the tab saw, then close it (it was opened without history, so the page may close itself). Makes no
// request; if the tab stays open the skill empties it instead.
const report = await kit.report(0);
setTimeout(() => window.close(), 0);
return {closing: true, ...report};
