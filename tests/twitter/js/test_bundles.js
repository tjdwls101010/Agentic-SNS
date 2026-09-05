const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
const source=()=>fs.readFileSync(path.resolve(__dirname,'../../../.claude/skills/twitter/scripts/browser/bundles.js'),'utf8');
test('mines only queries from both maps, including unnamed chunks and switches',async()=>{
  const html='<script src="https://abs.twimg.com/responsive-web/client-web/main.abc.js"></script> .u=e=>""+({12:"ondemand.s",13:"bundle.List"})[e]+"."+({12:"aa",13:"bb",14:"cc"})[e]+"a.js"; "flag":{"value":true}';
  const urls=[],logs=[];
  await new AsyncFunction('ARGS','fetch','console',source())({},async url=>{urls.push(url);return {status:200,url,text:async()=>url==='https://x.com/'?html:url.includes('main.')?'queryId:"id1",operationName:"Viewer",operationType:"query";queryId:"bad",operationName:"CreateTweet",operationType:"mutation"':url.includes('List')?'queryId:"id2",operationName:"ListMembers",operationType:"query"':'indices'}},{log:x=>logs.push(JSON.parse(x))});
  const result=JSON.parse(logs[0].body);
  assert.deepEqual(result.operations,{Viewer:'id1',ListMembers:'id2'});
  assert.equal(result.features.flag,true);
  assert.ok(urls.includes('https://abs.twimg.com/responsive-web/client-web/14.cca.js'));
  assert.equal(result.txid_ingredients.ondemand_js,'indices');
});
test('shared and locale chunks are mined without allowing path traversal',async()=>{
  const html='.u=e=>({1:"shared~bundle.Communities~bundle.UserLists",2:"i18n/en",3:"../escape",4:"bundle/../escape"})[e]+({1:"aa",2:"bb",3:"cc",4:"dd"})[e]';
  const urls=[],logs=[];
  await new AsyncFunction('ARGS','fetch','console',source())({},async url=>{
    urls.push(url);
    return {status:200,url,text:async()=>url==='https://x.com/'?html:'queryId:"community-id",operationName:"CommunityByRestId",operationType:"query"'};
  },{log:x=>logs.push(JSON.parse(x))});
  assert.equal(JSON.parse(logs[0].body).operations.CommunityByRestId,'community-id');
  assert.ok(urls.includes('https://abs.twimg.com/responsive-web/client-web/shared~bundle.Communities~bundle.UserLists.aaa.js'));
  assert.ok(urls.includes('https://abs.twimg.com/responsive-web/client-web/i18n/en.bba.js'));
  assert.ok(!urls.some(url=>url.includes('escape')));
});
