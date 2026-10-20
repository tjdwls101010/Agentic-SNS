// sns-snippet: aside.media
// One picture fetched by the browser without cookies (a post's picture or a video's poster on the platform's image
// host): {status, type, size, data (base64)}, or too_large without the bytes when it passes args.max — checked on the
// declared length first and on what arrived after, so a lying header cannot carry more. A redirect is not followed (it
// would fetch an address the host check never saw) and an unreachable host is answered, not thrown: both are this
// picture's failure, not the command's.
async (args) => {
  let response;
  try {
    response = await fetch(args.url, {credentials: 'omit', redirect: 'manual'});
  } catch (error) {
    return {status: 0, network: String(error && error.message ? error.name + ': ' + error.message : error).slice(0, 200)};
  }
  if (response.type === 'opaqueredirect' || (response.status >= 300 && response.status < 400)) {
    return {status: response.status, redirect: true};
  }
  const type = (response.headers.get('content-type') || '').split(';')[0].trim();
  const declared = Number(response.headers.get('content-length') || 0);
  if (declared > args.max) return {status: response.status, type, size: declared, data: null, too_large: true};
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.length > args.max) return {status: response.status, type, size: bytes.length, data: null, too_large: true};
  let data;
  if (typeof Buffer !== 'undefined') {
    data = Buffer.from(bytes).toString('base64');
  } else {
    let binary = '';
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    data = btoa(binary);
  }
  return {status: response.status, type, size: bytes.length, data};
}
