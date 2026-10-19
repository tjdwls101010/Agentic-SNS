// twitter-snippet: blank
// Report what the tab saw, then empty it (about:blank) so the app's background polling stops. Makes no request.
const report = await kit.report(0);
setTimeout(() => location.replace('about:blank'), 0);
return {blanked: true, ...report};
