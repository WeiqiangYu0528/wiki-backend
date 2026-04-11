import sys, os, subprocess, tempfile, shutil
sys.path.append(os.path.dirname(__file__))

from proposals import Proposal, FileChange, ProposalStatus
from git_workflow import GitWorkflow, GitWorkflowError

# --- Setup: create a fake publish repo ---
tmp_dir = tempfile.mkdtemp(prefix="test_publish_")
workspace_dir = tempfile.mkdtemp(prefix="test_workspace_")

# Init publish repo with a main branch
subprocess.run(["git", "init", tmp_dir], check=True, capture_output=True)
subprocess.run(["git", "-C", tmp_dir, "config", "user.email", "test@test.com"], check=True, capture_output=True)
subprocess.run(["git", "-C", tmp_dir, "config", "user.name", "Test"], check=True, capture_output=True)
os.makedirs(os.path.join(tmp_dir, "docs"), exist_ok=True)
with open(os.path.join(tmp_dir, "docs", "index.md"), "w") as f:
    f.write("# Index\n")
subprocess.run(["git", "-C", tmp_dir, "add", "."], check=True, capture_output=True)
subprocess.run(["git", "-C", tmp_dir, "commit", "-m", "init"], check=True, capture_output=True)

# Create workspace docs/
os.makedirs(os.path.join(workspace_dir, "docs"), exist_ok=True)
with open(os.path.join(workspace_dir, "docs", "index.md"), "w") as f:
    f.write("# Index\n")

gw = GitWorkflow(
    workspace_dir=workspace_dir,
    publish_dir=tmp_dir,
    github_token="",
    publish_repo="",
)

# --- Test 1: validate_paths (valid) ---
print("=== TEST 1: validate_paths (valid) ===")
p = Proposal(
    summary="test", commit_message="docs: test",
    files=[FileChange(path="docs/test.md", original_content="", proposed_content="new", diff="+new")]
)
gw.validate_paths(p)
print("PASS")

# --- Test 2: validate_paths (invalid) ---
print("\n=== TEST 2: validate_paths (invalid path) ===")
p_bad = Proposal(
    summary="test", commit_message="docs: test",
    files=[FileChange(path="backend/agent.py", original_content="", proposed_content="hacked", diff="")]
)
try:
    gw.validate_paths(p_bad)
    print("FAIL — should have raised")
except GitWorkflowError as e:
    assert "outside allowed prefix" in str(e)
    print("PASS")

# --- Test 3: write_files_to_workspace ---
print("\n=== TEST 3: write_files_to_workspace ===")
p_write = Proposal(
    summary="test", commit_message="docs: test",
    files=[FileChange(
        path="docs/test-page.md",
        original_content="",
        proposed_content="# Test Page\nContent here.\n",
        diff="",
    )]
)
written = gw.write_files_to_workspace(p_write)
assert written == ["docs/test-page.md"]
target_file = os.path.join(workspace_dir, "docs", "test-page.md")
assert os.path.exists(target_file)
with open(target_file) as f:
    assert f.read() == "# Test Page\nContent here.\n"
print("PASS")

# --- Test 4: create_branch ---
print("\n=== TEST 4: create_branch ===")
gw.create_branch("docs/test-branch")
res = subprocess.run(["git", "-C", tmp_dir, "branch", "--show-current"], capture_output=True, text=True)
assert res.stdout.strip() == "docs/test-branch"
print("PASS")

# --- Test 5: sync_to_publish ---
print("\n=== TEST 5: sync_to_publish ===")
gw.sync_to_publish()
synced_file = os.path.join(tmp_dir, "docs", "test-page.md")
assert os.path.exists(synced_file)
with open(synced_file) as f:
    assert f.read() == "# Test Page\nContent here.\n"
print("PASS")

# --- Test 6: commit (local only, no push) ---
print("\n=== TEST 6: commit locally ===")
gw._git(["add", "docs/"])
gw._git(["commit", "-m", "docs: test commit"])
sha = gw._git(["rev-parse", "HEAD"]).strip()
assert len(sha) == 40
print(f"PASS (sha={sha[:8]})")

# --- Test 7: cleanup_branch ---
print("\n=== TEST 7: cleanup_branch ===")
gw.cleanup_branch()
res = subprocess.run(["git", "-C", tmp_dir, "branch", "--show-current"], capture_output=True, text=True)
assert res.stdout.strip() == "main"
print("PASS")

# --- Cleanup ---
shutil.rmtree(tmp_dir)
shutil.rmtree(workspace_dir)

print("\n✅ All git workflow tests passed.")
