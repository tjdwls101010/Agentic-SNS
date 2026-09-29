// twitter-snippet: graphql
await (async () => {
  if (!/^[A-Za-z0-9_]+$/.test(ARGS.op) || !/^[A-Za-z0-9_-]+$/.test(ARGS.query_id) || !['GET','POST'].includes(ARGS.method)) throw Error('Invalid operation');
  const headers = {
    authorization: 'Bearer '+ARGS.bearer, 'x-csrf-token': ARGS.ct0,
    'x-twitter-auth-type': 'OAuth2Session', 'x-twitter-active-user': 'yes',
    'content-type': 'application/json', origin: 'https://x.com', referer: 'https://x.com/',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
  };
  if (ARGS.txid) headers['x-client-transaction-id'] = ARGS.txid;
  let url = 'https://x.com/i/api/graphql/'+ARGS.query_id+'/'+ARGS.op;
  const data = {variables: ARGS.variables, features: ARGS.features};
  if (ARGS.field_toggles) data.fieldToggles = ARGS.field_toggles;
  const options = {method: ARGS.method, headers, redirect: 'manual'};
  if (ARGS.method === 'POST') options.body = JSON.stringify({...data, queryId: ARGS.query_id});
  else url += '?' + Object.entries(data).map(([k,v])=>encodeURIComponent(k)+'='+encodeURIComponent(JSON.stringify(v))).join('&');
  const response = await fetch(url, options);
  const received = await response.text();
  const envelope = {status:response.status, url:response.url, body:received,
    ratelimit:Object.fromEntries(['limit','remaining','reset'].map(k=>[k,response.headers.get('x-rate-limit-'+k)]))};
  if (received.length > 1000000 && Buffer.byteLength(JSON.stringify(envelope)) > 8*1024*1024) {
    let index=0;
    for(let offset=0;offset<received.length;) {
      let end=Math.min(offset+512*1024,received.length);
      const last=received.charCodeAt(end-1);
      if(end<received.length && last>=0xD800 && last<=0xDBFF) end--;
      console.log(JSON.stringify({kind:'body_chunk',index:index++,body:received.slice(offset,end)})); offset=end;
    }
    envelope.body=''; envelope.body_chunks=index;
  }
  console.log(JSON.stringify(envelope));
})();
