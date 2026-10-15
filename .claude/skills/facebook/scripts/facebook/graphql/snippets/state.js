async (args) => {
  // facebook-snippet: state
  // What the dedicated tab is showing and who is logged in. Makes no request.
  const host = /^https:\/\/([a-z0-9-]+\.)*facebook\.com\//;
  const resources = performance.getEntriesByType('resource').filter(entry => host.test(entry.name)).length;
  let user = null;
  let runtime = false;
  try {
    runtime = typeof window.require === 'function';
    const value = window.require('CurrentUserInitialData').USER_ID;
    user = value === undefined || value === null ? null : String(value);
  } catch (_) { /* not a logged-in Facebook page */ }
  return {location: location.href, user_id: user, runtime, resources};
}
