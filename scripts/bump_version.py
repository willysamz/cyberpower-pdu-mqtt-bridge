#!/usr/bin/env python3
"""Bump version number in VERSION, pyproject.toml, app/__init__.py, and chart/Chart.yaml."""

import re
import sys
from pathlib import Path


def bump_version(version: str, part: str) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    if part == "major":
        major += 1
        minor = 0
        patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    elif part == "patch":
        patch += 1
    else:
        raise ValueError(f"Invalid part: {part}. Must be 'major', 'minor', or 'patch'")
    return f"{major}.{minor}.{patch}"


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"major", "minor", "patch"}:
        print("Usage: bump_version.py [major|minor|patch]")
        sys.exit(1)

    part = sys.argv[1]
    root = Path(__file__).parent.parent

    version_file = root / "VERSION"
    current = version_file.read_text().strip()
    new = bump_version(current, part)

    version_file.write_text(f"{new}\n")
    print(f"Updated VERSION: {current} -> {new}")

    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().replace(
            f'version = "{current}"', f'version = "{new}"'
        )
    )
    print(f"Updated pyproject.toml: {current} -> {new}")

    init_file = root / "app" / "__init__.py"
    init_file.write_text(
        init_file.read_text().replace(
            f'__version__ = "{current}"', f'__version__ = "{new}"'
        )
    )
    print(f"Updated app/__init__.py: {current} -> {new}")

    chart = root / "chart" / "Chart.yaml"
    text = chart.read_text()
    text = re.sub(r"^version: .+$", f"version: {new}", text, flags=re.MULTILINE)
    text = re.sub(r'^appVersion: ".+"$', f'appVersion: "{new}"', text, flags=re.MULTILINE)
    chart.write_text(text)
    print(f"Updated chart/Chart.yaml: {current} -> {new}")


if __name__ == "__main__":
    main()
