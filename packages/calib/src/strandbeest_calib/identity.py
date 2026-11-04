"""Source identity for the physical calibration adapter and inference code."""

from pathlib import Path

from strandbeest_common.implementation import ProcessImplementation, installed_files


def _files():
    files = installed_files()
    root = Path(__file__).parent
    files.update({f"strandbeest_calib/{p.name}": p for p in sorted(root.glob("*.py"))})
    return files


CALIBRATION_IMPLEMENTATION = ProcessImplementation(files=_files)
