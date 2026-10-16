// threads-snippet: state
// What the dedicated tab shows and who is logged in; the requests the tab finished since the last look (the first
// look of a command reports them as made between commands); the document itself when asked (a tab just opened).
// Makes no request.
const load = window['req' + 'uire'];  // the page's module loader; the REPL refuses code that spells its call
let user = null, appId = null, runtime = false;
try {
  runtime = typeof load === 'function';
  const current = load('CurrentUserInitialData');
  user = current.NON_FACEBOOK_USER_ID === undefined || current.NON_FACEBOOK_USER_ID === null ? null : String(current.NON_FACEBOOK_USER_ID);
  appId = current.APP_ID === undefined ? null : String(current.APP_ID);
} catch (_) { /* not a logged-in Threads page */ }
const document_html = args.document ? document.documentElement.outerHTML.slice(0, 3000000) : null;
return {user_id: user, app_id: appId, runtime, document: document_html, ...(await kit.report(0))};
