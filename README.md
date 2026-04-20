# plan-plus

***UPDATE***

- **Plan restructure simplified for consistency.** The on-disk plan file is no longer split into a skeleton + per-step files. Instead, the original plan is copied verbatim to `plan-full.md` and the on-disk file becomes a compressed line-reference index — each `## ` / `### ` header kept with its `(N-M)` line range in `plan-full.md`. Same compression logic runs on every plan regardless of its original structure.
- **More efficient use of the executor agent.** A session-specific executor name (`plan-plus-executor-<sessionid>`) is baked into the plan header with instructions to reuse that one agent session via `SendMessage` across every step, instead of spawning a fresh agent per step. Agent creation is the dominant per-step cost; reusing one session eliminates it.
- **New `reference-docs/` folder** next to `plan-full.md` for small fine-grained context files. An injected `## Step 0` instructs Claude to seed it (on the main thread, without the executor agent) before step 1 begins.
- **Line-reference compressor is now a standalone reusable Python module** (`scripts/compress-to-line-reference.py`) that can be used outside the hook.

---

**Smarter plan execution for Claude Code.**

- On ExitPlanMode, copies the full original plan to a plan-docs folder (`plan-full.md`) alongside an empty `reference-docs/` folder for fine-grained context files
- Rewrites the on-disk plan file in place as a compressed **line-reference index** — each `## ` / `### ` header is kept and annotated with its `(N-M)` line range in `plan-full.md`, and the bodies are removed
- Bakes a **reused-session executor agent name** (`plan-plus-executor-<sessionid>`) into the header so every step resumes the same ephemeral agent instead of spawning a new one (agent creation is expensive)
- Base plan mode re-injects the entire plan every turn, filling context fast — plan-plus fixes this by keeping only the compressed index on disk

---

## Quickstart

```bash
claude plugin marketplace add RandyHaylor/plan-plus
claude plugin install plan-plus
```

Restart Claude Code after adding to marketplace and installing.
Use plan mode normally.
    (shift+tab until it says plan mode in the cli tool - a button in the ui for vs code plugin). 
When you approve a plan and claude transitions to execute the plan, plan-plus will automatically restructure the plan file and inject more instructions. 
   (Manually exiting plan mode will not - you must go through claude code offering you the plan approval step and transition)

---
Disabling for a project or globally:

include in project-folder/.claude/settings.local.json or user-folder/.claude/settings.loca.json:
  "enabledPlugins": {
    "plan-plus@plan-plus": false
  }

---

## Case Study: Pac-Man Calculator

A React calculator app with an animated Pac-Man that navigates the lanes between buttons, turning toward the mouse at intersections — no diagonal movement, no 180° turns, dot-product direction picking at each node.

https://github.com/user-attachments/assets/723004a5-78ed-4f7f-a9a5-3fcf62010036

Two sessions built the same app from the same plan and the same 8 context files (lane graph construction, movement algorithm, canvas rendering, calculator reducer, CSS layout, component hierarchy, TypeScript interfaces, edge cases). Both produced near-identical results — Pac-Man successfully navigating between buttons, chomping, turning toward the cursor.

| Metric | plan-plus | Standard plan mode |
|--------|-----------|-------------------|
| Total tokens | **1.59M** | 4.35M |
| API calls | **50** | 98 |
| Peak context | **41K** | 61K |
| Calls at 30K+ context | **23** | 73 |

**63% fewer tokens, 49% fewer API calls.** Plan-plus delegated work to a focused executor agent while standard mode ran all 98 calls in one growing context. The plan-plus output was also more robust — reusable utilities, generic spanning-button detection, correct animation overshoot math — while standard mode had a subtle momentum bug and hardcoded layout assumptions.

> Note: this case study predates the current line-reference compression and reused-session agent design; the broader point (keeping plan content out of the main turn loop) still holds.

---

## The Problem

Claude Code re-injects the full plan file into the in-memory message array on every turn during plan execution. These injections accumulate and can't be removed until compaction. A 4KB plan injected across 30 turns adds ~120KB of duplicate plan content to the main conversation context.

## The Solution

Plan-plus intercepts ExitPlanMode and restructures the plan:

- **Copies** the full original plan to `<plan-dir>/plan-full.md` (source of truth)
- **Creates** `<plan-dir>/reference-docs/` for small fine-grained additional plan context files
- **Compresses** the on-disk plan file into a line-reference index: each `## ` / `### ` header is kept with a `(N-M)` line-range annotation referencing `plan-full.md`; bodies are removed
- **Bakes** a session-specific executor agent name into the header with instructions to *reuse* that one agent session across all steps (via `SendMessage`) rather than spawning a new agent per step

Only the compressed index gets injected per turn. The executor agent reads specific line ranges from `plan-full.md` (and anything under `reference-docs/`) on demand, and its context stays off the main conversation.

---

## What Happens When You Exit Plan Mode

**Before plan-plus** — the full verbose plan is injected every turn.

**After plan-plus** — your project gets this structure:

```
.claude/plans/plan-plus--<session-name>/
    plan-full.md              Full original plan (source of truth)
    reference-docs/           Fine-grained context files (written by the executor agent as it learns)
```

And the on-disk plan file is rewritten in place as something like:

```markdown
- plan body (read indicated line ranges): /abs/path/.claude/plans/plan-plus--vue-checkers/plan-full.md
- fine-grained context files (place/reference here): /abs/path/.claude/plans/plan-plus--vue-checkers/reference-docs
- executor agent: `plan-plus-executor-a1b2c3d4` (subagent_type: plan-plus-executor)
  - spawn ONCE on step 1; every later step: SendMessage(to="plan-plus-executor-a1b2c3d4", ...)
  - never spawn a new Agent per step (expensive)
  - if session expired, respawn Agent with SAME name to preserve continuity

## Step 0 - Create or copy docs for small chunks of requirements or reference that will be frequently referenced during the project to the reference-docs folder. Do not use the executor agent for this step.

## Context (3-18)

## Plan (19-74)

### Step 1 — Documentation (20-31)

### Step 2 — Project setup (32-45)

### Step 3 — TDD game logic (46-74)

## Testing (75-90)
```

Each `(N-M)` points to the line range in `plan-full.md` — the executor agent opens just those lines when it needs to work on that section. The injected `## Step 0` has no line range because it has no body in `plan-full.md`; it's an instruction added by the hook to prime `reference-docs/` before step work begins, and it deliberately opts out of the executor agent.

---

## Screenshots

![Step 0 reads all step files, refines the skeleton, then launches Step 1 with the executor agent](plan-plus-screenshot-2.png)

![Plan-plus executing steps — writing tests, wiring components, verifying](plan-plus-screenshot.png)

> Screenshots above show an earlier step-file-extraction design; the current plugin uses the line-reference index format described above.

---

## How It Works

**Plan mode works normally.** Claude researches, explores, writes a detailed plan.

**On ExitPlanMode**, a PostToolUse hook fires and runs a Python script that:

1. Locates the plan file Claude produced
2. Creates `<cwd>/.claude/plans/plan-plus--<basename>/`
3. Copies the full plan to `<plan-dir>/plan-full.md`
4. Creates `<plan-dir>/reference-docs/`
5. Rewrites the on-disk plan file as: a 6-line bulleted header (plan body path, reference-docs path, executor agent session name + reuse rules), an injected `## Step 0` header instructing Claude to prime `reference-docs/` without using the executor agent, and the compressed line-reference index (produced by the self-contained `compress-to-line-reference.py`)
6. Emits `additionalContext` pointing Claude at the new structure

**The executor agent** (`plan-plus-executor`) is spawned *once* per project session with name `plan-plus-executor-<sessionid>`. For every subsequent step Claude uses `SendMessage(to="plan-plus-executor-<sessionid>", ...)` to resume that same agent session, handing it the step header name, its `(N-M)` line range in `plan-full.md`, and any relevant `reference-docs/` files. The agent's context stays ephemeral to the main conversation.

---

## Requirements

- Python 3.7+
- Claude Code 2.1.x+

---

## Plugin Contents

```
.claude-plugin/
    marketplace.json                    Marketplace manifest

plan-plus/
    .claude-plugin/
        plugin.json                     Plugin manifest
    hooks/
        hooks.json                      PostToolUse hook on ExitPlanMode
    scripts/
        restructure-plan.py             Main hook script (copy + compress + inject)
        compress-to-line-reference.py   Self-contained, reusable line-reference compressor
    agents/
        plan-plus-executor.md           Reused-session executor agent definition
```

---

## Naming

The plan directory is named after the plan file's basename (which Claude Code derives from the session topic — the name you see above the prompt field). The executor agent session name uses the first 8 chars of the Claude Code `session_id`.

---

## Idempotency

If the on-disk plan file already starts with `- plan body` and contains `executor agent:` (indicating plan-plus has already restructured it), the hook is a no-op. Running plan mode again with a new plan will rewrite it fresh.

---

## Technical Background

Claude Code's plan execution mode re-injects the plan file content as a `plan_file_reference` attachment on every turn. These attachments are computed in-memory from the plan file on disk and appended to the persistent message array via React state (`setMessages`). They accumulate there until compaction replaces the entire message array — meaning every turn of execution adds another copy of the full plan into the main conversation's in-memory context.

By replacing the plan file with a small line-reference index, each injection is a fraction of the size. The verbose plan content lives in `plan-full.md` and is read by the executor agent at specific line ranges only when needed, keeping the main conversation lean throughout execution.

---

## License

MIT

---

## What It Actually Does (User Story)

**You:** Open a fresh Claude Code session, switch on plan mode, and type: "build me a Vue 3 multiplayer checkers game with Firebase."

**Claude:** Spends several turns researching your codebase, thinking through the architecture, and writes a detailed plan — stack choices, file structure, game logic, TDD approach, deployment. You read it, it looks good. You approve.

**The moment you hit approve**, before Claude writes a single line of code, the plan-plus hook fires. In the background, Python copies the plan file Claude just wrote to `plan-full.md`, creates a `reference-docs/` folder next to it, and rewrites the on-disk plan file in place as a compressed line-reference index — each `##`/`###` header kept with a `(N-M)` line range, bodies removed — plus a header baking in a session-specific executor agent name.

**Claude's first step** is to spawn the executor agent *once* with name `plan-plus-executor-<sessionid>`, handing it the header name and its line range in `plan-full.md`. The agent reads just those lines, does the work, and returns.

**For each subsequent step**, Claude *resumes* the same agent session via `SendMessage` — not a new Agent call, because spawning a new agent per step is expensive. The agent keeps working through the plan, reading specific line ranges, writing code, and dropping small context files into `reference-docs/` as it learns things worth preserving.

**What you see** in the main conversation: a short line-reference index with checkboxes, one by one. No re-injected walls of plan text accumulating turn after turn. The context stays clean across the whole build.

**When it's done**, your project is built and the main conversation is still lightweight enough to keep going — ask follow-up questions, request changes, start a new feature — without hitting context limits from the plan you approved at the start.
