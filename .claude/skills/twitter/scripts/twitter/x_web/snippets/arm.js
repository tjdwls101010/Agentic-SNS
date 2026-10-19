// twitter-snippet: arm
// Run again and again while the tab loads x.com (the load call): returns null until the new document exists, then
// installs the kit at once, before the app has run, so the observer sees the whole load. Makes no request.
if (location.href === 'about:blank' || !document.documentElement) return null;
const kit = KIT(args);
return {installed_at: Math.round(kit.installedAt), ready_at_install: kit.readyAtInstall, app_at_install: kit.appAtInstall,
        buffer_intact: kit.bufferIntact, location: location.href};
