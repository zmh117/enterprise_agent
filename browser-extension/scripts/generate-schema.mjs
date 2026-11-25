import Ajv from 'ajv/dist/2020.js';
import standalone from 'ajv/dist/standalone/index.js';
import { build } from 'esbuild';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';

const schema = JSON.parse(await readFile('shared/problem-package.schema.json', 'utf8'));
const ajv = new Ajv({ code: { source: true }, strict: false, allErrors: false });
ajv.addSchema(schema);
const names = Object.keys(schema.$defs);
const exports = { manifest: schema.$id, ...Object.fromEntries(names.map(n => [n, `${schema.$id}#/$defs/${n}`])) };
const result = await build({ stdin: { contents: standalone(ajv, exports), resolveDir: process.cwd() }, bundle: true, format: 'esm', platform: 'browser', target: 'chrome125', write: false });
await mkdir('shared/generated', { recursive: true });
const path = resolve('shared/generated/schema.js');
const code = '// 由 npm run schema:generate 生成，请修改 problem-package.schema.json。\n' + result.outputFiles[0].text;
if (await readFile(path, 'utf8').catch(() => '') !== code) await writeFile(path, code);
