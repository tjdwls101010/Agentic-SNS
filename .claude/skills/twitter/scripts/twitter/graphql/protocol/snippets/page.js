// twitter-snippet: page
await (async () => {
  if (!/^https:\/\/(?:x\.com|abs\.twimg\.com)\/(?!\/)[^\s\\]*$/.test(ARGS.url)) throw Error('URL is outside the allowed hosts');
  const response=await fetch(ARGS.url,{method:'GET',redirect:'manual',headers:{
    accept:'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'user-agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
  }});
  console.log(JSON.stringify({status:response.status,url:response.url,body:await response.text()}));
})();
