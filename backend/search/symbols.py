"""Symbol extraction using tree-sitter for Python, TypeScript, and C#."""

import logging
import threading
from typing import Any

import tree_sitter

logger = logging.getLogger(__name__)

_PARSERS: dict[str, tree_sitter.Parser] = {}
_PARSER_LOCK = threading.Lock()

_LANGUAGE_MAP = {
    "python": "tree_sitter_python",
    "typescript": "tree_sitter_typescript",
    "tsx": "tree_sitter_typescript",
    "javascript": "tree_sitter_typescript",
    "csharp": "tree_sitter_c_sharp",
}

_DEFINITION_TYPES = {
    "python": {
        "function_definition", "class_definition",
    },
    "typescript": {
        "function_declaration", "class_declaration", "interface_declaration",
        "type_alias_declaration", "enum_declaration", "method_definition",
    },
    "csharp": {
        "class_declaration", "struct_declaration", "interface_declaration",
        "enum_declaration", "method_declaration", "record_declaration",
    },
}


def _get_parser(language: str) -> tree_sitter.Parser | None:
    with _PARSER_LOCK:
        if language in _PARSERS:
            return _PARSERS[language]

        module_name = _LANGUAGE_MAP.get(language)
        if not module_name:
            return None

        try:
            import importlib
            mod = importlib.import_module(module_name)
            if hasattr(mod, "language"):
                lang = tree_sitter.Language(mod.language())
            elif language in ("typescript", "javascript") and hasattr(mod, "language_typescript"):
                lang = tree_sitter.Language(mod.language_typescript())
            elif language == "tsx" and hasattr(mod, "language_tsx"):
                lang = tree_sitter.Language(mod.language_tsx())
            else:
                return None

            parser = tree_sitter.Parser(lang)
            _PARSERS[language] = parser
            return parser
        except Exception as e:
            logger.warning("Failed to load tree-sitter parser for %s: %s", language, e)
            return None


class SymbolExtractor:
    def extract(
        self,
        file_path: str,
        content: str,
        language: str,
    ) -> list[dict]:
        if not content.strip():
            return []

        parser = _get_parser(language)
        if not parser:
            return []

        try:
            tree = parser.parse(content.encode("utf-8"))
        except Exception as e:
            logger.warning("tree-sitter parse failed for %s: %s", file_path, e)
            return []

        def_types = _DEFINITION_TYPES.get(language, set())
        symbols: list[dict] = []
        self._walk(tree.root_node, file_path, language, def_types, content, symbols)
        return symbols

    def _walk(
        self,
        node: Any,
        file_path: str,
        language: str,
        def_types: set[str],
        source: str,
        symbols: list[dict],
    ) -> None:
        if node.type in def_types:
            sym = self._extract_symbol(node, file_path, language, source)
            if sym:
                symbols.append(sym)

        for child in node.children:
            self._walk(child, file_path, language, def_types, source, symbols)

    def _extract_symbol(
        self,
        node: Any,
        file_path: str,
        language: str,
        source: str,
    ) -> dict | None:
        name = ""
        kind = node.type.replace("_declaration", "").replace("_definition", "")

        for child in node.children:
            if child.type in ("identifier", "name", "type_identifier", "property_identifier"):
                name = source[child.start_byte:child.end_byte]
                break

        if not name:
            return None

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        lines = source.splitlines()
        signature = lines[start_line - 1].strip() if start_line <= len(lines) else ""

        docstring = ""
        if language == "python":
            for child in node.children:
                if child.type == "block":
                    for stmt in child.children:
                        if stmt.type == "expression_statement":
                            for expr in stmt.children:
                                if expr.type == "string":
                                    docstring = source[expr.start_byte:expr.end_byte].strip("\"' \n")
                                    break
                        break
                    break

        return {
            "name": name,
            "kind": kind,
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "signature": signature,
            "docstring": docstring[:200],
        }
