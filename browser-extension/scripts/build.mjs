import { createHash } from 'node:crypto';
import { build } from 'esbuild';
import './generate-schema.mjs';
import { mkdir, copyFile, rm, writeFile, readFile } from 'node:fs/promises';
await rm('dist', { recursive: true, force: true });
await mkdir('dist', { recursive: true });
const agentPanel = await readFile('extension/ui/agent-panel.html', 'utf8');
const buildPage = async (name) => {
  const template = await readFile('extension/ui/' + name + '.html', 'utf8');
  await writeFile('dist/' + name + '.html', template.replace('<!-- agent-panel -->', () => agentPanel));
};
await Promise.all([
  buildPage('control'), buildPage('floating'),
  build({ entryPoints: ['extension/ui/floating.tsx'], outfile: 'dist/floating.js', bundle: true, format: 'esm', target: 'chrome125', minify: true, define: { 'process.env.NODE_ENV': '"production"' } }),
  build({ entryPoints: ['extension/content/float.ts'], outfile: 'dist/float-host.js', bundle: true, format: 'iife', target: 'chrome125' }),
  build({ entryPoints: ['extension/background/index.ts'], outfile: 'dist/background.js', bundle: true, format: 'esm', target: 'chrome125', sourcemap: true }),
  build({ entryPoints: ['extension/content/live-recorder.ts'], outfile: 'dist/live-recorder.js', bundle: true, format: 'iife', target: 'chrome125' }),
  build({ entryPoints: ['extension/content/bootstrap.ts'], outfile: 'dist/bootstrap.js', bundle: true, format: 'iife', target: 'chrome125' }),
  build({ entryPoints: ['extension/page/recorder.ts'], outfile: 'dist/recorder.js', bundle: true, format: 'iife', target: 'chrome125' }),
  build({ entryPoints: ['extension/ui/control.ts'], outfile: 'dist/control.js', bundle: true, format: 'esm', target: 'chrome125', sourcemap: true }),
  ...[['extension/manifest.json', 'manifest.json'], ['extension/ui/floating.css', 'floating-page.css'], ['extension/ui/control.css', 'control.css'], ['extension/ui/chat.css', 'chat.css']].map(([src, name]) => copyFile(src, `dist/${name}`))
]);
const lock = JSON.parse(await readFile('package-lock.json', 'utf8'));
const manifest = JSON.parse(await readFile('extension/manifest.json', 'utf8'));
const schema = JSON.parse(await readFile('shared/problem-package.schema.json', 'utf8'));
await writeFile('dist/build-info.json', JSON.stringify({ builtAt: new Date().toISOString(), buildHash: createHash('sha256').update(await readFile('dist/background.js')).update(await readFile('dist/recorder.js')).update(await readFile('dist/live-recorder.js')).update(await readFile('dist/control.js')).update(await readFile('dist/float-host.js')).update(await readFile('dist/floating.js')).update(await readFile('dist/floating-page.css')).update(await readFile('dist/control.html')).update(await readFile('dist/control.css')).update(await readFile('dist/chat.css')).digest('hex'), extensionVersion: manifest.version, schemaVersion: schema.properties.schemaVersion.enum.at(-1), rrwebVersion: lock.packages['node_modules/@rrweb/record'].version, minimumChrome: 125 }, null, 2));
console.log('Built unpacked extension: dist/');
