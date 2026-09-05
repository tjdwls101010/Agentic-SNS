// twitter-snippet: cookie
await (async () => {
  let page;
  try {
    page=await openTab('https://x.com/robots.txt');
    const body=await page.evaluate(()=>Object.fromEntries(document.cookie.split(';').map(x=>x.trim().split(/=(.*)/s)).filter(x=>['ct0','twid'].includes(x[0])).map(([k,v])=>[k,v])));
    console.log(JSON.stringify({status:200,url:'https://x.com/robots.txt',body:JSON.stringify(body)}));
  } finally {if(page) await closeTab(page);}
})();
