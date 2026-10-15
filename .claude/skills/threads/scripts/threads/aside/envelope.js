// Shared by every snippet Aside runs: print one response envelope as the final line.
// Keep each log line below the measured 12 MiB ceiling without writing personal data to disk: a large body is sent
// first as ordered chunk lines, and the envelope then carries body_chunks instead of the body.
const emitEnvelope = envelope => {
  const received = envelope.body;
  if (received.length > 1000000 && Buffer.byteLength(JSON.stringify(envelope)) > 8 * 1024 * 1024) {
    let index = 0;
    for (let offset = 0; offset < received.length;) {
      let end = Math.min(offset + 512 * 1024, received.length);
      const last = received.charCodeAt(end - 1);
      if (end < received.length && last >= 0xD800 && last <= 0xDBFF) end--;
      console.log(JSON.stringify({kind: 'body_chunk', index: index++, body: received.slice(offset, end)}));
      offset = end;
    }
    envelope = {...envelope, body: '', body_chunks: index};
  }
  console.log(JSON.stringify(envelope));
};
