import sys, os
sys.path.append(os.path.dirname(__file__))

from agent import search_knowledge_base, read_workspace_file, read_source_file

print("=== TEST 1: search_knowledge_base ===")
res = search_knowledge_base.invoke({"query": "FileInfo"})
print(res[:800])

print("\n=== TEST 2: read a file (explicit project prefix) ===")
res2 = read_workspace_file.invoke({"file_path": "deepagents/libs/deepagents/deepagents/backends/filesystem.py"})
print(res2[:800])

print("\n=== TEST 3: read_source_file (namespace + repo-relative path) ===")
res3 = read_source_file.invoke({"namespace": "deepagents", "file_path": "libs/deepagents/deepagents/middleware/memory.py"})
print(res3[:800])

print("\n=== TEST 4: read_workspace_file fallback (bare repo-relative path) ===")
res4 = read_workspace_file.invoke({"file_path": "libs/deepagents/deepagents/middleware/memory.py"})
print("OK (found via fallback)" if not res4.startswith("Error") else res4)

print("\n=== TEST 5: read_source_file bad namespace ===")
res5 = read_source_file.invoke({"namespace": "bogus", "file_path": "foo.py"})
print(res5)

print("\n=== TEST 6: read_workspace_file wiki doc path ===")
res6 = read_workspace_file.invoke({"file_path": "docs/deepagents-wiki/entities/memory-system.md"})
print("OK (wiki page found)" if not res6.startswith("Error") else res6)
