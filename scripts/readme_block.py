"""Print the README.md code block marked ``<!-- test: KIND [NAME] -->``.

CI runs the Installation commands this way (``python scripts/readme_block.py install``), and
tests/functional/test_readme.py runs the others.
"""

import argparse
import re
import sys
from pathlib import Path

BLOCK = re.compile(
    pattern=r"<!-- test: (?P<kind>\w+)(?: (?P<name>[^ ]+))? -->\n```[\w-]*\n(?P<body>.*?)```",
    flags=re.DOTALL,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind")
    parser.add_argument("name", nargs="?")
    args = parser.parse_args()
    readme = Path(__file__).resolve().parents[1] / "README.md"
    found = [
        match["body"]
        for match in BLOCK.finditer(string=readme.read_text())
        if match["kind"] == args.kind and match["name"] == args.name
    ]
    if len(found) != 1:
        print(f"README.md has {len(found)} `test: {args.kind}` blocks, not 1", file=sys.stderr)
        return 1
    sys.stdout.write(found[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
