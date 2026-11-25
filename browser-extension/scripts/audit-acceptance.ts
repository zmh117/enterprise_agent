import { readFile, readdir, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { createHash } from 'node:crypto';
import { unzipSync, strFromU8 } from 'fflate';
import { validatePackage } from '../extension/export/package';

// 显式选择本次证据目录，避免将历史包自动重算为当前执行。
const [output, ...directories] = process.argv.slice(2);
if (!output || !directories.length) throw Error('用法: tsx scripts/audit-acceptance.ts output.json directory...');
const artifacts: object[] = []; const reports: any[] = [];
for (const directory of directories) {
  const files = await readdir(directory);
  const report = files.includes('acceptance.json') ? JSON.parse(await readFile(join(directory, 'acceptance.json'), 'utf8')) : null;
  if (report) reports.push({ directory, ...report });
  const build = await readFile(join(directory, 'test-extension/build-info.json'), 'utf8').then(JSON.parse).catch(async () => readFile(join(directory, 'external/source-manifest.json'), 'utf8').then(s => JSON.parse(s).build).catch(() => null));
  for (const name of files.filter(f => f.endsWith('.zip'))) {
    const zip = new Uint8Array(await readFile(join(directory, name)));
    const validation = await validatePackage(zip);
    const manifest = JSON.parse(strFromU8(unzipSync(zip)['manifest.json']!));
    artifacts.push({ path: join(directory, name), sha256: createHash('sha256').update(zip).digest('hex'), validation, build, browser: manifest.recording.browserVersion, policy: manifest.recording.policy, state: manifest.recording.state });
  }
}
const mentioned = [...new Set(reports.flatMap(r => r.checks.flatMap((c: any) => c.tIds ?? [])))].sort();
const assertions = reports.flatMap(r => r.checks);
await writeFile(resolve(output), JSON.stringify({ at: new Date().toISOString(), reports: reports.map(r => ({ directory: r.directory, build: r.build, browser: r.browser, system: r.system, permissionMode: r.permissionMode, counts: r.counts })), counts: { assertions: assertions.length, passedAssertions: assertions.filter(c => c.passed).length, mentionedTIds: mentioned.length, validatedZip: artifacts.length }, mentionedTIds: mentioned, note: '这些是断言数和涉及编号数，不代表完整 T 项通过数。状态及边界见 docs/acceptance.md。每个包绑定其实际采集构建，历史包不改写。', artifacts }, null, 2));
console.log(JSON.stringify({ assertions: assertions.length, mentionedTIds: mentioned.length, validatedZip: artifacts.length }));
