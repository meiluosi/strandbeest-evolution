#!/usr/bin/env python3
"""Verify the exported package only. No network, installations or experiments."""
from pathlib import Path
import hashlib, re, sys
from urllib.parse import urlparse, unquote
root=Path(__file__).resolve().parent
errors=[]
count=0
for line in (root/'SHA256SUMS').read_text(encoding='utf-8').splitlines():
    expected, relative=line.split('  ',1)
    p=(root/relative).resolve()
    if not p.is_relative_to(root) or not p.is_file():
        errors.append(f'Missing/unsafe path: {relative}'); continue
    actual=hashlib.sha256(p.read_bytes()).hexdigest()
    if actual!=expected: errors.append(f'Checksum mismatch: {relative}')
    count+=1
for p in root.rglob('*.md'):
    if p.parent.name=='originals': continue
    text=p.read_text(encoding='utf-8')
    clean=re.sub(r'^```[^\n]*\n.*?^```[ \t]*$', '', text, flags=re.M|re.S)
    for target in re.findall(r'(?<!!)\[[^\]\n]*\]\(([^)\n]+)\)',clean):
        target=target.split(' "',1)[0]
        if target.startswith('#') or urlparse(target).scheme: continue
        target=target.split('#',1)[0]
        if target and not (p.parent/unquote(target)).exists():
            errors.append(f'Broken relative link: {p.relative_to(root)} -> {target}')
if errors:
    print('FAILED\n'+'\n'.join(errors)); sys.exit(1)
print(f'OK: {count} file hashes verified; relative file links resolved.')
print('This does not validate the repository implementation, scientific results or external links.')
