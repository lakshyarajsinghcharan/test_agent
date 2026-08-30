# test_agent — AI Social Content Pipeline

A 5-agent AI system that takes a product name and produces a brand-checked,
ready-to-schedule Instagram post — caption, visual direction, and a pass/fail
brand review — end to end, with zero API cost. Built on
[CrewAI](https://github.com/crewAIInc/crewAI) running entirely on local
[Ollama](https://ollama.com/) models, no cloud LLM billing required for the
agents themselves.

Read **[CASE_STUDY.md](CASE_STUDY.md)** for the real engineering story: five
production-grade bugs this pipeline hit during testing, how each one was
diagnosed, and how it was fixed. That's the part worth reading if you want to
see the actual debugging work, not just the pitch.

## What it does

Give it a product name. It returns either a scheduled calendar entry or a
clear, cited rejection — never a silent failure and never unreviewed content:

```
Input:  "Tesla Model 3"

Output: - Product Name: Tesla Model 3
        - Caption: Need a car that goes the distance & saves the planet?
          The Tesla Model 3 hits 358 miles on one charge...
        - Visual Brief: [detailed shot description tied to the caption's fact]
        - Brand Check Status: PASS
        - Suggested Post Date: TBD
```

If the brand-checker rejects the copy, nothing gets written — the pipeline
returns `NOT SCHEDULED - Brand check failed` with the specific rule violated,
and stops there.

## Architecture

Five agents run in a strict sequential pipeline, each one consuming the prior
agents' real output as context (not just a summary of it):

```
Strategist  →  Copywriter  →  Visual Brief Writer  →  Brand-Checker  →  Scheduler
(theme,        (researches      (translates the         (PASS/FAIL       (writes the
 audience,      the product,     caption into a          verdict,         calendar
 angle)         writes the       concrete shot           citing the       entry, or
                caption)         description)            exact rule)      refuses)
```

- **Strategist** — defines the content theme, target audience, and a specific
  angle from the product name alone.
- **Copywriter** — researches the product via live web search, then writes one
  on-brand Instagram caption grounded in a real fact from the search results.
- **Visual Brief Writer** — turns that caption into a concrete shot
  description a designer or AI image tool could execute without guessing.
- **Brand-Checker** — reads the brand voice guide and issues a PASS/FAIL
  verdict, required to quote the exact rule it's judging against.
- **Scheduler** — on PASS, appends a structured entry to the content calendar;
  on FAIL, writes nothing and reports why.

A deterministic Python guardrail (not an LLM judge) enforces the Scheduler's
output shape, and a purpose-built write tool enforces PASS-only, append-only
writes at the code level — not just by asking the model nicely. Details on
why both exist are in the case study.

## Tech stack

- **[CrewAI](https://github.com/crewAIInc/crewAI)** — multi-agent
  orchestration, JSONC-first crew/task/agent configuration
- **[Ollama](https://ollama.com/)** running `qwen2.5-7b-8k` locally — every
  agent call is a local inference call, not a metered API request
- **[Serper](https://serper.dev/)** — the Copywriter's only external
  dependency, for live product research
- **Python** — custom tools, hooks, and a deterministic guardrail
- **[Claude Code](https://claude.com/claude-code)** — used throughout
  development for debugging, source-level root-causing, and automated
  regression testing (results described in the case study)

## Project structure

```
crew.jsonc          — crew, task, and pipeline definition
agents/              — one JSONC file per agent (role, goal, backstory, LLM, limits)
tools/               — custom Python tools (e.g. the hardened calendar writer)
guardrails/          — deterministic Python guardrails (not LLM judges)
hooks/               — before-kickoff callbacks (calendar injection, maintenance)
brand_voice.md       — the brand rules the Brand-Checker judges against
content_calendar.md  — the running output — real, passing entries land here
```

## Running it

```bash
crewai run
```

You'll be prompted for `product_name`. Requires a local Ollama instance
running the configured model and a `SERPER_API_KEY` set in `.env`.

> **Note:** `custom:<name>` tool references execute `tools/<name>.py` as local
> Python code when the crew loads. Only run crew projects from sources you
> trust.
