import sys, os
sys.path.append(os.path.dirname(__file__))

from proposals import ProposalStore, ProposalStatus, FileChange, compute_diff

store = ProposalStore()

# --- Test 1: compute_diff ---
print("=== TEST 1: compute_diff ===")
diff = compute_diff("docs/test.md", "line one\nline two\n", "line one\nline TWO\n")
assert "line two" in diff and "line TWO" in diff, f"Unexpected diff: {diff}"
print("PASS")

# --- Test 2: create proposal ---
print("\n=== TEST 2: create proposal ===")
fc = FileChange(
    path="docs/deepagents-wiki/entities/memory-system.md",
    original_content="old content",
    proposed_content="new content",
    diff="@@ -1 +1 @@\n-old content\n+new content",
)
p = store.create(summary="Improve memory docs", commit_message="docs: improve memory", files=[fc])
assert p.id and len(p.id) == 12, f"Bad ID: {p.id}"
assert p.status == ProposalStatus.PENDING
print(f"PASS (id={p.id})")

# --- Test 3: get proposal ---
print("\n=== TEST 3: get proposal ===")
fetched = store.get(p.id)
assert fetched is not None and fetched.id == p.id
assert fetched.files[0].path == "docs/deepagents-wiki/entities/memory-system.md"
print("PASS")

# --- Test 4: update status ---
print("\n=== TEST 4: update status ===")
store.update_status(p.id, ProposalStatus.APPROVED)
assert store.get(p.id).status == ProposalStatus.APPROVED
print("PASS")

# --- Test 5: update status with result ---
print("\n=== TEST 5: update status with result ===")
store.update_status(p.id, ProposalStatus.COMPLETED, result={"branch": "docs/test", "commit_sha": "abc123"})
assert store.get(p.id).result["branch"] == "docs/test"
print("PASS")

# --- Test 6: list_pending ---
print("\n=== TEST 6: list_pending ===")
fc2 = FileChange(path="docs/x.md", original_content="", proposed_content="x", diff="+x")
p2 = store.create(summary="Another", commit_message="docs: x", files=[fc2])
pending = store.list_pending()
assert len(pending) == 1 and pending[0].id == p2.id
print("PASS")

# --- Test 7: get nonexistent ---
print("\n=== TEST 7: get nonexistent ===")
assert store.get("nonexistent") is None
print("PASS")

# --- Test 8: path validation ---
print("\n=== TEST 8: path validation ===")
from proposals import ALLOWED_PATH_PREFIX
assert ALLOWED_PATH_PREFIX == "docs/"
print("PASS")

print("\n✅ All proposal tests passed.")
