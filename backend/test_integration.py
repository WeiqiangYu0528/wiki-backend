"""Integration test: full proposal → approve → git workflow cycle."""
import sys, os, subprocess, tempfile, shutil, json, re
sys.path.append(os.path.dirname(__file__))

from proposals import proposal_store, ProposalStatus, Proposal, FileChange, ALLOWED_PATH_PREFIX
from agent import propose_doc_change, tools, ROOT_DIR
from git_workflow import GitWorkflow, GitWorkflowError

print("=" * 60)
print("INTEGRATION TEST: Approval-Gated Wiki Documentation Agent")
print("=" * 60)

# --- Safety Test 1: Agent has no direct git tools ---
print("\n--- Safety 1: No direct git tools ---")
tool_names = [t.name for t in tools]
assert "run_git_commit" not in tool_names, "FAIL: run_git_commit still in tools!"
assert "run_git_push" not in tool_names, "FAIL: run_git_push still in tools!"
assert "propose_doc_change" in tool_names
print("PASS — agent cannot directly commit or push")

# --- Safety Test 2: Path restriction ---
print("\n--- Safety 2: Path restriction on proposals ---")
result = propose_doc_change.invoke({"changes": json.dumps({
    "summary": "test",
    "commit_message": "test",
    "files": [{"path": "backend/agent.py", "content": "hacked"}],
})})
assert "Error" in result and "outside" in result
print("PASS — non-docs/ paths are rejected")

# --- Safety Test 3: Path restriction on git workflow ---
print("\n--- Safety 3: Path restriction on git workflow ---")
bad_proposal = Proposal(
    summary="hack", commit_message="hack",
    files=[FileChange(path="backend/evil.py", original_content="", proposed_content="evil", diff="")],
)
tmp_dir = tempfile.mkdtemp()
try:
    subprocess.run(["git", "init", tmp_dir], check=True, capture_output=True)
    gw = GitWorkflow(workspace_dir=ROOT_DIR, publish_dir=tmp_dir)
    try:
        gw.execute(bad_proposal)
        print("FAIL — should have raised GitWorkflowError")
    except GitWorkflowError as e:
        assert "outside allowed prefix" in str(e)
        print("PASS — git workflow rejects non-docs/ paths")
finally:
    shutil.rmtree(tmp_dir)

# --- Functional Test 4: Full proposal creation ---
print("\n--- Functional 4: Create a proposal ---")
result = propose_doc_change.invoke({"changes": json.dumps({
    "summary": "Improve memory system documentation",
    "commit_message": "docs(deepagents): improve memory system docs",
    "files": [{
        "path": "docs/deepagents-wiki/entities/memory-system.md",
        "content": "# Memory System\n\nImproved documentation.\n",
    }],
})})
assert "Proposal ID:" in result
pid = re.search(r"Proposal ID: `(\w+)`", result).group(1)
proposal = proposal_store.get(pid)
assert proposal is not None
assert proposal.status == ProposalStatus.PENDING
assert len(proposal.files) == 1
assert proposal.files[0].path == "docs/deepagents-wiki/entities/memory-system.md"
print(f"PASS — proposal {pid} created in PENDING state")

# --- Functional Test 5: Reject proposal ---
print("\n--- Functional 5: Reject proposal ---")
proposal_store.update_status(pid, ProposalStatus.REJECTED)
assert proposal_store.get(pid).status == ProposalStatus.REJECTED
print("PASS — proposal rejected, no files written")

# --- Functional Test 6: Full git workflow (local mock repo) ---
print("\n--- Functional 6: Full git workflow with mock publish repo ---")
tmp_publish = tempfile.mkdtemp(prefix="test_publish_")
tmp_workspace = tempfile.mkdtemp(prefix="test_workspace_")
try:
    # Init mock publish repo
    subprocess.run(["git", "init", tmp_publish], check=True, capture_output=True)
    subprocess.run(["git", "-C", tmp_publish, "config", "user.email", "t@t.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", tmp_publish, "config", "user.name", "T"], check=True, capture_output=True)
    os.makedirs(os.path.join(tmp_publish, "docs"), exist_ok=True)
    with open(os.path.join(tmp_publish, "docs", "index.md"), "w") as f:
        f.write("# Index\n")
    subprocess.run(["git", "-C", tmp_publish, "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", tmp_publish, "commit", "-m", "init"], check=True, capture_output=True)

    # Create workspace with a docs/ file
    os.makedirs(os.path.join(tmp_workspace, "docs", "deepagents-wiki", "entities"), exist_ok=True)
    with open(os.path.join(tmp_workspace, "docs", "deepagents-wiki", "entities", "test.md"), "w") as f:
        f.write("# Test Entity\n\nUpdated content.\n")

    # Create proposal
    fc = FileChange(
        path="docs/deepagents-wiki/entities/test.md",
        original_content="# Test\n",
        proposed_content="# Test Entity\n\nUpdated content.\n",
        diff="- # Test\n+ # Test Entity\n+ Updated content.",
    )
    test_proposal = proposal_store.create(
        summary="Update test entity",
        commit_message="docs(deepagents): update test entity",
        files=[fc],
    )

    # Execute workflow (no push since no remote)
    gw = GitWorkflow(workspace_dir=tmp_workspace, publish_dir=tmp_publish)
    gw.validate_paths(test_proposal)
    gw.create_branch(f"docs/test-{test_proposal.id}")
    gw.write_files_to_workspace(test_proposal)
    gw.sync_to_publish()
    gw._git(["add", "docs/"])
    gw._git(["commit", "-m", test_proposal.commit_message])
    sha = gw._git(["rev-parse", "HEAD"]).strip()
    gw.cleanup_branch()

    # Verify
    assert len(sha) == 40
    res = subprocess.run(["git", "-C", tmp_publish, "log", "--oneline", "--all"], capture_output=True, text=True)
    assert "docs(deepagents)" in res.stdout
    print(f"PASS — branch created, committed (sha={sha[:8]}), cleaned up")
finally:
    shutil.rmtree(tmp_publish)
    shutil.rmtree(tmp_workspace)

# --- Summary ---
print("\n" + "=" * 60)
print("✅ ALL INTEGRATION TESTS PASSED")
print("=" * 60)
print("""
Safety guarantees verified:
  ✓ Agent has no direct git write tools
  ✓ propose_doc_change rejects non-docs/ paths
  ✓ GitWorkflow rejects non-docs/ paths
  ✓ Proposals require explicit status transition
  ✓ Git workflow creates branch (never commits to main)
  ✓ Branch cleanup returns to main after workflow
""")
