# Case Study: Debugging a Multi-Agent AI Pipeline

This pipeline runs five AI agents in sequence, entirely on a local 7B model
(`qwen2.5-7b-8k` via Ollama) instead of a hosted API. That choice — small
local model, no cloud LLM cost — makes the system fast and free to run, but
it also makes every weak assumption in the design visible almost immediately.
A 7B model has none of the slack a frontier model has to paper over an
ambiguous instruction or a leaky abstraction.

What follows are five real bugs hit while building and testing this pipeline,
each one diagnosed from actual failing runs, not guessed at. For each: what
broke, how it was found, and what actually fixed it.

---

## 1. Memory caused cross-product contamination

**What broke.** CrewAI's built-in memory system is crew-wide, not scoped per
product. A run for one product could recall — and act on — memories saved
during a run for a completely different product. Confirmed live: a Nutella
run's own search query came back contaminated with "RTX 5060" facts pulled in
from an earlier tech-product run, before any search had even happened. A
separate Nike run produced a visual brief whose primary subject was a snack,
with iPhone button names and an unrelated hashtag folded in.

**How it was diagnosed.** By reading the actual generated search queries and
outputs against what the product actually was. The Nutella run's search query
literally contained "NVIDIA GeForce RTX 5060" — a GPU, for a hazelnut spread.
That's not a subtle bug; it's the model treating stale memory as ground truth
about the current product.

**How it was fixed.** The first pass was mitigation: a before-kickoff hook
that wiped memory whenever the incoming product name differed from the last
run's, so at least cross-product bleed couldn't happen mid-session. That
worked, but it was a patch on a structural problem — see bug #5 for why the
real fix ended up being to disable memory entirely.

---

## 2. A tool call could execute before the guardrail got a chance to reject it

**What broke.** The Scheduler agent has a guardrail that checks its *final
answer text* for a valid shape. But guardrails in CrewAI only see the final
text — they have no visibility into tool calls the model already made while
generating that text. In one live run, the Brand-Checker returned FAIL, but
the Scheduler still called the calendar-write tool with a fully-formed entry
(one that self-contradictorily included `Brand Check Status: FAIL` inside
it) *before* producing its correct final answer of `NOT SCHEDULED`. The
guardrail passed the final text — because the final text was fine — while the
corrupted write had already landed on disk.

**How it was diagnosed.** By comparing the file that got written against what
the guardrail actually validates. The guardrail was checking the right thing;
it was checking it in the wrong place. The write had already happened by the
time there was anything to check.

**How it was fixed.** Moved the enforcement from "ask the guardrail to judge
the final text" to "make the tool itself refuse the write." The calendar
writer tool now inspects the `Brand Check Status` field in whatever content
it's asked to write and hard-refuses anything that isn't literally `PASS`,
regardless of what the model's subsequent final answer says. The lesson: a
guardrail on generated text can't protect against a side effect the model
already triggered on the way there — the enforcement has to live at the
action itself.

---

## 3. Orphaned Ollama worker processes leaked RAM across restarts

**What broke.** During repeated local-model testing across many product
categories, available system RAM quietly collapsed — down to 2.84 GB free out
of 31 GB — eventually causing process kills mid-run.

**How it was diagnosed.** `ollama ps` reported nothing unusual — it only
lists currently *loaded* models, not worker processes. Checking the raw
Windows process list (`tasklist`) told the real story: killing the visible
`ollama.exe` / `ollama app.exe` processes between runs was leaving orphaned
`llama-server.exe` child processes running invisibly in the background, each
one still holding 1–3 GB of RAM. Over many restarts across a long testing
session, those orphans accumulated silently — invisible to the normal Ollama
tooling because they'd already detached from their parent.

**How it was fixed.** Restart logic now explicitly kills `llama-server.exe`
processes by name, not just the parent `ollama` process — killing the parent
doesn't guarantee its children go with it. Free RAM recovered to 15+ GB
immediately after. The lesson: when a tool's own status command says
everything is fine, that's a claim about what the tool is tracking, not a
guarantee about what's actually running.

---

## 4. An agent got stuck in an infinite save-then-search loop

**What broke.** With crew memory enabled, CrewAI automatically injects
`Search memory` / `Save to memory` tools into every agent — not opt-in, not
configurable per task. Without a hard cap on tool-call iterations, one agent
got stuck looping `save → search → save` on the same content, over 100 tool
calls deep in a single task, never converging on an answer.

**How it was diagnosed.** From the crew's own execution log: the same
save/search pair repeating with near-identical arguments, well past any
point a real reasoning process would still be making progress.

**How it was fixed.** Two layers. Immediately: a hard `max_iter` cap (6) and
a wall-clock `max_execution_time` (300s) on every agent, so a stuck loop fails
fast and loud instead of hanging indefinitely — a genuine safety net, still in
place today. Structurally: once memory was disabled entirely (bug #5), the
memory tools that caused the loop stopped being injected at all, which
verified — via CrewAI's own tool-resolution code, not just observed behavior
— that the loop's actual precondition was gone.

---

## 5. Prompt-level bans failed because contaminated memory read as a direct instruction

**What broke.** Every task's prompt explicitly said, in plain language, "do
not call the memory tools." The model called them anyway, repeatedly, across
multiple products. The reason turned out to be specific: past runs had saved
memory notes phrased *as instructions* — things like "The visual brief should
focus on showcasing the Camera Control button and Action Button" — rather
than as neutral facts. When that memory got recalled into a later, unrelated
run, it read to the model as authoritative in-context guidance competing
directly with the actual system prompt telling it not to use memory at all.
A same-weight instruction beats a "please don't" every time a 7B model has to
choose between them.

**How it was diagnosed.** By reading what the memory store actually
contained — not what the system prompt asked for, but the literal saved
strings. They were written in imperative voice, and once you see a memory
system storing instructions instead of facts, it's obvious why telling the
model "ignore memory" doesn't reliably win.

**How it was fixed.** Stopped trying to out-prompt the problem. Read
CrewAI's own source to confirm memory-tool injection is unconditional
whenever a crew has memory enabled — no per-task or per-agent override
exists to suppress it selectively. Disabled crew memory entirely, then
verified structurally (by loading the real crew object and inspecting each
agent's resolved tool list, not just by re-running and hoping) that zero
agents had memory tools available anymore. Confirmed with two independent
live regression runs and, later, seven products across seven categories with
retry-until-genuine-result logic — all completing cleanly with no memory
calls possible. The fix that actually worked was removing the model's
ability to make the mistake, not asking it more firmly not to.

---

## What this demonstrates

Small local models don't fail gracefully — they fail loudly and immediately
when an architecture leans on an assumption that isn't actually true. That
turned out to be an advantage for finding real problems fast, not just a
constraint to work around.

A few things that held up across all five bugs:

- **Prompting is not a substitute for structural enforcement.** Every "please
  don't do X" instruction in this codebase that relied purely on the model's
  compliance eventually failed under some condition. The fixes that actually
  held were the ones that made the failure mode structurally unreachable —
  a tool that refuses bad input, a hard iteration cap, a feature disabled at
  the framework level and verified via source code, not a stronger sentence.
- **Guardrails need to sit at the point of consequence, not just at the
  point of output.** Checking a model's final text isn't the same as
  checking what it already did on the way there.
- **"The tool's status output looks fine" isn't the same as "the system is
  fine."** The RAM leak was invisible to `ollama ps` specifically because it
  was designed to report loaded models, not every process a restart could
  leave behind.
- **Diagnosis has to go one level below the symptom.** "The model ignored an
  instruction" isn't a root cause — the real cause was a specific string
  format in what the memory system stored. Fixing the visible symptom without
  finding that would have meant re-fighting the same bug under a different
  product name next time.
- **Fixes need to be verified, not just plausible.** Every fix above was
  confirmed by re-running the actual pipeline and inspecting real output —
  resolved tool lists, process lists, calendar file contents — rather than by
  reasoning that the fix *should* work.
