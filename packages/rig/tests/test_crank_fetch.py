"""The raw-data reader must reject a server that ignores or truncates ranges."""
import importlib.util
import io
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('crank_fetch', Path(__file__).resolve().parents[1] / 'scripts/fetch_crank_trials.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def reader():
    return MODULE.RangeReader({'size': 100, 'links': {'self': 'https://example.invalid/data'}},
        {'max_single_request_bytes': 10, 'max_total_bytes': 12})


class Response(io.BytesIO):
    def __init__(self, content, status=206, content_range='bytes 0-4/100'):
        super().__init__(content)
        self.status = status
        self.headers = {'Content-Range': content_range}


def test_exact_range_is_accepted_with_identity_encoding(monkeypatch):
    def serve(request, timeout):
        assert request.headers['Range'] == 'bytes=0-4'
        assert request.headers['Accept-encoding'] == 'identity'
        return Response(b'abcde')
    monkeypatch.setattr(MODULE.urllib.request, 'urlopen', serve)
    r = reader()
    assert r.read(5) == b'abcde'
    assert r.tell() == r.transferred == 5


@pytest.mark.parametrize('status,header', [(200, 'bytes 0-4/100'), (206, 'bytes 5-9/100')])
def test_ignored_or_wrong_range_is_rejected(monkeypatch, status, header):
    monkeypatch.setattr(MODULE.urllib.request, 'urlopen', lambda *a, **k: Response(b'abcde', status, header))
    with pytest.raises(ValueError, match='exact bounded range'):
        reader().read(5)


def test_truncation_is_rejected_and_counted_without_advancing_cursor(monkeypatch):
    monkeypatch.setattr(MODULE.urllib.request, 'urlopen', lambda *a, **k: Response(b'ab'))
    r = reader()
    with pytest.raises(ValueError, match='response length'):
        r.read(5)
    assert r.tell() == 0 and r.transferred == 2
    assert r.requests == [{'start': 0, 'length': 5, 'received': 2}]


def test_limit_failure_performs_no_network_request(monkeypatch):
    monkeypatch.setattr(MODULE.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('Unexpected network request'))
    r = reader()
    with pytest.raises(ValueError, match='bound'):
        r.read(11)
    r.transferred = 8
    with pytest.raises(ValueError, match='bound'):
        r.read(5)


def test_segmented_ranges_reassemble_without_reordering(monkeypatch):
    monkeypatch.setattr(MODULE, 'MAX_RANGE_CHUNK', 3)
    expected = iter([('bytes=0-2', b'abc', 'bytes 0-2/100'), ('bytes=3-4', b'de', 'bytes 3-4/100')])
    def serve(request, timeout):
        request_range, raw, content_range = next(expected)
        assert request.headers['Range'] == request_range
        return Response(raw, content_range=content_range)
    monkeypatch.setattr(MODULE.urllib.request, 'urlopen', serve)
    r = reader()
    assert r.read(5) == b'abcde'
    assert r.tell() == r.transferred == 5
    assert len(r.requests) == 2
