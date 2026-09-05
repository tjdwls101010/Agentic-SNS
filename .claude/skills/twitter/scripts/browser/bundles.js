// twitter-snippet: bundles
await (async () => {
  const base='https://abs.twimg.com/responsive-web/client-web/';
  const url=ARGS.html_url || 'https://x.com/';
  if(url!=='https://x.com/') throw Error('Invalid HTML URL');
  const headers={accept:'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8','user-agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'};
  async function get(url) {
    if(!/^https:\/\/(?:x\.com|abs\.twimg\.com)\/(?!\/)[^\s\\]*$/.test(url)) throw Error('Invalid bundle URL');
    const r=await fetch(url,{method:'GET',redirect:'manual',headers});
    const body=await r.text();
    if(r.status!==200) {const e=new Error('Bundle fetch failed'); e.status=r.status;e.body=body;throw e;}
    return body;
  }
  let html;
  try {html=await get(url);} catch(e) {
    console.log(JSON.stringify({status:e.status||502,url,body:e.body||'HTML fetch failed'})); return;
  }
  function braces(text,start) {
    const begin=text.indexOf('{',start); if(begin<0) throw Error('Missing chunk map');
    let depth=0,quote=null,escape=false;
    for(let i=begin;i<text.length;i++) {
      const c=text[i];
      if(quote) {if(escape) escape=false; else if(c==='\\') escape=true; else if(c===quote) quote=null;continue;}
      if(c==='"'||c==="'") {quote=c;continue;}
      if(c==='{') depth++;
      if(c==='}' && --depth===0) return [text.slice(begin,i+1),i+1];
    }
    throw Error('Unbalanced chunk map');
  }
  const pairs=text=>Object.fromEntries([...text.matchAll(/(\d+):"([^"]+)"/g)].map(m=>[m[1],m[2]]));
  const operations={},features={},failures=[];
  function mine(text) {
    for(const m of text.matchAll(/queryId:"([A-Za-z0-9_-]+)",operationName:"(\w+)",operationType:"query"/g)) operations[m[2]]=m[1];
  }
  for(const m of html.matchAll(/"([\w_]+)":\{"value":(true|false)/g)) features[m[1]]=m[2]==='true';
  const main=html.match(/https:\/\/abs\.twimg\.com\/responsive-web\/client-web\/[\w./-]*main\.[\w-]+\.js/);
  let urls=[],ondemand_url=null,ondemand_js=null;
  const marker=html.indexOf('.u=e=>');
  if(marker>=0) {
    try {
      const [namesLiteral,after]=braces(html,marker),[hashesLiteral]=braces(html,after);
      const names=pairs(namesLiteral),hashes=pairs(hashesLiteral);
      const safeName=name=>/^[\w.~/-]+$/.test(name)&&name.split('/').every(part=>part&&part!=='.'&&part!=='..');
      urls=Object.entries(hashes).filter(([id,hash])=>/^[a-f0-9]+$/.test(hash)&&safeName(names[id]||id)).map(([id,hash])=>base+(names[id]||id)+'.'+hash+'a.js');
      const id=Object.keys(names).find(k=>names[k]==='ondemand.s');
      if(id&&hashes[id]) ondemand_url=base+'ondemand.s.'+hashes[id]+'a.js';
    } catch(e) {failures.push('chunk maps');}
  }
  if(main) urls.unshift(main[0]);
  let next=0;
  // Static CDN chunks are not API calls; one bounded sweep uses at most sixteen fetches concurrently.
  await Promise.all(Array.from({length:16},async()=>{
    while(next<urls.length) {
      const current=urls[next++];
      try {const text=await get(current);mine(text);if(current===ondemand_url) ondemand_js=text;}
      catch(e) {failures.push(current);}
    }
  }));
  console.log(JSON.stringify({status:200,url,body:JSON.stringify({operations,features,failures,txid_ingredients:{html,ondemand_url,ondemand_js}})}));
})();
