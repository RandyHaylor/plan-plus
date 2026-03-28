# plan-plus

**Smarter plan execution for Claude Code.**
Automatically restructures plans into lightweight skeletons with step-by-step detail files, so your context window stays clean and agents do the heavy lifting.

---

## Quickstart

```bash
claude plugin marketplace add RandyHaylor/plan-plus
claude plugin install plan-plus
```

Restart Claude Code. Use plan mode normally. When you exit plan mode, plan-plus takes over automatically.

---

## The Problem

Claude Code re-injects the full plan file into every API call during plan execution. These injections accumulate in the in-memory message array and can't be removed until compaction. A 4KB plan injected across 30 turns wastes ~120KB of context on duplicate plan content.

## The Solution

Plan-plus intercepts ExitPlanMode and restructures the plan:

- **Splits** the full plan into individual step files
- **Creates** a lightweight skeleton that replaces the original plan file
- **Mines** the conversation for goals
- **Injects** a Step 0 that uses an agent to fill in real requirements and refine the skeleton
- **Provides** a focused executor agent for step-by-step work with ephemeral context

The skeleton is all that gets injected per turn. Agents read the detailed step files only when they need them, and their context is discarded when they return.

---

## What Happens When You Exit Plan Mode

**Before plan-plus** — the full verbose plan is injected every turn.

**After plan-plus** — your project gets this structure:

```
.claude/plans/plan-plus--<session-name>/
    plan-full.md              Full original plan (backup)
    context/
        project.md            Project context extracted from plan preamble
        goals.md              Goals mined from early conversation messages
        requirements.md       Created by Step 0 agent
    steps/
        00-update-skeleton.md Step 0: agent refines the skeleton
        01-documentation.md   Step detail files with full content
        02-project-setup.md   from each section of the original plan
        03-game-logic.md
        ...
```

**The skeleton** (what gets injected per turn):

```markdown
# plan-plus--vue-checkers-multiplayer

## Instructions
- Use plan-plus-executor agent for each step
- Agent context is ephemeral
- Update context/ files with discoveries
- Mark steps done as you complete them

full plan: .claude/plans/plan-plus--vue-checkers-multiplayer/plan-full.md
context:   .claude/plans/plan-plus--vue-checkers-multiplayer/context/
steps:     .claude/plans/plan-plus--vue-checkers-multiplayer/steps/

## Requirements
- Stack: Vue 3 + Vite + TypeScript + Vitest + Firebase/Firestore
- Architecture: Pure game logic -> Firebase service -> Vue components
- Patterns: Strict TDD, pure functions, reactive composable
- Key features: Multiplayer via Firestore, mandatory jumps, king promotion

## Steps
0. [x] Update skeleton — filled in requirements and step descriptions
1. [ ] Documentation — requirements, user stories, firestore model, flowcharts
2. [ ] Project setup — scaffold, install deps, configure vitest, verify
3. [ ] TDD game logic — types, board, moves, jumps, execution, state
...
```

---

## How It Works

**Plan mode works normally.** Claude researches, explores, writes a detailed plan.

**On ExitPlanMode**, a PostToolUse hook fires and runs a Python script that:

1. Backs up the full plan to `plan-full.md`
2. Splits the plan on `## ` headers into individual step files
3. Routes context-like sections (Context, Background, Overview) to `context/project.md`
4. Mines the JSONL for early user messages (goals) and the session topic name
5. Writes a skeleton with instructions, requirements placeholder, and step list
6. Renames the plan file to `plan-plus--<session-name>.md`
7. Injects `additionalContext` telling Claude to start with Step 0

**Step 0** is always injected as the first step. An agent reads all step files and context, then rewrites the skeleton with real requirements (stack, architecture, patterns, constraints) and clear one-sentence descriptions per step.

**Steps 1-N** are executed by spawning the `plan-plus-executor` agent with just the relevant step file and context files. The agent's context is ephemeral — it won't bloat the main conversation.

---

## Requirements

- Python 3.7+
- Claude Code 2.1.x+

---

## Plugin Contents

```
.claude-plugin/
    marketplace.json             Marketplace manifest

plan-plus/
    .claude-plugin/
        plugin.json              Plugin manifest
    hooks/
        hooks.json               PostToolUse hook on ExitPlanMode
    scripts/
        restructure-plan.py      Restructuring logic (Python)
    agents/
        plan-plus-executor.md    Step execution agent definition
```

---

## Naming

The plan directory and skeleton file are named after the session topic (the name you see above the prompt field in Claude Code). If no topic name is available, falls back to the session ID.

---

## Existing Plan Directory Warning

If plan-plus detects that the plan directory already exists (from a previous ExitPlanMode in the same session), it warns the user and tells the orchestrator to ask whether to keep or remove old files. New step files are appended alongside existing ones.

---

## Technical Background

Claude Code's plan execution mode re-injects the plan file content as a `plan_file_reference` attachment on every turn. These attachments are computed in-memory from the plan file on disk, appended to the persistent message array via React state (`setMessages`), and sent to the Anthropic API with every call. They accumulate until compaction replaces the entire message array.

By replacing the plan file with a small skeleton, each injection costs ~100 tokens instead of ~1000+. The verbose plan content lives in step files that only agents read in their ephemeral context.

---

## License

MIT
