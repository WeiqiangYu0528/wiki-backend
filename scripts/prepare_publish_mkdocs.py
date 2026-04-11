#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def quoted(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def set_top_level_scalar(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"(?m)^{re.escape(key)}:\s*.*$")
    replacement = f"{key}: {quoted(value)}"
    if pattern.search(text):
        return pattern.sub(replacement, text, count=1)

    insertion_anchor = re.compile(r"(?m)^site_description:\s*.*$")
    match = insertion_anchor.search(text)
    if match:
        insert_at = match.end()
        return text[:insert_at] + f"\n{replacement}" + text[insert_at:]

    return replacement + "\n" + text


def enforce_publish_block(text: str, site_url: str, repo_url: str) -> str:
    text = re.sub(r"(?m)^(site_url|repo_url):\s*.*$\n?", "", text)
    publish_block = (
        f'site_url: {quoted(site_url)}\n'
        f'repo_url: {quoted(repo_url)}'
    )

    insertion_anchor = re.compile(r"(?m)^site_description:\s*.*$")
    match = insertion_anchor.search(text)
    if match:
        insert_at = match.end()
        return text[:insert_at] + f"\n{publish_block}" + text[insert_at:]

    return publish_block + "\n" + text


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a publish-safe mkdocs.yml by forcing deployment fields."
    )
    parser.add_argument("source", type=Path, help="Source mkdocs.yml from the working wiki")
    parser.add_argument("target", type=Path, help="Target mkdocs.yml in the publish repo")
    parser.add_argument("--site-url", required=True, help="GitHub Pages site_url to enforce")
    parser.add_argument("--repo-url", required=True, help="Repository URL to enforce")
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    text = enforce_publish_block(text, args.site_url, args.repo_url)

    if not text.endswith("\n"):
        text += "\n"

    args.target.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
