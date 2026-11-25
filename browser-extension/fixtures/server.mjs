import http from 'node:http';
import { createHash, randomUUID } from 'node:crypto';
import { readFile, appendFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export async function startFixtures({ port = 4317, crossPort = 4318, logFile = 'output/playwright/fixture-backend.ndjson' } = {}) {
  const html = await readFile(new URL('./mes.html', import.meta.url), 'utf8');
  await mkdir(path.dirname(logFile), { recursive: true });
  const timers = new Set(); const sockets = new Set();
  const fixtureRunId = randomUUID();
  const log = data => appendFile(logFile, JSON.stringify({ at: new Date().toISOString(), backendBuildId: 'fixture-backend-1', ...data }) + '\n');
  let requestSeq = 0;
  function handler(req, res) {
    const u = new URL(req.url, `http://127.0.0.1:${port}`);
    const requestId = `fixture-${fixtureRunId}-${++requestSeq}`;
    const headers = { 'x-request-id': requestId, 'x-backend-build': 'fixture-backend-1', 'x-frontend-build': 'fixture-frontend-1', 'x-service-instance': 'fixture-local', 'access-control-allow-origin': '*', 'cache-control': 'no-store' };
    const json = (data, status = 200, extra = {}) => { res.writeHead(status, { ...headers, 'content-type': 'application/json; charset=utf-8', ...extra }); res.end(JSON.stringify(data)); };
    if (u.pathname === '/api/first') { void log({ requestId, path: u.pathname, marker: u.searchParams.get('id') }); json({ code: 'OK', marker: u.searchParams.get('id') }); return; }
    if (u.pathname === '/api/echo') {
      let body = ''; req.on('data', c => { body += c; });
      req.on('end', () => { void log({ requestId, path: u.pathname, marker: u.searchParams.get('id'), header: req.headers['x-case'] }); json({ code: 'OK', marker: u.searchParams.get('id'), header: req.headers['x-case'] ?? null, body: body || null }, 200, { 'x-case': req.headers['x-case'] ?? '' }); }); return;
    }
    if (u.pathname === '/api/hops') {
      const hop = Number(u.searchParams.get('page') || 0); const marker = u.searchParams.get('id');
      void log({ requestId, path: u.pathname, marker, hop, header: req.headers['x-case'] });
      if (hop < 2) { res.writeHead(307, { ...headers, location: `/api/hops?id=${encodeURIComponent(marker)}&page=${hop + 1}`, 'x-hop': String(hop), 'x-case': marker }); res.end(); }
      else json({ code: 'OK', marker, hop }, 200, { 'x-hop': String(hop), 'x-case': marker }); return;
    }
    if (u.pathname === '/bfcache') {
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'max-age=60' });
      res.end('<!doctype html><title>BFCache fixture</title><input name="precision" value="1"><a href="/bfcache?id=away">下一页</a><script>window.life=[];addEventListener("pageshow",e=>life.push({type:"pageshow",persisted:e.persisted,at:performance.now()}));addEventListener("pagehide",e=>life.push({type:"pagehide",persisted:e.persisted,at:performance.now()}));</script>'); return;
    }
    if (u.pathname === '/shared-worker.js') { res.writeHead(200, { ...headers, 'content-type': 'application/javascript' }); res.end(`const clients=[];onconnect=e=>{const p=e.ports[0];clients.push(p);p.onmessage=async e=>{await fetch('/api/echo?id=SHARED_INTERNAL_'+e.data).then(r=>r.text());p.postMessage({done:e.data,clients:clients.length});};p.start();}`); return; }
    if (u.pathname === '/marked-worker.js') { res.writeHead(200, { ...headers, 'content-type': 'application/javascript' }); res.end(`onmessage=async e=>{await fetch('/api/echo?id=DEDICATED_'+e.data).then(r=>r.text());postMessage(e.data);}`); return; }
    if (u.pathname === '/api/save') {
      let data = ''; req.on('data', c => { data += c; if (data.length > 2 * 1024 * 1024) req.destroy(); });
      req.on('end', () => {
        let body; try { body = JSON.parse(data); } catch { json({ code: 'INVALID_JSON' }, 400); return; }
        const conflict = Number(body.version) !== 2;
        void log({ requestId, path: u.pathname, recipeId: body.recipeId, receivedVersion: body.version, storedVersion: 2, branch: conflict ? 'VERSION_CONFLICT' : 'SAVED' });
        json({ code: conflict ? 'VERSION_CONFLICT' : 'OK', message: conflict ? '配方版本已变化，请检查现场配置' : '已保存', recipeId: body.recipeId, receivedVersion: body.version, currentVersion: 2, precision: body.precision });
      }); return;
    }
    if (u.pathname === '/api/slow') {
      void log({ requestId, path: u.pathname, phase: 'accepted' });
      const timer = setTimeout(() => { timers.delete(timer); void log({ requestId, path: u.pathname, phase: 'server_completed_even_if_browser_closed' }); json({ code: 'OK', latePayload: 'SHOULD_NOT_APPEAR_AFTER_CUTOFF' }); }, 1800); timers.add(timer); return;
    }
    if (u.pathname === '/api/correlation') { json({ code: 'OK', metadata: { build: u.searchParams.get('version') ?? 'v1', requestId } }, 200, { 'x-deploy': u.searchParams.get('version') ?? 'v1', 'x-log-id': requestId }); return; }
    if (u.pathname === '/api/error') { json({ code: 'SERVER_FAILURE', message: '模拟数据库连接失败' }, 500); return; }
    if (u.pathname === '/api/network-fail') { req.socket.destroy(); return; }
    if (u.pathname === '/api/empty') { res.writeHead(204, headers); res.end(); return; }
    if (u.pathname === '/api/token') { json({ code: 'OK', token: 'RESPONSE_SECRET_829', nested: { password: 'NESTED_SECRET_283' }, precision: '3.00' }, 200, { 'set-cookie': 'sessionid=COOKIE_SECRET_431; HttpOnly', 'x-demo': 'token=HEADER_SECRET_773' }); return; }
    if (u.pathname === '/api/large') { json({ code: 'OK', data: 'x'.repeat(1100 * 1024), token: 'LARGE_SECRET_102' }); return; }
    if (u.pathname === '/api/redirect') { res.writeHead(302, { ...headers, location: '/api/redirect-final', 'x-hop': 'first' }); res.end(); return; }
    if (u.pathname === '/api/redirect-final') { json({ code: 'OK', hop: 'final' }, 200, { 'x-hop': 'final' }); return; }
    if (u.pathname === '/api/events') {
      res.writeHead(200, { ...headers, 'content-type': 'text/event-stream', connection: 'keep-alive' });
      res.write('event: mes\nid: one\ndata: {"code":"OK","quantity":7,"token":"SSE_SECRET_618"}\n\n');
      const timer = setInterval(() => res.write('data: {"code":"OK","quantity":8}\n\n'), 300);
      timers.add(timer); req.on('close', () => { clearInterval(timer); timers.delete(timer); }); return;
    }
    if (u.pathname === '/worker.js') { res.writeHead(200, { ...headers, 'content-type': 'application/javascript' }); res.end(`onmessage=()=>{fetch('/api/token').then(r=>r.json()).then(x=>postMessage({code:x.code}));console.warn('dedicated worker diagnostic')}`); return; }
    if (u.pathname === '/favicon.ico') { res.writeHead(204); res.end(); return; }
    if (u.pathname === '/frame') {
      res.writeHead(200, { ...headers, 'content-type': 'text/html; charset=utf-8' });
      res.end(`<!doctype html><meta charset="utf-8"><h3>${u.searchParams.get('id') === 'cross' ? '跨源' : '同源'} iframe</h3><label>精度<input name="precision" value="2"></label><button id="frame-program">程序赋值</button><script>document.querySelector('button').onclick=()=>{document.querySelector('input').value='7';fetch('/api/token').then(r=>r.json())};</script>`); return;
    }
    res.writeHead(200, { ...headers, 'content-type': 'text/html; charset=utf-8' }); res.end(html.replaceAll('__CROSS_PORT__', String(crossPort)));
  }
  const servers = [http.createServer(handler), http.createServer(handler)];
  for (const server of servers) {
    server.on('connection', socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)); socket.on('error', () => socket.destroy()); });
    server.on('upgrade', (req, socket) => {
      if (req.url !== '/api/socket' || !req.headers['sec-websocket-key']) { socket.destroy(); return; }
      const accept = createHash('sha1').update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
      socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
      const body = Buffer.from('{"code":"OK","quantity":9,"token":"WS_SECRET_829"}');
      socket.write(Buffer.concat([Buffer.from([0x81, body.length]), body]));
      socket.on('data', data => { if ((data[0] & 0x0f) === 8) socket.end(Buffer.from([0x88, 0])); });
    });
  }
  await Promise.all(servers.map((server, i) => new Promise((resolve, reject) => { server.once('error', reject); server.listen(i ? crossPort : port, '127.0.0.1', resolve); })));
  return { servers, close: async () => { for (const timer of timers) { clearTimeout(timer); clearInterval(timer); } for (const socket of sockets) socket.destroy(); await Promise.all(servers.map(s => new Promise(resolve => s.close(resolve)))); } };
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const fixture = await startFixtures(); console.log('模拟 MES: http://127.0.0.1:4317；跨源 iframe: http://localhost:4318');
  process.on('SIGINT', () => void fixture.close().then(() => process.exit()));
  process.on('SIGTERM', () => void fixture.close().then(() => process.exit()));
}
