import { readFile } from 'node:fs/promises';
import { validatePackage } from '../extension/export/package';
const path = process.argv[2];
if (!path) { console.error('用法: npm run validate:package -- /path/to/browser-capture-xxx.zip'); process.exit(1); }
try { console.log(JSON.stringify(await validatePackage(new Uint8Array(await readFile(path))), null, 2)); }
catch (e) { console.error(String(e)); process.exitCode = 1; }
