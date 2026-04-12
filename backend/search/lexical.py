"""Lexical search using ripgrep (rg) or grep fallback."""

import json
import os
import re
import subprocess
from typing import Optional


class LexicalSearch:
    """Fast text search using ripgrep with structured output and ranking."""

    _DEFINITION_PATTERN = re.compile(
        r"^\s*(?:export\s+)?(?:async\s+)?(?:pub(?:lic)?\s+)?(?:static\s+)?(?:abstract\s+)?"
        r"(?:def|fn|func|class|function|interface|type|enum|struct|trait|impl)\s+",
        re.IGNORECASE,
    )

    @staticmethod
    def _camel_to_snake(name: str) -> str:
        """Convert camelCase to snake_case for query expansion."""
        s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

    def _build_pattern(self, query: str) -> str:
        """Build regex pattern with camelCase→snake_case expansion."""
        escaped = re.escape(query)
        snake = self._camel_to_snake(query)
        if snake != query.lower():
            return f"({escaped}|{re.escape(snake)})"
        return escaped

    def __init__(self, workspace_dir: str) -> None:
        self.workspace_dir = workspace_dir
        self._has_rg = self._check_rg()

    def _check_rg(self) -> bool:
        try:
            subprocess.run(["rg", "--version"], capture_output=True, check=True)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            return False

    def search(
        self,
        query: str,
        search_paths: Optional[list[str]] = None,
        max_results: int = 15,
        file_glob: str = "",
        context_lines: int = 2,
    ) -> list[dict]:
        if not query.strip():
            return []

        if search_paths:
            abs_paths = [os.path.join(self.workspace_dir, p) for p in search_paths]
        else:
            abs_paths = [self.workspace_dir]

        abs_paths = [p for p in abs_paths if os.path.exists(p)]
        if not abs_paths:
            return []

        if self._has_rg:
            return self._search_rg(query, abs_paths, max_results, file_glob, context_lines)
        return self._search_grep(query, abs_paths, max_results, file_glob, context_lines)

    def _search_rg(
        self,
        query: str,
        paths: list[str],
        max_results: int,
        file_glob: str,
        context_lines: int,
    ) -> list[dict]:
        if not query.strip():
            return []
        cmd = [
            "rg", "--json",
            "--ignore-case",
            "--max-count", "5",
            f"--context={context_lines}",
            "--max-filesize", "1M",
        ]
        if file_glob:
            cmd.extend(["--glob", file_glob])

        cmd.append(self._build_pattern(query))
        cmd.extend(paths)

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            return []

        results: list[dict] = []
        context_buffer: dict[str, list[str]] = {}

        for line in res.stdout.splitlines():
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj["type"] == "match":
                data = obj["data"]
                file_path = os.path.relpath(data["path"]["text"], self.workspace_dir)
                line_number = data["line_number"]
                text = data["lines"]["text"].rstrip()

                ctx_lines = context_buffer.get(file_path, [])
                ctx_lines.append(text)

                results.append({
                    "file_path": file_path,
                    "line_number": line_number,
                    "text": text,
                    "score": self._score_match(file_path, query, text),
                })

            elif obj["type"] == "context":
                data = obj["data"]
                file_path = os.path.relpath(data["path"]["text"], self.workspace_dir)
                context_buffer.setdefault(file_path, []).append(
                    data["lines"]["text"].rstrip()
                )

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:max_results]

    def _search_grep(
        self,
        query: str,
        paths: list[str],
        max_results: int,
        file_glob: str,
        context_lines: int,
    ) -> list[dict]:
        if not query.strip():
            return []
        cmd = ["grep", "-r", "-E", "-i", "-n", f"-C{context_lines}"]
        if file_glob:
            cmd.extend(["--include", file_glob])

        cmd.append(self._build_pattern(query))
        cmd.extend(paths)

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            return []

        if res.returncode not in (0, 1):
            return []

        results: list[dict] = []
        for line in res.stdout.splitlines():
            if not line.strip() or line.startswith("--"):
                continue
            parts = line.split(":", 2)
            if len(parts) >= 3:
                file_path = os.path.relpath(parts[0], self.workspace_dir)
                try:
                    line_number = int(parts[1])
                except ValueError:
                    continue
                text = parts[2].rstrip()
                results.append({
                    "file_path": file_path,
                    "line_number": line_number,
                    "text": text,
                    "score": self._score_match(file_path, query, text),
                })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:max_results]

    @staticmethod
    def _score_match(file_path: str, query: str, text: str) -> float:
        score = 1.0
        query_lower = query.lower()
        snake = LexicalSearch._camel_to_snake(query)
        match_terms = {query_lower}
        if snake != query_lower:
            match_terms.add(snake)
        basename = os.path.basename(file_path).lower()

        # Filename contains query → strong signal
        if any(t.replace(" ", "-") in basename or t.replace(" ", "_") in basename for t in match_terms):
            score += 5.0

        # Exact text match (original or snake_case variant)
        if query in text or (snake != query.lower() and snake in text):
            score += 2.0

        # Definition line boost
        if LexicalSearch._DEFINITION_PATTERN.match(text) and any(t in text.lower() for t in match_terms):
            score += 3.0

        # Source code boost (not docs) for code-like queries
        if not file_path.startswith("docs/"):
            score += 0.5

        return score
