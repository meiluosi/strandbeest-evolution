"""Log the firmware's serial stream to a file. The line source is injectable so the logic is testable without a port."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Iterable


def log_lines(lines: Iterable[str], out_path: str | Path, duration_s: float | None = None, now: Callable[[], float] = time.monotonic) -> int:
    """Write lines to `out_path` until the iterator ends or `duration_s` has passed. Returns the number of lines written."""
    n = 0
    start = now()
    with open(out_path, "w") as f:
        for line in lines:
            line = line.rstrip("\r\n")
            if not line:
                continue
            f.write(line + "\n")
            n += 1
            if duration_s is not None and now() - start >= duration_s:
                break
    return n


def log_serial(port: str, baud: int, out_path: str | Path, duration_s: float, omega_rad_s: float | None = None) -> int:
    """Open `port`, optionally set the crank speed and start, log for `duration_s`, then stop the motor.
    Needs pyserial: pip install "strandbeest-rig[serial]". Not tested against hardware."""
    import serial  # type: ignore

    with serial.Serial(port, baud, timeout=1) as s:
        s.reset_input_buffer()

        def lines():
            while True:
                raw = s.readline()
                if raw:
                    yield raw.decode(errors="replace")

        try:
            s.write(b"ZERO\n")
            if omega_rad_s is not None:
                s.write(f"S {omega_rad_s}\n".encode())
            s.write(b"START\n")
            return log_lines(lines(), out_path, duration_s)
        finally:
            s.write(b"STOP\n")
