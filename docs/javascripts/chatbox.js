document.addEventListener("DOMContentLoaded", function () {
  // --- INJECT HTML ---
  const widgetHtml = `
    <div id="mkdocs-ai-chat-widget">
      <!-- Chat Panel -->
      <div id="chat-panel">
        <div class="chat-header">
          <div class="chat-header-inner">
            <div class="chat-header-orb">✦</div>
            <div class="chat-header-text">
              <div class="chat-header-title">Axiom</div>
              <div class="chat-header-sub">Knowledge Intelligence System</div>
            </div>
          </div>
          <div class="chat-header-actions">
            <button class="chat-expand-btn" id="chat-expand" title="Expand">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/>
                <line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>
              </svg>
            </button>
            <button class="chat-close-btn" id="chat-close" title="Close">✕</button>
          </div>
        </div>

        <!-- Auth View -->
        <div id="chat-auth-view">
          <h3 class="chat-auth-title">Authentication Required</h3>
          <p class="chat-auth-sub">Sign in to access the knowledge intelligence system.</p>
          <input type="text"     id="auth-user" class="chat-input-field" placeholder="Username"              autocomplete="username" />
          <input type="password" id="auth-pass" class="chat-input-field" placeholder="Password"              autocomplete="current-password" />
          <input type="text"     id="auth-mfa"  class="chat-input-field" placeholder="6-digit MFA code"     autocomplete="one-time-code" />
          <button id="auth-btn" class="chat-btn">Sign in</button>
          <div id="auth-loader" class="loader"></div>
          <div id="auth-error"></div>
        </div>

        <!-- Main Chat Body -->
        <div class="chat-body" id="chat-body" style="display:none;"></div>

        <!-- Input Area -->
        <div id="chat-input-area" style="flex-direction: column; width: 100%;">
          <div class="model-select-wrapper">
            <select id="chat-model-select" class="model-select">
              <option value="openai">⬡ GPT-4o</option>
              <option value="deepseek" selected>⬡ DeepSeek Chat</option>
              <option value="qwen">⬡ Qwen Plus</option>
            </select>
          </div>
          <div class="chat-footer">
            <div class="chat-input-wrap">
              <input type="text" id="chat-input" placeholder="Ask anything about the wikis…" />
            </div>
            <button id="chat-send" title="Send">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"/>
                <polygon points="22 2 15 22 11 13 2 9 22 2"/>
              </svg>
            </button>
            <button id="chat-stop" title="Stop generation" style="display:none;">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                <rect x="4" y="4" width="16" height="16" rx="2"/>
              </svg>
            </button>
          </div>
        </div>
      </div>

      <!-- FAB -->
      <button id="chat-fab" title="Open Axiom">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          <circle cx="9"  cy="10" r="0.9" fill="currentColor" stroke="none"/>
          <circle cx="12" cy="10" r="0.9" fill="currentColor" stroke="none"/>
          <circle cx="15" cy="10" r="0.9" fill="currentColor" stroke="none"/>
        </svg>
      </button>
    </div>
  `;

  document.body.insertAdjacentHTML('beforeend', widgetHtml);

  // --- STATE ---
  const fab       = document.getElementById("chat-fab");
  const panel     = document.getElementById("chat-panel");
  const closeBtn  = document.getElementById("chat-close");

  const authView  = document.getElementById("chat-auth-view");
  const chatBody  = document.getElementById("chat-body");
  const inputArea = document.getElementById("chat-input-area");

  // chatHistory holds the full conversation as [{role, content}] pairs.
  // It is appended to only after a complete round-trip (user msg + agent reply).
  let chatHistory = [];
  const BACKEND_URL = "http://localhost:8001";

  // --- TOGGLE LOGIC ---
  let isExpanded = false;

  // Expand / shrink icons
  const expandIcon = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>`;
  const shrinkIcon = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="10" y1="14" x2="3" y2="21"/><line x1="21" y1="3" x2="14" y2="10"/></svg>`;

  const expandBtn = document.getElementById("chat-expand");

  expandBtn.addEventListener("click", () => {
    isExpanded = !isExpanded;
    panel.classList.toggle("chat-panel--expanded", isExpanded);
    expandBtn.innerHTML = isExpanded ? shrinkIcon : expandIcon;
    expandBtn.title     = isExpanded ? "Shrink" : "Expand";
  });

  fab.addEventListener("click", () => {
    panel.style.display = "flex";
    fab.style.display   = "none";
    checkAuth();
  });

  closeBtn.addEventListener("click", () => {
    panel.style.display = "none";
    fab.style.display   = "flex";
  });

  // --- AUTH LOGIC ---
  function checkAuth() {
    const token = localStorage.getItem("mkdocs_ai_jwt");
    if (token) {
      showChatView();
    } else {
      showAuthView();
    }
  }

  function showAuthView() {
    authView.style.display  = "flex";
    chatBody.style.display  = "none";
    inputArea.style.display = "none";
  }

  function showChatView() {
    authView.style.display  = "none";
    chatBody.style.display  = "flex";
    inputArea.style.display = "flex";
    if (chatHistory.length === 0 && chatBody.children.length === 0) {
      const greeting = "Hi! I can answer questions about any of the wikis in this documentation site. What would you like to know?";
      appendMessage("agent", greeting);
      chatHistory.push({ role: "agent", content: greeting });
    }
  }

  document.getElementById("auth-btn").addEventListener("click", async () => {
    const user    = document.getElementById("auth-user").value;
    const pass    = document.getElementById("auth-pass").value;
    const mfa     = document.getElementById("auth-mfa").value;
    const loader  = document.getElementById("auth-loader");
    const errorEl = document.getElementById("auth-error");

    errorEl.style.display = "none";
    loader.style.display  = "block";

    try {
      const res = await fetch(`${BACKEND_URL}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: user, password: pass, totp: mfa })
      });

      const data = await res.json();
      if (res.ok && data.access_token) {
        localStorage.setItem("mkdocs_ai_jwt", data.access_token);
        showChatView();
      } else {
        errorEl.textContent    = data.detail || "Login failed.";
        errorEl.style.display  = "block";
      }
    } catch (e) {
      errorEl.textContent   = "Cannot connect to Backend Server.";
      errorEl.style.display = "block";
    } finally {
      loader.style.display = "none";
    }
  });

  // --- CHAT HELPERS ---

  /** Append a fully-formed message bubble to the chat body. */
  function appendMessage(role, text) {
    const div = createMessageBubble(role);
    if (window.marked && role === "agent") {
      div.querySelector(".msg-content").innerHTML = marked.parse(text);
    } else {
      div.querySelector(".msg-content").innerText = text;
    }
    chatBody.appendChild(div);
    chatBody.scrollTop = chatBody.scrollHeight;
    return div;
  }

  /** Create an empty message bubble.
   *  Agent:  .msg-agent > [ .msg-agent-icon | .msg-agent-body > [ .msg-content, .msg-citations ] ]
   *  User:   .msg-user  > .msg-content
   *  querySelector(".msg-content") and querySelector(".msg-citations") work on both. */
  function createMessageBubble(role) {
    const outer = document.createElement("div");
    outer.classList.add("chat-msg", role === "user" ? "msg-user" : "msg-agent");

    if (role === "agent") {
      // Avatar icon
      const icon = document.createElement("div");
      icon.classList.add("msg-agent-icon");
      icon.textContent = "✦";
      outer.appendChild(icon);

      // Body wrapper (bubble card)
      const body = document.createElement("div");
      body.classList.add("msg-agent-body");

      const content = document.createElement("div");
      content.classList.add("msg-content");
      body.appendChild(content);

      const citations = document.createElement("div");
      citations.classList.add("msg-citations");
      body.appendChild(citations);

      outer.appendChild(body);
    } else {
      const content = document.createElement("div");
      content.classList.add("msg-content");
      outer.appendChild(content);
    }

    return outer;
  }

  /** Show a transient tool-use indicator inside an agent bubble. */
  function showToolIndicator(bubble, toolName) {
    const content = bubble.querySelector(".msg-content");
    // Only show indicator if no real tokens have arrived yet
    if (!bubble.dataset.hasTokens) {
      const label = toolName === "read_workspace_file"  ? "Reading file…"
                  : toolName === "read_source_file"     ? "Reading source code…"
                  : toolName === "search_knowledge_base" ? "Searching knowledge base…"
                  : toolName === "list_wiki_pages"        ? "Listing pages…"
                  : toolName === "propose_doc_change"     ? "Drafting documentation changes…"
                  : `${toolName}…`;
      content.innerHTML = `<span class="tool-indicator">${label}</span>`;
    }
  }

  /** Render source citation chips below an agent message bubble. */
  function renderCitations(bubble, sources) {
    const citationsEl = bubble.querySelector(".msg-citations");
    if (!citationsEl || !sources || sources.length === 0) return;

    citationsEl.innerHTML = "";
    const label = document.createElement("span");
    label.className   = "citations-label";
    label.textContent = "Sources";
    citationsEl.appendChild(label);

    sources.forEach(filePath => {
      const chip       = document.createElement("a");
      chip.className   = "source-chip";
      chip.textContent = filePath.split("/").pop().replace(".md", "");
      chip.title       = filePath;
      // Map docs/namespace-wiki/section/page.md → /namespace-wiki/section/page/
      chip.href        = filePathToWikiUrl(filePath);
      chip.target      = "_blank";
      citationsEl.appendChild(chip);
    });
  }

  /** Convert a docs-relative file path to a MkDocs URL. */
  function filePathToWikiUrl(filePath) {
    // e.g. docs/claude-code/entities/tool-system.md → /claude-code/entities/tool-system/
    const withoutDocs = filePath.replace(/^docs\//, "");
    const withoutExt  = withoutDocs.replace(/\.md$/, "");
    return `/${withoutExt}/`;
  }

  /** Render a proposal card with diff preview and Approve/Reject buttons. */
  function renderProposal(bubble, proposal) {
    const card = document.createElement("div");
    card.className = "proposal-card";
    card.dataset.proposalId = proposal.proposal_id;

    const header = document.createElement("div");
    header.className = "proposal-header";
    header.innerHTML = `<span class="proposal-icon">📋</span> Documentation Change Proposal`;
    card.appendChild(header);

    const summary = document.createElement("div");
    summary.className = "proposal-summary";
    summary.textContent = proposal.summary;
    card.appendChild(summary);

    proposal.files.forEach(f => {
      const fileLabel = document.createElement("div");
      fileLabel.className = "proposal-file-label";
      fileLabel.textContent = f.path;
      card.appendChild(fileLabel);

      const diffBlock = document.createElement("pre");
      diffBlock.className = "proposal-diff";
      diffBlock.textContent = f.diff || "(new file)";
      card.appendChild(diffBlock);
    });

    const actions = document.createElement("div");
    actions.className = "proposal-actions";

    const approveBtn = document.createElement("button");
    approveBtn.className = "proposal-btn proposal-btn-approve";
    approveBtn.innerHTML = "✓ Approve &amp; Create PR";
    approveBtn.addEventListener("click", () =>
      handleProposalAction(proposal.proposal_id, "approve", card)
    );

    const rejectBtn = document.createElement("button");
    rejectBtn.className = "proposal-btn proposal-btn-reject";
    rejectBtn.innerHTML = "✕ Reject";
    rejectBtn.addEventListener("click", () =>
      handleProposalAction(proposal.proposal_id, "reject", card)
    );

    actions.appendChild(approveBtn);
    actions.appendChild(rejectBtn);
    card.appendChild(actions);

    const body = bubble.querySelector(".msg-agent-body");
    if (body) {
      body.appendChild(card);
    } else {
      bubble.appendChild(card);
    }
    chatBody.scrollTop = chatBody.scrollHeight;
  }

  /** Handle Approve or Reject button click. */
  async function handleProposalAction(proposalId, action, card) {
    const token = localStorage.getItem("mkdocs_ai_jwt");
    const btns = card.querySelectorAll(".proposal-btn");
    btns.forEach(b => { b.disabled = true; b.style.opacity = "0.5"; });

    try {
      const res = await fetch(`${BACKEND_URL}/proposals/${proposalId}/${action}`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      });

      if (res.status === 401) {
        localStorage.removeItem("mkdocs_ai_jwt");
        showAuthView();
        return;
      }

      const data = await res.json();
      const statusEl = document.createElement("div");

      if (action === "approve" && res.ok && data.result) {
        statusEl.className = "proposal-status proposal-status-approved";
        const r = data.result;
        statusEl.innerHTML =
          `<strong>✓ Approved — PR Created</strong><br>` +
          `Branch: <code>${r.branch}</code><br>` +
          `Commit: <code>${(r.commit_sha || "").substring(0, 8)}</code><br>` +
          (r.pr_url && r.pr_url.startsWith("http")
            ? `<a href="${r.pr_url}" target="_blank" rel="noopener">View Pull Request →</a>`
            : `<span>${r.pr_url || ""}</span>`);
      } else if (action === "reject") {
        statusEl.className = "proposal-status proposal-status-rejected";
        statusEl.innerHTML = `<strong>✕ Rejected</strong> — No changes were made.`;
      } else {
        statusEl.className = "proposal-status proposal-status-error";
        statusEl.innerHTML = `<strong>Error:</strong> ${data.detail || JSON.stringify(data)}`;
      }

      const actionsEl = card.querySelector(".proposal-actions");
      if (actionsEl) actionsEl.replaceWith(statusEl);
    } catch (e) {
      console.error("Proposal action failed:", e);
      btns.forEach(b => { b.disabled = false; b.style.opacity = "1"; });
      const errEl = document.createElement("div");
      errEl.className = "proposal-status proposal-status-error";
      errEl.textContent = "Network error — is the backend running?";
      card.appendChild(errEl);
    }
  }

  // --- SEND CHAT (streaming) ---

  let activeAbortController = null;

  const sendBtn = document.getElementById("chat-send");
  const stopBtn = document.getElementById("chat-stop");

  sendBtn.addEventListener("click", sendChat);
  document.getElementById("chat-input").addEventListener("keypress", (e) => {
    if (e.key === "Enter") sendChat();
  });

  stopBtn.addEventListener("click", () => {
    if (activeAbortController) {
      activeAbortController.abort();
    }
  });

  function setStreaming(on) {
    sendBtn.style.display = on ? "none" : "flex";
    stopBtn.style.display = on ? "flex"  : "none";
    document.getElementById("chat-input").disabled = on;
  }

  async function sendChat() {
    const inputField = document.getElementById("chat-input");
    const val = inputField.value.trim();
    if (!val) return;

    inputField.value = "";
    setStreaming(true);

    // Show user message immediately (not yet in chatHistory)
    appendMessage("user", val);

    // Create empty agent bubble for streaming into
    const agentBubble = createMessageBubble("agent");
    agentBubble.querySelector(".msg-content").innerHTML = '<div class="loader" style="display:block;"></div>';
    chatBody.appendChild(agentBubble);
    chatBody.scrollTop = chatBody.scrollHeight;

    const token       = localStorage.getItem("mkdocs_ai_jwt");
    const model       = document.getElementById("chat-model-select").value;
    const pageContext = { title: document.title, url: window.location.href };

    // Create a fresh AbortController for this request
    activeAbortController = new AbortController();
    const { signal } = activeAbortController;

    let fullContent = "";
    let stopped     = false;

    try {
      const res = await fetch(`${BACKEND_URL}/chat/stream`, {
        method: "POST",
        signal,
        headers: {
          "Content-Type":  "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({
          query:        val,
          history:      chatHistory,
          model:        model,
          page_context: pageContext
        })
      });

      if (res.status === 401) {
        localStorage.removeItem("mkdocs_ai_jwt");
        chatHistory        = [];
        chatBody.innerHTML = '';
        showAuthView();
        return;
      }

      let buffer   = "";
      const reader  = res.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.trim()) continue;
          let event;
          try { event = JSON.parse(line); } catch (_) { continue; }

          if (event.type === "token") {
            agentBubble.dataset.hasTokens = "1";
            fullContent += event.content;
            const contentEl = agentBubble.querySelector(".msg-content");
            if (window.marked) {
              contentEl.innerHTML = marked.parse(fullContent);
            } else {
              contentEl.innerText = fullContent;
            }
            chatBody.scrollTop = chatBody.scrollHeight;

          } else if (event.type === "tool_call") {
            showToolIndicator(agentBubble, event.name);

          } else if (event.type === "proposal") {
            renderProposal(agentBubble, event);

          } else if (event.type === "citations") {
            renderCitations(agentBubble, event.sources);

          } else if (event.type === "error") {
            agentBubble.querySelector(".msg-content").innerText = "Error: " + event.detail;
          }
        }
      }

      // Commit both turns to history only after full round-trip
      chatHistory.push({ role: "user",  content: val });
      chatHistory.push({ role: "agent", content: fullContent });

    } catch (e) {
      if (e.name === "AbortError") {
        // User stopped the stream — keep whatever was streamed so far
        stopped = true;
        if (fullContent) {
          // Mark partial response as stopped
          const contentEl = agentBubble.querySelector(".msg-content");
          const stopBadge = document.createElement("span");
          stopBadge.className   = "stop-badge";
          stopBadge.textContent = " [stopped]";
          contentEl.appendChild(stopBadge);
          // Still commit what we have to history
          chatHistory.push({ role: "user",  content: val });
          chatHistory.push({ role: "agent", content: fullContent });
        } else {
          // Nothing streamed yet — remove the empty bubble
          agentBubble.remove();
        }
      } else {
        agentBubble.querySelector(".msg-content").innerText = "Network error. Is the backend running?";
      }
    } finally {
      activeAbortController = null;
      setStreaming(false);
      document.getElementById("chat-input").focus();
    }
  }
});
