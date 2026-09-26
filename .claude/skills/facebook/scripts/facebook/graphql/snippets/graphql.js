// facebook-snippet: graphql
await (async () => {
  const t = ARGS.tokens;
  const form = {
    av: t.user_id, __user: t.user_id, __a: '1', __comet_req: '15',
    fb_dtsg: t.fb_dtsg, jazoest: t.jazoest, lsd: t.lsd,
    __spin_r: t.__spin_r, __rev: t.__rev, server_timestamps: 'true',
    fb_api_caller_class: 'RelayModern', fb_api_req_friendly_name: ARGS.name,
    variables: JSON.stringify(ARGS.variables), doc_id: ARGS.doc_id
  };
  const body = Object.entries(form).map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&');
  const response = await fetch('https://www.facebook.com/api/graphql/', {
    method: 'POST', credentials: 'include', body,
    headers: {
      'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
      'accept': '*/*', 'sec-fetch-site': 'same-origin', 'sec-fetch-mode': 'cors', 'sec-fetch-dest': 'empty',
      'origin': 'https://www.facebook.com', 'referer': ARGS.referer,
      'x-fb-friendly-name': ARGS.name, 'x-fb-lsd': t.lsd,
      'content-type': 'application/x-www-form-urlencoded'
    }
  });
  const received = await response.text();
  const envelope = {status: response.status, url: response.url, body: received};
  // Keep each log line below the measured 12 MiB ceiling without writing personal data to disk.
  if (received.length > 1000000 && Buffer.byteLength(JSON.stringify(envelope)) > 8 * 1024 * 1024) {
    let index = 0;
    for (let offset = 0; offset < received.length;) {
      let end = Math.min(offset + 512 * 1024, received.length);
      const last = received.charCodeAt(end - 1);
      if (end < received.length && last >= 0xD800 && last <= 0xDBFF) end--;
      console.log(JSON.stringify({kind: 'body_chunk', index: index++, body: received.slice(offset, end)}));
      offset = end;
    }
    envelope.body = '';
    envelope.body_chunks = index;
  }
  console.log(JSON.stringify(envelope));
})();
