# Context Pack Lite — B01: Agentic MVP Factory

## What we're building

A CLI-first "council runner" that orchestrates multi-model planning debates. Three models draft proposals, critique each other's work, then a chair model synthesizes a final plan. A human reviews and approves before artifacts are committed to a target repository.

## Key constraints

- **OpenRouter only** — no direct API keys for individual providers
- **Postgres persistence** — must work with Railway
- **No secrets in repo** — environment variables only
- **Single approval checkpoint** — no nested approval loops
- **CLI-only** — no web/mobile UI for V0

## Research links

| ID | Question | Key Finding |
|----|----------|-------------|
| RQ1 | LangGraph state management | Use TypedDict for Studio compatibility ([docs](https://langchain-ai.github.io/langgraph/concepts/low_level/)) |
| RQ2 | OpenRouter rate limits | Use exponential backoff ([docs](https://openrouter.ai/docs)) |
| RQ3 | HITL with LangGraph | Checkpoints enable pause/resume ([docs](https://langchain-ai.github.io/langgraph/concepts/persistence/)) |

## Assumptions

- TypedDict is required for LangGraph Studio visualization
- OpenRouter handles 3 parallel model calls without issues
- LangGraph checkpoints provide sufficient state for HITL
- Railway free tier Postgres works for development

## Unknowns (carry forward)

- Exact rate limits for OpenRouter free tier
- LangSmith trace retention policy
- Maximum synthesis length before context issues
- Rejected run handling (child run vs. fresh restart)

