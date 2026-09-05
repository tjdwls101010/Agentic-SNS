const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
const source = name => fs.readFileSync(path.resolve(__dirname, '../../../.claude/skills/twitter/scripts/browser', name+'.js'),'utf8');
for (const method of ['GET','POST']) test(method+' contract', async()=>{
  let call; const logs=[];
  await new AsyncFunction('ARGS','fetch','console',source('graphql'))({op:'HomeTimeline',query_id:'abc',method,variables:{count:3,rawQuery:'a & b'},features:{flag:true},ct0:'csrf',bearer:'public',txid:'fresh'},async(url,options)=>{call={url,options};return {status:200,url,text:async()=>'{"data":{}}',headers:{get:()=> '50'}}},{log:x=>logs.push(JSON.parse(x))});
  assert.equal(call.options.redirect,'manual'); assert.equal(call.options.headers['x-csrf-token'],'csrf');
  assert.equal(call.options.headers['x-client-transaction-id'],'fresh');
  assert.equal(call.options.headers.authorization,'Bearer public');
  assert.equal(call.options.headers['x-twitter-auth-type'],'OAuth2Session');
  assert.equal(call.options.headers['x-twitter-active-user'],'yes');
  assert.equal(call.options.headers['content-type'],'application/json');
  assert.equal(call.options.headers.origin,'https://x.com');
  assert.equal(call.options.headers.referer,'https://x.com/');
  assert.match(call.options.headers['user-agent'],/^Mozilla/);
  if(method==='GET') assert.deepEqual(JSON.parse(new URL(call.url).searchParams.get('variables')),{count:3,rawQuery:'a & b'});
  else assert.deepEqual(JSON.parse(call.options.body),{variables:{count:3,rawQuery:'a & b'},features:{flag:true},queryId:'abc'});
  if(method==='GET') assert.deepEqual(JSON.parse(new URL(call.url).searchParams.get('features')),{flag:true});
  assert.equal(logs[0].ratelimit.remaining,'50');
});
test('page refuses arbitrary hosts before fetch',async()=>{
  for(const url of ['https://evil.com/','https://x.com@evil.com/','http://x.com/','https://x.com.evil/'])
    await assert.rejects(new AsyncFunction('ARGS','fetch',source('page'))({url},()=>{throw Error('fetch must not run')}),/URL/);
});
test('cookie closes tab when evaluation fails',async()=>{
  let closed=false; const tab={evaluate:async()=>{throw Error('failed')}};
  await assert.rejects(new AsyncFunction('ARGS','openTab','closeTab',source('cookie'))({},async()=>tab,async p=>{assert.equal(p,tab);closed=true}));
  assert.equal(closed,true);
});

test('ungated requests omit an unavailable signature',async()=>{
  let headers;
  await new AsyncFunction('ARGS','fetch','console',source('graphql'))(
    {op:'Viewer',query_id:'abc',method:'GET',variables:{},features:{},ct0:'synthetic',bearer:'public'},
    async(url,options)=>{headers=options.headers;return {status:200,url,text:async()=>'{}',headers:{get:()=>null}}},
    {log:()=>{}});
  assert.equal(Object.hasOwn(headers,'x-client-transaction-id'),false);
});
