import http from 'node:http';
import { gzipSync } from 'node:zlib';

// Focused network regression fixture. Bodies are synthetic, not production data.
export async function startNetworkFixtures(port = 4517, deniedPort = 4518) {
  const requests = [];
  const large = JSON.stringify({ precision: '3.00', token: 'GZIP_PRIVATE_SENTINEL', password: 'GZIP_PASSWORD_SENTINEL', data: 'x'.repeat(1400 * 1024) });
  const compressed = gzipSync(large);
  const handler = (req, res) => {
    const url = new URL(req.url, `http://127.0.0.1:${port}`);
    requests.push({ path: url.pathname, method: req.method, host: req.headers.host });
    const headers = { 'access-control-allow-origin': '*', 'cache-control': 'no-store' };
    const json = value => { res.writeHead(200, { ...headers, 'content-type': 'application/json', 'x-hop': 'network' }); res.end(JSON.stringify(value)); };
    if (url.pathname === '/network-sw.js') {
      res.writeHead(200, { 'content-type': 'application/javascript', 'cache-control': 'no-store' });
      res.end(`addEventListener('install',e=>e.waitUntil(skipWaiting()));addEventListener('activate',e=>e.waitUntil(clients.claim()));addEventListener('fetch',e=>{const u=new URL(e.request.url);if(u.pathname==='/api/sw-json')e.respondWith(Promise.resolve(new Response(JSON.stringify({precision:'3.00',token:'SW_PRIVATE_SENTINEL'}),{headers:{'content-type':'application/json'}})));if(u.pathname==='/api/sw-redirect')e.respondWith(Promise.resolve(Response.redirect(u.origin+'/api/final',302)));});`); return;
    }
    if (url.pathname === '/api/gzip') { res.writeHead(200, { ...headers, 'content-type': 'application/json', 'content-encoding': 'gzip', 'content-length': compressed.length }); res.end(compressed); return; }
    if (url.pathname === '/api/post') {
      let body = ''; req.on('data', c => { body += c; }); req.on('end', () => {
        const parsed = JSON.parse(body); res.writeHead(200, { ...headers, 'content-type': 'text/plain;charset=UTF-8' }); res.end(JSON.stringify(parsed));
      }); return;
    }
    if (url.pathname.startsWith('/api/')) { json({ precision: '3.00', path: url.pathname }); return; }
    res.writeHead(200, { ...headers, 'content-type': 'text/html;charset=UTF-8' });
    if (url.pathname === '/frame') res.end('<!doctype html><title>新 frame</title><input name="precision" value="3.00"><script>fetch("/api/frame-first").then(r=>r.json()).then(()=>document.body.dataset.done="yes")</script>');
    else if (url.pathname === '/denied') res.end(`<!doctype html><title>未授权 frame</title><script>fetch('http://127.0.0.1:${port}/api/denied-post',{method:'POST',body:JSON.stringify({value:'DENIED_PRIVATE_SENTINEL'})}).then(()=>document.body.dataset.done='yes')</script>`);
    else res.end('<!doctype html><title>网络回归</title><input name="precision" value="3.00"><input name="ordinary" value="PLAIN_INPUT_SENTINEL"><input id="loginPassword" type="password" autocomplete="current-password" value="LOGIN_PASSWORD_SENTINEL"><p data-sensitive data-token="DOM_TOKEN_SENTINEL">token=PLAIN_TEXT_SENTINEL</p>');
  };
  const servers = [http.createServer(handler), http.createServer(handler)];
  await Promise.all(servers.map((s, i) => new Promise((resolve, reject) => { s.once('error', reject); s.listen(i ? deniedPort : port, '127.0.0.1', resolve); })));
  return { requests, decodedBytes: Buffer.byteLength(large), encodedBytes: compressed.length,
    close: async () => { for (const s of servers) s.closeAllConnections(); await Promise.all(servers.map(s => new Promise(resolve => s.close(resolve)))); } };
}
