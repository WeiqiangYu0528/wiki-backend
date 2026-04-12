import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from search.symbols import SymbolExtractor

se = SymbolExtractor()

print("=== TEST 1: Python symbols ===")
py_code = '''
"""Module docstring."""

import os

def hello(name: str) -> str:
    """Say hello to someone."""
    return f"Hello, {name}"

class Greeter:
    """A class that greets people."""

    def greet(self, name: str) -> str:
        """Greet a specific person."""
        return f"Hi, {name}"

    async def greet_async(self, name: str) -> str:
        """Async greet."""
        return f"Hi, {name}"

CONSTANT = 42
'''
symbols = se.extract("test.py", py_code, "python")
names = {s["name"] for s in symbols}
assert "hello" in names
assert "Greeter" in names
assert "greet" in names
assert "greet_async" in names
print(f"PASS — found: {names}")

print("\n=== TEST 2: TypeScript symbols ===")
ts_code = '''
export interface ToolConfig {
  name: string;
  handler: Function;
}

export class ToolRegistry {
  register(config: ToolConfig): void {}
}

export function createAgent(name: string): Agent {
  return new Agent(name);
}

export type AgentState = "idle" | "running";
'''
symbols = se.extract("tools.ts", ts_code, "typescript")
names = {s["name"] for s in symbols}
assert "ToolConfig" in names
assert "ToolRegistry" in names
assert "createAgent" in names
print(f"PASS — found: {names}")

print("\n=== TEST 3: symbol metadata ===")
hello_sym = next(s for s in se.extract("t.py", py_code, "python") if s["name"] == "hello")
assert hello_sym["kind"] in ("function", "def")
assert hello_sym["file_path"] == "t.py"
assert hello_sym["start_line"] > 0
assert "signature" in hello_sym
print(f"PASS — {hello_sym}")

print("\n=== TEST 4: empty file ===")
symbols = se.extract("empty.py", "", "python")
assert symbols == []
print("PASS")

print("\n=== TEST 5: unsupported language ===")
symbols = se.extract("test.rb", "def hello; end", "ruby")
assert symbols == []
print("PASS")

print("\n✅ All symbol extraction tests passed.")
