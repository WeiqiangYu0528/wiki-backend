# Search Strategy & Code Search

## Overview
The agent uses a multi-tier hybrid search strategy combining lexical (ripgrep), semantic (ChromaDB), and keyword (Meilisearch) search to find both documentation and source code.

## Query Classification
Every query is classified by `classify_query()` in `backend/search/orchestrator.py`:
- **symbol**: Exact code identifiers → extracted and searched directly
- **definition**: "Where is X defined?" queries
- **reference**: "Who calls X?" queries  
- **conceptual**: Broad documentation questions

Symbol extraction handles natural language wrappers like "Explain startMdmRawRead()" → extracts `startMdmRawRead`.

## Search Tools Available to Agent
| Tool | Purpose | When to Use |
|------|---------|-------------|
| `find_symbol` | Exact symbol lookup by name | Known function/class name |
| `smart_search` | Hybrid search across wiki + code | General queries |
| `read_code_section` | Read specific lines/symbols from a file | After finding a file |

## Strategy Escalation
The `SearchStrategyEngine` in `backend/search/strategy.py` tracks attempts per request and escalates:

1. **symbol_exact** — Direct symbol lookup (cheapest, most precise)
2. **lexical_code** — Ripgrep search on source code
3. **semantic_code** — ChromaDB vector similarity on code embeddings
4. **lexical_broad** — Ripgrep across all files including docs
5. **semantic_broad** — Vector similarity across all collections

After 3 consecutive failures at any tier, the engine escalates to the next tier. After all tiers are exhausted, the agent receives an explicit "⚠️ All search strategies exhausted" message.

## Loop Prevention
- `recursion_limit=25` on the LangGraph agent prevents infinite tool loops
- The strategy engine tracks all attempts and appends hints to tool output
- Each request gets a fresh strategy engine via `contextvars` (thread-safe)
- On exhaustion, the agent is told to summarize what it found

## Repo Targeting
`RepoRegistry.target()` returns `(repos, confidence)`:
- **high**: URL/namespace matches exactly → search that repo only
- **medium**: Partial match → search top candidates in order  
- **low**: No clear match → search up to 3 repos, explain ambiguity

## Lexical Search Improvements
- Removed `--fixed-strings` flag for regex matching
- Added definition boost: `def/class/function/interface` lines score higher
- CamelCase expansion: `startMdmRawRead` also searches `start_mdm_raw_read`
- Pattern building for better ripgrep matching
