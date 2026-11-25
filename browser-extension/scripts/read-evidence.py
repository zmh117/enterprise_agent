#!/usr/bin/env python3
"""独立消费演练的有界只读入口；审计实际输出行，不包含故障规则。"""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('directory', type=Path)
p.add_argument('member', help='ZIP 内文件名，或 external/ 开头的同目录日志/源码')
p.add_argument('--start', type=int, default=1)
p.add_argument('--count', type=int, default=60)
p.add_argument('--match', help='只输出包含该原文标识的行')
a = p.parse_args()
root = a.directory.resolve()
if a.start < 1 or not 1 <= a.count <= 200:
    p.error('start >= 1，count 在 1–200 之间')
if a.member.startswith('rrweb/') or a.member.startswith('pages/'):
    p.error('本演练不读取完整 rrweb 流；请按语义/网络引用定位')
if a.member.startswith('external/'):
    path = (root / a.member).resolve()
    if not path.is_relative_to(root / 'external'):
        p.error('路径越界')
    raw = path.read_bytes()
else:
    with ZipFile(root / 'problem.zip') as z:
        if a.member == '--list':
            raw = '\n'.join(z.namelist()).encode()
        else:
            if 'rrweb' in a.member.lower():
                p.error('演练禁止读取 rrweb 流')
            raw = z.read(a.member)
lines = raw.decode().splitlines()
selected = [(i, line) for i, line in enumerate(lines, 1) if i >= a.start and (a.match is None or a.match in line)][:a.count]
result = '\n'.join(f'{i}: {line}' for i, line in selected)
if len(result) > 40000:
    p.error('输出超过 40,000 字符，请缩小行范围或按引用筛选')
with (root / 'read-audit.ndjson').open('a') as f:
    f.write(json.dumps({'member': a.member, 'start': a.start, 'count': a.count, 'match': a.match, 'returnedLines': [i for i, _ in selected], 'returnedChars': len(result), 'fileSha256': hashlib.sha256(raw).hexdigest()}, ensure_ascii=False) + '\n')
print(result)
