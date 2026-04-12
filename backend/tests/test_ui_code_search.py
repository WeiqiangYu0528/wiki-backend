"""UI browser tests for code-search chat experience.

Uses Playwright to interact with the MkDocs chat widget, send 5 coding-related
questions, and verify that the agent responds without hanging. These tests
exercise the full stack: frontend → backend → search → LLM → UI.

Requirements:
  - Docker services running (backend, ollama, meilisearch, mkdocs)
  - Playwright + chromium installed: pip install playwright && python -m playwright install chromium
  - MFA disabled (app_mfa_secret empty)

Run:
  python -m pytest tests/test_ui_code_search.py -v --timeout=300
"""

import os
import time
import pytest

# Skip entire module if playwright is not installed
playwright = pytest.importorskip("playwright.sync_api", reason="playwright not installed")

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8000")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")
ADMIN_USER = os.getenv("APP_ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("APP_ADMIN_PASSWORD", "StrongPassword123!")
# Maximum seconds to wait for a chat response
RESPONSE_TIMEOUT = 180_000  # 180s in ms — Ollama local models can be slow


@pytest.fixture(scope="module")
def browser():
    """Launch a headless Chromium browser for the test module."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True)
    yield b
    b.close()
    pw.stop()


@pytest.fixture(scope="module")
def authenticated_page(browser):
    """Open the frontend and authenticate via the chat widget."""
    page = browser.new_page()
    page.goto(FRONTEND_URL, wait_until="networkidle", timeout=30_000)

    # Click the FAB (floating action button) to open the chat panel
    fab = page.locator("#chat-fab")
    if fab.count() > 0:
        fab.click()
        page.wait_for_timeout(500)

    # Wait for auth form to be visible
    page.wait_for_selector("#auth-user", state="visible", timeout=10_000)

    # Fill login form
    page.fill("#auth-user", ADMIN_USER)
    page.fill("#auth-pass", ADMIN_PASS)
    # MFA field left empty (disabled)
    page.click("#auth-btn")

    # Wait for auth to complete — chat body should become visible
    page.wait_for_selector("#chat-body", state="visible", timeout=15_000)
    page.wait_for_timeout(500)

    # Select the Ollama (local) model to avoid paid API tokens
    page.select_option("#chat-model-select", "ollama")
    page.wait_for_timeout(300)

    yield page
    page.close()


def _send_chat_and_wait(page, message: str, timeout_ms: int = RESPONSE_TIMEOUT) -> dict:
    """Send a chat message and wait for a response.

    Returns dict with:
      - response_text: the text of the last assistant message
      - latency_s: time from send to response visible
      - had_error: whether an error indicator appeared
    """
    # Wait for input to be enabled (may be disabled from previous request)
    # Also wait for stop button to be hidden (streaming finished)
    try:
        page.wait_for_function(
            """() => {
                const inp = document.getElementById('chat-input');
                const stop = document.getElementById('chat-stop');
                return !inp.disabled && (!stop || stop.style.display === 'none');
            }""",
            timeout=timeout_ms,
        )
    except Exception:
        # If input never re-enabled, the previous request may have hung.
        # Try clicking stop if visible, then proceed.
        stop_btn = page.locator("#chat-stop")
        if stop_btn.count() > 0 and stop_btn.first.is_visible():
            stop_btn.first.click()
            page.wait_for_timeout(2000)

    # Count existing agent messages so we can detect the NEW one
    existing_count = page.evaluate(
        "() => document.querySelectorAll('.chat-msg.msg-agent').length"
    )

    start = time.time()

    # Type message and send
    input_el = page.locator("#chat-input")
    input_el.fill(message, timeout=10_000)
    page.click("#chat-send")

    # Wait for a NEW agent message (beyond existing_count) with real content
    try:
        page.wait_for_function(
            """(prevCount) => {
                const msgs = document.querySelectorAll('.chat-msg.msg-agent');
                if (msgs.length <= prevCount) return false;
                const last = msgs[msgs.length - 1];
                const content = last.querySelector('.msg-content');
                if (!content) return false;
                const text = content.textContent.trim();
                return text.length > 10 && !content.querySelector('.loader');
            }""",
            arg=existing_count,
            timeout=timeout_ms,
        )
    except Exception:
        pass

    latency = time.time() - start

    # Extract response text from last agent message
    response_text = page.evaluate(
        """() => {
            const msgs = document.querySelectorAll('.chat-msg.msg-agent');
            if (msgs.length === 0) return '';
            const last = msgs[msgs.length - 1];
            const content = last.querySelector('.msg-content');
            return content ? content.textContent.trim() : '';
        }"""
    )

    # Check for error indicators
    had_error = page.evaluate(
        """() => {
            const errs = document.querySelectorAll('.chat-error, .error-message, [data-error]');
            return errs.length > 0;
        }"""
    )

    return {
        "response_text": response_text,
        "latency_s": latency,
        "had_error": had_error,
    }


# ─── Coding-related UI tests ───────────────────────────────────────────────


class TestUICodeSearch:
    """5 coding-related questions sent through the chat UI."""

    @pytest.mark.skipif(
        os.getenv("SKIP_UI_TESTS", "0") == "1",
        reason="UI tests disabled via SKIP_UI_TESTS=1",
    )
    def test_q1_explain_function(self, authenticated_page):
        """Q1: Ask the agent to explain a function (code-location test)."""
        result = _send_chat_and_wait(
            authenticated_page,
            "Explain what classify_query does and where it is defined",
        )
        assert result["response_text"], "Agent should return a response"
        assert result["latency_s"] < 180, f"Response took {result['latency_s']:.1f}s, too slow"
        # Should mention something code-related
        low = result["response_text"].lower()
        assert any(w in low for w in ["classify", "query", "search", "function", "def"]), \
            f"Response should be about classify_query, got: {result['response_text'][:200]}"

    @pytest.mark.skipif(
        os.getenv("SKIP_UI_TESTS", "0") == "1",
        reason="UI tests disabled via SKIP_UI_TESTS=1",
    )
    def test_q2_find_class(self, authenticated_page):
        """Q2: Ask the agent to find a class implementation."""
        result = _send_chat_and_wait(
            authenticated_page,
            "Where is SearchOrchestrator implemented?",
        )
        assert result["response_text"], "Agent should return a response"
        assert result["latency_s"] < 180, f"Response took {result['latency_s']:.1f}s, too slow"

    @pytest.mark.skipif(
        os.getenv("SKIP_UI_TESTS", "0") == "1",
        reason="UI tests disabled via SKIP_UI_TESTS=1",
    )
    def test_q3_search_strategy(self, authenticated_page):
        """Q3: Ask about the search strategy architecture."""
        result = _send_chat_and_wait(
            authenticated_page,
            "How does the search strategy engine work? What strategies does it use?",
        )
        assert result["response_text"], "Agent should return a response"
        assert result["latency_s"] < 180, f"Response took {result['latency_s']:.1f}s, too slow"

    @pytest.mark.skipif(
        os.getenv("SKIP_UI_TESTS", "0") == "1",
        reason="UI tests disabled via SKIP_UI_TESTS=1",
    )
    def test_q4_code_callers(self, authenticated_page):
        """Q4: Ask who calls a function."""
        result = _send_chat_and_wait(
            authenticated_page,
            "Which files import or call find_symbol?",
        )
        assert result["response_text"], "Agent should return a response"
        assert result["latency_s"] < 180, f"Response took {result['latency_s']:.1f}s, too slow"

    @pytest.mark.skipif(
        os.getenv("SKIP_UI_TESTS", "0") == "1",
        reason="UI tests disabled via SKIP_UI_TESTS=1",
    )
    def test_q5_repo_structure(self, authenticated_page):
        """Q5: Ask about codebase structure (tests repo-context awareness)."""
        result = _send_chat_and_wait(
            authenticated_page,
            "What is the overall structure of the backend codebase? List the main modules.",
        )
        assert result["response_text"], "Agent should return a response"
        assert result["latency_s"] < 180, f"Response took {result['latency_s']:.1f}s, too slow"


class TestUIChatBehavior:
    """UI behavior tests: clear, error, model selector."""

    @pytest.mark.skipif(
        os.getenv("SKIP_UI_TESTS", "0") == "1",
        reason="UI tests disabled via SKIP_UI_TESTS=1",
    )
    def test_clear_chat(self, authenticated_page):
        """Verify clear button resets chat."""
        page = authenticated_page
        clear_btn = page.locator("#chat-clear")
        if clear_btn.count() > 0 and clear_btn.first.is_visible():
            # Auto-accept the confirm dialog
            page.on("dialog", lambda dialog: dialog.accept())
            clear_btn.first.click()
            page.wait_for_timeout(1000)
            # After clear, should have at most 1 system message
            msgs = page.locator(".chat-msg, .chat-message").count()
            assert msgs <= 2, f"Expected ≤2 messages after clear, got {msgs}"

    @pytest.mark.skipif(
        os.getenv("SKIP_UI_TESTS", "0") == "1",
        reason="UI tests disabled via SKIP_UI_TESTS=1",
    )
    def test_model_selector_visible(self, authenticated_page):
        """Verify model selector dropdown is present."""
        page = authenticated_page
        selector = page.locator("#chat-model-select")
        assert selector.count() > 0, "Model selector should exist"
        # Should have at least one option
        options = selector.locator("option")
        assert options.count() >= 1, "Model selector should have at least one option"

    @pytest.mark.skipif(
        os.getenv("SKIP_UI_TESTS", "0") == "1",
        reason="UI tests disabled via SKIP_UI_TESTS=1",
    )
    def test_expand_collapse(self, authenticated_page):
        """Verify expand/collapse button works."""
        page = authenticated_page
        expand_btn = page.locator("#chat-expand")
        if expand_btn.count() > 0 and expand_btn.first.is_visible():
            expand_btn.first.click()
            page.wait_for_timeout(300)
            # Panel should still be visible
            panel = page.locator("#chat-panel")
            assert panel.is_visible(), "Chat panel should remain visible after expand"
