import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { build } from 'esbuild';

const read = path => readFile(path, 'utf8');
const playerDist = 'node_modules/rrweb-player/dist';
const bundle = await build({ entryPoints: ['replay/main.js'], bundle: true, write: false, target: 'chrome125', format: 'iife' });
const scripts = [
  await read(playerDist + '/rrweb-player.umd.min.cjs'),
  bundle.outputFiles[0].text,
].map(source => source.replace(/\n\/\/# sourceMappingURL=[^\n]*\s*$/, '').replace(/<\/script/gi, '<\\/script').replace(/\r\n?/g, '\n'));
const hashes = scripts.map(script => "'sha256-" + createHash('sha256').update(script).digest('base64') + "'");
const policy = "default-src 'none'; script-src " + hashes.join(' ') + "; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; frame-src about:; connect-src 'none'; base-uri 'none'; form-action 'none'; object-src 'none'";
const licenses = await Promise.all(['replay/rrweb.LICENSE', 'node_modules/fflate/LICENSE'].map(read));
const parts = {
  POLICY: policy,
  PLAYER_CSS: (await read(playerDist + '/style.min.css')).replace(/\/\*# sourceMappingURL=.*?\*\//g, ''),
  SCRIPTS: scripts.map(script => '<script>' + script + '</script>').join('\n'),
  LICENSES: licenses.join('\n').replaceAll('&', '&amp;').replaceAll('<', '&lt;'),
};
const html = (await read('replay/index.html')).replace(/{{(\w+)}}/g, (_, key) => parts[key]);
await mkdir('release', { recursive: true });
await writeFile('release/MES-rrweb-replay.html', html);
