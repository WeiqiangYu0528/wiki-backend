# Interruption and Human Approval Flow

## Overview

Hermes treats interruption and approval as shell mechanics, not as ordinary model turns. The core idea is simple: when a session is busy or a command is risky, the runtime must let the user regain control without corrupting the current turn. That control can take different forms, but the split is always the same. Hermes keeps one shared policy engine for detecting dangerous actions and recognizing control commands, then lets the active surface carry the actual interaction.

That distinction is what keeps the runtime coherent. A tool can be blocked for approval without becoming a malformed assistant turn. A new user message can interrupt work without being lost. A `/stop` or `/reset` command can preempt the current turn without being replayed later as normal prompt text. The surface-specific transport changes, but the invariants stay the same.

## Shared Model

Think about the flow in two layers:

1. The shared policy layer decides what the runtime should do.
   It detects dangerous commands, recognizes busy-session controls, and determines whether something should be queued, interrupted, approved, or denied.

2. The active surface decides how to ask or respond.
   CLI, gateway, and ACP all carry the same decision, but each one uses a different transport for human input and output.

That split is the reason this concept page sits between [Gateway Runtime](../entities/gateway-runtime.md), [ACP Adapter](../entities/acp-adapter.md), and [Terminal and Execution Environments](../entities/terminal-and-execution-environments.md). The policy is shared; the transport is not.

## Shared Policy Versus Surface Transport

| Layer | Owns | Does not own |
| --- | --- | --- |
| Shared policy engine | Dangerous-command detection, approval state, interrupt intent, queue intent, and the rules that decide whether a command may proceed | UI prompts, message delivery, JSON-RPC permissions, or shell-specific text rendering |
| CLI transport | Direct blocking prompt and local terminal response | Gateway message routing or ACP permission RPCs |
| Gateway transport | In-band `/approve` and `/deny`, session queueing, running-session guards, and message-based control flow | Terminal execution transport or editor permission dialogs |
| ACP transport | Permission requests and editor-visible approval buttons or choices | Shell prompt semantics or gateway queue policy |

The boundary matters because the same policy event can arrive through very different surfaces. Hermes wants one decision model, not three separate ones.

## Mechanism

The flow has two related but distinct branches: interruption and approval. They share the same architectural rule, but they enter the runtime at different points.

### Interruption

1. A session is already running.
   The agent loop may be waiting on the model, waiting on a tool, or blocked on approval.

2. A new event arrives for that session.
   In the CLI this might be a fresh line of text. In the gateway it may be a platform message, a slash command, or a control action. In ACP it may be a new editor prompt or a cancel request.

3. The active surface applies its busy-session mechanics.
   The gateway can queue the message, interrupt the current turn, or route a control command directly. CLI can stop the current task locally. ACP can cancel the active run from the editor session.

4. The agent loop observes the interrupt.
   Hermes does not treat the interruption as a normal assistant reply. It is a control signal that causes the in-flight provider call or long-running tool to stop making progress when possible.

5. The runtime decides what survives.
   A queued message becomes the next turn. A stop request clears the session lock. A reset request starts fresh. Interrupted assistant output is not treated as a user-visible conversational fact.

This is why interrupts are not ordinary turns. They are control signals that protect session integrity.

### Approval

1. A tool call reaches an approval-sensitive path.
   The terminal tool is the clearest example, but the principle is general: a command can be visible to the model without being allowed to run yet.

2. The shared policy engine evaluates the command.
   `tools/approval.py` normalizes the command, checks dangerous patterns, and consults per-session approval state. It knows whether the command is safe, already allowed, allowed for the session, or blocked.

3. The active surface carries the decision to the human.
   CLI shows a direct prompt, the gateway sends an in-band approval request or waits for `/approve` and `/deny`, and ACP converts the decision into a permission request in the editor.

4. The approval result returns to the blocked execution path.
   A positive decision lets the tool continue. A deny decision returns a blocked result. A session-scoped or permanent approval updates the policy state so later commands can reuse it.

5. The tool output is reinjected into the agent loop.
   The model sees the approved side effect or the blocked result on the next turn, which keeps the conversation consistent with what actually happened.

Approval is not a detached UX feature. It is part of the execution path, and the conversation only continues after the policy gate has been satisfied.

## Busy-Session Controls

Busy sessions need their own branch because control commands are not the same thing as ordinary user messages.

The gateway makes this explicit:

1. `/status` reports live progress without disturbing the running turn.
2. `/stop` force-clears a stuck session and releases the lock.
3. `/new` and `/reset` interrupt the run, clear stale pending input, and start fresh.
4. `/queue` appends work for the next turn without interrupting the current one.
5. `/approve` and `/deny` bypass normal message handling because they are responses to a blocked approval wait.

The key implication is that queueing and bypass are different mechanisms. `Queue` preserves order for later work. Bypass commands preempt the normal path because they are control-plane messages, not user content meant for the model.

## Why The Boundary Exists

Hermes makes interruption and approval shell mechanics for three reasons.

First, the model should not need to know how each surface asks for consent. The model only needs to see the result of the decision.

Second, busy-session control must preserve transcript integrity. If a `/stop` or `/reset` were treated as normal text, it could be replayed later as if the user had asked the model to do something else.

Third, the same policy has to work across surfaces with very different interaction models. The CLI can block on stdin, the gateway cannot, and ACP must translate into editor permissions. If the policy lived in the surface, each surface would drift.

These invariants are the real contract:

- a dangerous command is either approved, denied, or still pending, but never silently executed
- an interrupt either becomes the next turn, cancels the current one, or is discarded as control noise, but never becomes accidental assistant content
- queueing preserves order without forcing an interrupt
- bypass commands preempt the normal path because they are shell controls
- the model sees normalized outcomes, not transport-specific approval machinery

## Step Order Across Surfaces

The same pattern shows up in all three surfaces, but the transport differs.

1. CLI detects a dangerous command or interrupt condition.
   The runtime prompts directly and can continue as soon as the user responds.

2. Gateway detects the same condition in a message-driven session.
   `gateway/run.py` keeps running-session guards, queues pending follow-ups, and exposes `/approve`, `/deny`, `/stop`, `/new`, `/reset`, and `/queue` as shell commands.

3. ACP detects the same condition inside an editor session.
   `acp_adapter/permissions.py` converts Hermes approval needs into ACP permission requests, while `acp_adapter/server.py` and session state bridge the active run.

4. The blocked operation resumes or aborts.
   The shared approval state is updated, the interrupt flag is cleared or preserved as needed, and the agent loop gets the final result on the next step.

This order is why Hermes feels interactive instead of brittle. A user can interrupt a long session, approve a risky command, or queue follow-up work without collapsing the runtime into a bad state.

## Source Evidence

The implementation evidence for this pattern comes from:

- `hermes-agent/tools/approval.py` for dangerous-command detection, approval state, and per-session approval queues
- `hermes-agent/tools/interrupt.py` for the shared interrupt signal used by long-running tools
- `hermes-agent/gateway/run.py` for running-session guards, `/approve` and `/deny`, `/stop`, `/new`, `/reset`, and `/queue`
- `hermes-agent/acp_adapter/permissions.py` for ACP permission transport
- [Gateway Message to Agent Reply Flow](../syntheses/gateway-message-to-agent-reply-flow.md) for the gateway-side message/queue/bypass flow
- [Tool Call Execution and Approval Pipeline](../syntheses/tool-call-execution-and-approval-pipeline.md) for the tool-call approval path
- `hermes-agent/website/docs/developer-guide/gateway-internals.md` and `hermes-agent/website/docs/developer-guide/agent-loop.md` for the maintainer-facing explanation of the same boundary

## See Also

- [Gateway Runtime](../entities/gateway-runtime.md)
- [CLI Runtime](../entities/cli-runtime.md)
- [ACP Adapter](../entities/acp-adapter.md)
- [Terminal and Execution Environments](../entities/terminal-and-execution-environments.md)
- [Gateway Message to Agent Reply Flow](../syntheses/gateway-message-to-agent-reply-flow.md)
- [Tool Call Execution and Approval Pipeline](../syntheses/tool-call-execution-and-approval-pipeline.md)
- [Interruption and Human Approval Flow](../concepts/interruption-and-human-approval-flow.md)
