# Chatbox Widget Redesign — Indigo Ink

**Date:** 2026-04-11  
**Status:** Approved  
**Files:** `docs/stylesheets/chatbox.css`, `docs/javascripts/chatbox.js`

---

## Aesthetic Direction

**Name:** Indigo Ink (dark) / Ink & Paper Studio (light)  
**Source:** Matches `/Users/weiqiangyu/Downloads/notes` design system exactly.  
**Feel:** Warm, comfortable, artistic — not techy or sci-fi.

---

## Color Tokens

### Dark Mode (`[data-md-color-scheme="slate"]`)
| Token | Value | Use |
|---|---|---|
| bg-panel | `#1a1520` | Panel background |
| bg-messages | `#130f1a` | Message area |
| bg-input | `#130f1a` | Input wrap |
| border | `#312a38` | All borders |
| accent | `#a68dcf` | Soft lavender — FAB, send btn, agent icon |
| accent-soft | `rgba(166,141,207,0.10)` | Hover/wash states |
| user-bg | `#2d2040 → #241830` (gradient) | User bubble bg |
| user-border | `#3a3145` | User bubble border |
| user-accent | `#a68dcf → #7c5cbf` | Right-strip on user bubble |
| text-primary | `#ebe5d8` | Main text (warm parchment) |
| text-dim | `#8a8078` | Muted labels, placeholders |
| text-body | `#d4cdc2` | Message body text |
| chip-bg | `rgba(166,141,207,0.10)` | Source citation background |
| chip-border | `rgba(166,141,207,0.22)` | Citation chip border |
| chip-text | `#a68dcf` | Citation chip text |

### Light Mode (`[data-md-color-scheme="default"]`)
| Token | Value | Use |
|---|---|---|
| bg-panel | `#faf9f5` | Panel background |
| bg-messages | `#f5f4ed` | Message area |
| border | `#e2dbd2` | All borders |
| accent | `#5c4d8a` | Muted purple — FAB, send, agent icon |
| accent-soft | `rgba(92,77,138,0.08)` | Wash/hover |
| user-bg | `#ede8f5 → #e6dff5` (gradient) | User bubble bg |
| user-text | `#3a2d5c` | User bubble text |
| user-accent | `#5c4d8a → #7a65aa` | Right-strip on user bubble |
| text-primary | `#1c1814` | Main text (warm near-black) |
| text-dim | `#7d756b` | Muted labels |
| text-body | `#3f352c` | Message body text |
| chip-bg | `rgba(92,77,138,0.08)` | Citation chip bg |
| chip-text | `#5c4d8a` | Citation chip text |

---

## Typography

| Role | Font | Size | Weight |
|---|---|---|---|
| Panel title "Axiom" | Playfair Display | 16px | 700 |
| Panel subtitle | Inter | 10px | 400 |
| Message body | Inter | 13.5px | 300 |
| Muted labels, model selector | Inter / JetBrains Mono | 10px | 400 |
| Code blocks | JetBrains Mono | 11.5px | 400 |

---

## Component Specs

### Panel
- Width: 420px desktop, 100% mobile (≤520px)
- Height: 620px desktop, 82vh mobile
- Border-radius: 16px
- Border: 1px solid border-color (no bold accent strip — clean)
- Shadow: multi-layer, warm dark
- Grain texture overlay (SVG fractal noise, 2.5% opacity)

### Header
- Gradient bg: subtle warm tint on left
- Avatar orb: 34px circle, accent gradient, star glyph
- Title: Playfair Display "Axiom"
- Subtitle: Inter small-caps feel
- Close: 26px circle button

### Message Bubbles
- Agent: soft rounded `4px 14px 14px 14px`, bg = card color, left side has agent icon (26px accent circle)
- User: `14px 14px 4px 14px` (tail bottom-right), gradient bg, **3px accent gradient strip on right edge**
- Padding: 11px 14px — generous
- Line-height: 1.65

### FAB
- 50px circle, accent gradient fill
- Soft pulse ring (single, 25% opacity)
- Spring-bounce hover

### Source Citations
- Rounded-full chips (matching notes tag style)
- Accent-wash bg, accent text
- "Sources" label in tiny uppercase

### Input Area
- Pill-shaped input wrap (rounded-full)
- No prefix symbol — clean
- Send: 32px circle, accent gradient
- Model selector: small pill with JetBrains Mono font

### Animations
- Panel open: fade-up + scale from 0.96 (matching notes `scale-in`)
- Messages: fade-up stagger
- Thinking indicator: 3-dot blink (matching notes animation rhythm)
- FAB hover: spring scale (cubic-bezier 0.34, 1.56, 0.64, 1)

---

## Functional Requirements (unchanged)
- Auth flow: username, password, TOTP → JWT in localStorage
- Streaming responses (token-by-token rendering with marked.js)
- Tool-use indicators during agent thinking
- Source citation chips with wiki URL links
- Model selector: GPT-4o, DeepSeek Chat, Qwen Max
- Enter-key send, auto-scroll, session history
- Dark/light mode adapts to MkDocs Material theme toggle
- Mobile responsive with safe-area inset support
