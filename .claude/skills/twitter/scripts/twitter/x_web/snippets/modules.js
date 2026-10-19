// twitter-snippet: modules
// Which of the skill's operations the tab's app defines right now (and as what), loading the lazily loaded chunks
// the skill names by hint first. Makes no x.com request (chunks come from the static CDN).
for (const hint of args.hints || []) await kit.loadChunks(String(hint));
const index = kit.index();
const live = {};
for (const name of args.names || []) {
  const def = index && index.ops[name];
  live[name] = def ? {query_id: def.queryId, type: def.type, features: def.featureSwitches.length} : null;
}
return {live, modules: index ? index.modules : 0, generator: !!kit.generator(), bearer: !!kit.bearer(), ...(await kit.report(0))};
