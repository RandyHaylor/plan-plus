# plan-plus

Optimized plan mode for Claude Code. Automatically restructures plans into lightweight skeletons when you exit plan mode, reducing token bloat from repeated plan injections.

## What it does

When you exit plan mode (ExitPlanMode), plan-plus:

1. **Backs up** your full plan to `plans/plan-plus--<name>/plan-full.md`
2. **Mines your conversation** JSONL for goals, tech stack, patterns, and constraints
3. **Creates context files** in `plans/plan-plus--<name>/context/`
4. **Rewrites** the plan file as a lightweight skeleton (~500 bytes vs ~4KB+)
5. **Renames** the plan file to `plan-plus--<name>.md` so you can see it's plan-plus managed
6. **Injects instructions** telling Claude to use the `plan-plus-executor` agent for step execution

## Why

Claude Code injects the full plan file content into every API call during plan execution mode. This accumulates in context and can't be removed until compaction. A smaller plan file = less token waste per turn.

## Requirements

- Python 3.7+
- Claude Code 2.1.x+

## Install

```bash
# Add the marketplace
claude plugin marketplace add RandyHaylor/plan-plus

# Install the plugin
claude plugin install plan-plus
```

Then restart Claude Code.

## Usage

Just use plan mode normally. When you approve the plan (ExitPlanMode), the hook fires automatically.

After restructuring, you'll see:
- Plan name in CLI shows `plan-plus--<original-name>`
- `plans/plan-plus--<name>/` directory created in your project with:
  - `plan-full.md` — your original complete plan
  - `context/goals.md` — goals extracted from conversation
  - `context/requirements.md` — stack, patterns, constraints detected
  - `steps/` — directory for per-step detail files

Use the `plan-plus-executor` agent to execute steps:
```
Use the plan-plus-executor agent to work on step 1.
Pass it the step details from plans/plan-plus--<name>/plan-full.md
and the context files from plans/plan-plus--<name>/context/.
```

## Structure

```
.claude-plugin/
  marketplace.json          # Marketplace manifest
plan-plus/
  .claude-plugin/
    plugin.json             # Plugin manifest
  hooks/
    hooks.json              # PostToolUse hook on ExitPlanMode
  scripts/
    restructure-plan.py     # Main restructuring logic
  agents/
    plan-plus-executor.md   # Step execution agent
```

## How it works (technical)

- `nk8()` in Claude Code reads the plan `.md` file from disk every turn
- The content is injected as a `plan_file_reference` attachment into the in-memory message array
- These attachments accumulate permanently until compaction
- By replacing the plan with a tiny skeleton, each new injection is ~100 tokens instead of ~1000+
- The full plan and mined context live in separate files that agents read on demand

## License

MIT
