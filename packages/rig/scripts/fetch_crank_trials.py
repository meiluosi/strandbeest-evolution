"""Fetch only predeclared public crank trials; validate ZIP entries without executing code."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path

MAX_RANGE_CHUNK = 65536  # Bound individual transport responses; not a data filter.


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class RangeReader(io.RawIOBase):
    def __init__(self, entry, limits):
        self.entry, self.limits = entry, limits
        self.position = self.transferred = 0
        self.requests = []

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset if whence == 0 else self.position + offset if whence == 1 else self.entry['size'] + offset
        if not 0 <= position <= self.entry['size']:
            raise ValueError('Range seek out of bounds')
        self.position = position
        return position

    def read(self, count=-1):
        count = self.entry['size'] - self.position if count < 0 else min(count, self.entry['size'] - self.position)
        if count == 0:
            return b''
        if count > self.limits['max_single_request_bytes'] or self.transferred + count > self.limits['max_total_bytes']:
            raise ValueError('Predeclared transfer bound exceeded')
        parts = []
        for offset in range(0, count, MAX_RANGE_CHUNK):
            length = min(count - offset, MAX_RANGE_CHUNK)
            start = self.position + offset
            stop = start + length - 1
            request = urllib.request.Request(self.entry['links']['self'], headers={
                'Range': f'bytes={start}-{stop}', 'Accept-Encoding': 'identity',
                'User-Agent': 'Beest-Engine-public-data-validation/1.0'})
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 206 or response.headers.get('Content-Range') != f"bytes {start}-{stop}/{self.entry['size']}":
                    raise ValueError('Server did not honour exact bounded range')
                raw = response.read(length + 1)
            # Failed reads are evidence too and consume the total transfer bound.
            self.transferred += len(raw)
            self.requests.append({'start': start, 'length': length, 'received': len(raw)})
            if len(raw) != length:
                raise ValueError('Wrong range response length')
            parts.append(raw)
        self.position += count
        return b''.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume-manifest', type=Path)
    parser.add_argument('--earlier-transfer-bound', type=int, default=0)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    ds = plan['dataset']
    assert digest(ds['metadata_path']) == ds['metadata_sha256']
    metadata = json.loads(Path(ds['metadata_path']).read_text())
    assert metadata['metadata']['license']['id'] == 'cc-by-4.0'
    entry, = metadata['files']
    reader = RangeReader(entry, plan['raw_download_limits'])
    args.output.mkdir(parents=True, exist_ok=False)
    result = {'complete': False, 'plan_path': str(args.plan), 'plan_sha256': digest(args.plan),
        'script_sha256': digest(__file__), 'files': [], 'requests': [], 'bytes_transferred': 0,
        'whole_archive_md5_verified': False, 'source_license': 'CC BY 4.0',
        'attribution': 'Hermus, Doeringer, Sternad and Hogan, Crank Turning Data, doi:10.5281/zenodo.10059390'}
    if args.earlier_transfer_bound < 0:
        raise ValueError('Earlier transfer bound cannot be negative')
    reader.transferred = args.earlier_transfer_bound
    result['earlier_transfer_upper_bound_bytes'] = args.earlier_transfer_bound
    if args.resume_manifest:
        previous = json.loads(args.resume_manifest.read_text())
        assert previous['plan_sha256'] == digest(args.plan)
        expected = {r['name']: r for r in plan['selected_trials']}
        for row in previous['files']:
            assert all(row[k] == v for k, v in expected[row['name']].items())
            assert digest(row['local_path']) == row['sha256'] and row['zip_crc32_verified']
        assert len({r['name'] for r in previous['files']}) == len(previous['files'])
        result['files'] = previous['files'].copy()
        result['resumed_from'] = {'path': str(args.resume_manifest), 'sha256': digest(args.resume_manifest)}
        reader.transferred += previous['bytes_transferred']
        reader.requests = previous['requests'].copy()
    output = args.output / 'manifest.json'
    def checkpoint():
        result['requests'] = reader.requests
        result['bytes_transferred'] = reader.transferred
        output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    checkpoint()
    try:
        with zipfile.ZipFile(reader) as archive:
            existing = {row['name'] for row in result['files']}
            for trial in plan['selected_trials']:
                if trial['name'] in existing:
                    continue
                info = archive.getinfo(trial['name'])
                assert info.file_size == trial['bytes'] and f'{info.CRC:08x}' == trial['crc32']
                assert info.file_size <= plan['raw_download_limits']['max_entry_bytes']
                raw = archive.read(info)  # zipfile verifies the full member CRC.
                name = Path(info.filename).name
                destination = args.output / name
                with destination.open('xb') as stream:
                    stream.write(raw)
                result['files'].append({**trial, 'local_path': str(destination),
                    'sha256': hashlib.sha256(raw).hexdigest(), 'zip_crc32_verified': True})
                checkpoint()
                print(json.dumps({'done': len(result['files']), 'file': name,
                                  'transferred': reader.transferred}), flush=True)
        result['complete'] = True
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        checkpoint()


if __name__ == '__main__':
    main()
