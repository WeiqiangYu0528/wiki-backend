import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from search.chunker import chunk_markdown, chunk_source_file

print("=== TEST 1: chunk_markdown by headings ===")
md = """# Title

Intro paragraph.

## Section One

Content of section one with multiple sentences.
More detail here.

## Section Two

Content of section two.

### Subsection 2.1

Deep content.
"""
chunks = chunk_markdown(md, file_path="docs/test.md")
assert len(chunks) >= 3, f"Expected >=3 chunks, got {len(chunks)}"
assert chunks[0]["file_path"] == "docs/test.md"
assert "section" in chunks[0] or "heading" in chunks[0]
print(f"PASS — {len(chunks)} chunks")

print("\n=== TEST 2: empty markdown ===")
chunks = chunk_markdown("", file_path="docs/empty.md")
assert len(chunks) == 0
print("PASS")

print("\n=== TEST 3: markdown without headings ===")
chunks = chunk_markdown("Just a paragraph.\nAnother line.", file_path="docs/flat.md")
assert len(chunks) == 1
assert "Just a paragraph" in chunks[0]["text"]
print("PASS")

print("\n=== TEST 4: chunk_source_file ===")
py_code = '''"""Module docstring."""

def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}"

class Greeter:
    """A greeter class."""

    def greet(self, name: str) -> str:
        """Greet someone."""
        return f"Hi, {name}"
'''
chunks = chunk_source_file(py_code, file_path="src/hello.py", language="python")
assert len(chunks) >= 2, f"Expected >=2 chunks, got {len(chunks)}"
print(f"PASS — {len(chunks)} chunks")

print("\n=== TEST 5: source with no functions ===")
chunks = chunk_source_file("x = 1\ny = 2\n", file_path="src/const.py", language="python")
assert len(chunks) >= 1
print("PASS")

print("\n=== TEST 6: large section is split ===")
big_section = "## Big\n\n" + ("word " * 2000) + "\n"
chunks = chunk_markdown(big_section, file_path="docs/big.md", max_tokens=500)
assert len(chunks) >= 2
print(f"PASS — split into {len(chunks)} chunks")

print("\n✅ All chunker tests passed.")
