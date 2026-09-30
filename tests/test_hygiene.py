"""The generic repo must not carry names, hosts or addresses from the
environment it was first built for."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANNED = re.compile(r"divar|sotoon|hwb-bare|neda-bare|bigbrother|gateway-envoy|git\.divar|mhossein|"
                    r"\b10\.60\.\d+\.\d+|\b172\.21\.\d+\.\d+", re.I)


def test_no_internal_references():
    hits = []
    for path in ROOT.rglob("*"):
        if ".git" in path.parts or "__pycache__" in path.parts or not path.is_file() or path.name == "test_hygiene.py":
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if BANNED.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:80]}")
    assert not hits, "\n".join(hits)
