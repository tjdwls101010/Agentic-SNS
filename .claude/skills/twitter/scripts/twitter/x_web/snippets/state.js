// twitter-snippet: state
// What the dedicated tab shows and who is logged in (the redux store's session), whether the app's parts the skill
// needs are there, and the requests the tab finished since the last look (the first look of a command reports them as
// made between commands). Makes no request.
const session = kit.session();
const runtime = kit.runtime();
const ct0 = /(?:^|;\s*)ct0=/.test(document.cookie);
return {user_id: session.user_id, language: session.language, app: !!runtime, store: !!kit.store(),
        switches: session.switches ? Object.keys(session.switches).length : 0, ct0,
        installed_at: Math.round(kit.installedAt), ready_at_install: kit.readyAtInstall, app_at_install: kit.appAtInstall,
        ...(await kit.report(0))};
