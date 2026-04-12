"""Chunking logic for wiki markdown and source code files."""

import re


def chunk_markdown(
    content: str,
    file_path: str,
    max_tokens: int = 500,
) -> list[dict]:
    """Split markdown content into chunks by headings.

    Each chunk is a dict with keys: text, file_path, section, heading, start_line.
    """
    if not content.strip():
        return []

    sections: list[dict] = []
    current_heading = ""
    current_lines: list[str] = []
    current_start = 1

    for i, line in enumerate(content.splitlines(), 1):
        heading_match = re.match(r"^(#{1,3})\s+(.+)", line)
        if heading_match and current_lines:
            sections.append({
                "heading": current_heading,
                "text": "\n".join(current_lines).strip(),
                "start_line": current_start,
            })
            current_lines = [line]
            current_heading = heading_match.group(2).strip()
            current_start = i
        else:
            if heading_match:
                current_heading = heading_match.group(2).strip()
                current_start = i
            current_lines.append(line)

    if current_lines:
        sections.append({
            "heading": current_heading,
            "text": "\n".join(current_lines).strip(),
            "start_line": current_start,
        })

    result: list[dict] = []
    for sec in sections:
        if not sec["text"]:
            continue
        words = sec["text"].split()
        if len(words) <= max_tokens:
            result.append({
                "text": sec["text"],
                "file_path": file_path,
                "section": sec["heading"],
                "heading": sec["heading"],
                "start_line": sec["start_line"],
            })
        else:
            for j in range(0, len(words), max_tokens):
                chunk_words = words[j:j + max_tokens]
                result.append({
                    "text": " ".join(chunk_words),
                    "file_path": file_path,
                    "section": sec["heading"],
                    "heading": sec["heading"],
                    "start_line": sec["start_line"],
                })

    return result


def chunk_source_file(
    content: str,
    file_path: str,
    language: str = "python",
    max_lines: int = 200,
) -> list[dict]:
    """Split source code into chunks by top-level definitions.

    Uses regex-based extraction. Each chunk is a dict with
    keys: text, file_path, symbol, kind, start_line.
    """
    if not content.strip():
        return []

    lines = content.splitlines()

    if language in ("python",):
        pattern = re.compile(r"^(class|def|async\s+def)\s+(\w+)")
    elif language in ("typescript", "javascript"):
        pattern = re.compile(
            r"^(?:export\s+)?(?:async\s+)?(?:function|class|interface|type|enum|const)\s+(\w+)"
        )
    elif language in ("csharp",):
        pattern = re.compile(
            r"^\s*(?:public|private|protected|internal|static|abstract|sealed|partial|\s)*"
            r"(?:class|struct|interface|enum|record)\s+(\w+)"
        )
    else:
        pattern = re.compile(r"^(?:def|class|function|interface|type)\s+(\w+)")

    defs: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if m:
            groups = m.groups()
            symbol = groups[-1] if groups else "unknown"
            kind_match = re.match(r"\s*(?:export\s+)?(?:async\s+)?(class|def|function|interface|type|enum|struct|record)", line)
            kind = kind_match.group(1) if kind_match else "definition"
            defs.append((i, symbol, kind))

    if not defs:
        text = "\n".join(lines[:max_lines])
        return [{
            "text": text,
            "file_path": file_path,
            "symbol": "",
            "kind": "module",
            "start_line": 1,
        }]

    chunks: list[dict] = []
    for idx, (start, symbol, kind) in enumerate(defs):
        end = defs[idx + 1][0] if idx + 1 < len(defs) else len(lines)
        end = min(end, start + max_lines)
        text = "\n".join(lines[start:end]).rstrip()
        if text:
            chunks.append({
                "text": text,
                "file_path": file_path,
                "symbol": symbol,
                "kind": kind,
                "start_line": start + 1,
            })

    return chunks
