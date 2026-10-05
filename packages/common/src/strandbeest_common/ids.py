"""Stable asset identity (ADR-0001, E2-01): ULIDs, plus deterministic "legacy" ids for pre-id documents.

A ULID is 128 bits written as 26 Crockford base32 characters: a 48-bit millisecond timestamp followed by 80 random
bits, so ids sort by creation time. The TypeScript twin is packages/core/src/ids.ts; both are checked against
contracts/ids/ulid-vectors.json.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from typing import Callable

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ULID_RE = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
_TIME_MASK = (1 << 48) - 1
_RAND_MASK = (1 << 80) - 1


def encode_ulid(time_ms: int, randomness: int) -> str:
    """Build a ULID from a millisecond timestamp (48 bits) and 80 random bits."""
    if not 0 <= time_ms <= _TIME_MASK:
        raise ValueError(f"timestamp out of range: {time_ms}")
    if not 0 <= randomness <= _RAND_MASK:
        raise ValueError("randomness must fit in 80 bits")
    n = (time_ms << 80) | randomness
    return "".join(ALPHABET[(n >> shift) & 31] for shift in range(125, -1, -5))


def is_ulid(s: object) -> bool:
    return isinstance(s, str) and ULID_RE.match(s) is not None


def decode_ulid(ulid: str) -> tuple[int, int]:
    """(time_ms, randomness) of a canonical (upper-case) ULID."""
    if not is_ulid(ulid):
        raise ValueError(f"not a ULID: {ulid!r}")
    n = 0
    for ch in ulid:
        n = (n << 5) | ALPHABET.index(ch)
    return n >> 80, n & _RAND_MASK


def ulid_time_ms(ulid: str) -> int:
    return decode_ulid(ulid)[0]


class UlidGenerator:
    """Monotonic generator: ids made in the same millisecond still sort in creation order (the random part is incremented)."""

    def __init__(self, clock: Callable[[], int] | None = None, rng: Callable[[int], bytes] = os.urandom) -> None:
        self._clock = clock or (lambda: time.time_ns() // 1_000_000)
        self._rng = rng
        self._lock = threading.Lock()
        self._last_ms = -1
        self._last_rand = 0

    def new(self) -> str:
        with self._lock:
            ms = max(self._clock(), self._last_ms)  # a clock that steps back must not break ordering
            if ms == self._last_ms:
                rand = self._last_rand + 1
                if rand > _RAND_MASK:
                    raise OverflowError("more than 2^80 ids in one millisecond")
            else:
                rand = int.from_bytes(self._rng(10), "big")
            self._last_ms, self._last_rand = ms, rand
            return encode_ulid(ms, rand)


_default = UlidGenerator()


def new_ulid() -> str:
    return _default.new()


# ---- legacy ids ------------------------------------------------------------------------------------------------
# Documents written before ids existed (schema v1) are identified by a name, and other documents refer to them by that
# name. Reading or migrating such a document must give it the same id on every machine and every run, and a reference
# must resolve to the id of the thing it names without a lookup table. So the id depends only on the kind and the old
# name: time part 0 (these ids sort before every real one; the creation time stays in the document's provenance), random
# part = the first 80 bits of SHA-256("kind:name").
def legacy_ulid(kind: str, key: str) -> str:
    digest = hashlib.sha256(f"{kind}:{key}".encode("utf-8")).digest()
    return encode_ulid(0, int.from_bytes(digest[:10], "big"))
