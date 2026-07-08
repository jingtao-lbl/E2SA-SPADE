---
name: e2sa-refine-skill
description: Improve an existing E2SA skill from accumulated evidence, human-gated. Use when a skill missed a step or needs updating, when a lesson/feedback in a skill's domain has piled up, or during a periodic skill review — "refine the X skill", "improve this skill", "the X skill should have caught Y", "review the skills". Gathers the signal (lessons, run-journal outcomes, feedback), proposes a concrete SKILL.md diff, and STOPS for human approval; it never self-applies. After approval it edits, appends a Changelog line, and commits.
allowed-tools: [Read, Glob, Grep, Write, Edit, Bash]
---

# e2sa-refine-skill

The "distill → propose → gate → apply" half of skill evolution. The capture half already exists (`e2sa-lessons-capture` writes traps to `memory/knowledge/lessons/`). Design: `docs/design/09_skill_evolution.md`. **Human-gated: this skill proposes; it never rewrites a skill on its own.**

## When to fire

- **Reactive:** a lesson, feedback, or repeated failure in a skill's domain suggests its `SKILL.md` is missing or mis-stating a step.
- **Periodic:** a scheduled skill review (see §"Cadence" in the design doc).
- A human directly asks to refine/improve a skill.

## Procedure

1. **Pick the target skill** and read its current `.claude/skills/<name>/SKILL.md`.
2. **Gather the signal** (do not act on noise):
   - `memory/knowledge/lessons/` and `findings/` tagged to the skill's domain.
   - Run-journal outcomes for the skill (clean / retry / fail / human-corrected) — a high retry/fail rate is a candidate.
   - Explicit feedback memories.
   - **Threshold:** refine on a *repeated* trap (same lesson ≥ ~2-3 times), an explicit human correction, or a clear failure pattern. A single one-off is usually not enough.
3. **Propose a concrete diff**, not a vague suggestion: the exact new/edited step, gotcha, or trigger wording, with the lesson(s) that justify it cited.
4. **STOP at the human gate.** Present the proposed diff and the evidence; wait for approval. (The independent reviewer at `.claude/reviewer/` may serve as the gate where configured. Per-skill auto-apply of low-risk edits is a later opt-in, off by default.)
5. **On approval:** apply the edit and append a dated `## Changelog` line stating what changed and which lesson drove it. **If the edit changed the skill's `name:` or its catalog-relevant trigger/summary, update the matching row in the `AGENTS.md` capability catalog to stay in sync.** Then **run `python tools/check_skill_registry.py` (must exit 0)** before committing — it confirms the name↔directory match, the catalog row, and the `## Changelog` are all intact (the same backstop `e2sa-add-skill` step 5 uses). Commit with a plain message; write a short dev log if the change is substantive.

## Guardrails

- **Never self-apply.** Propose + gate, always (to start).
- **Surgical edits only** — add or fix a step; do not bloat the skill or rewrite wholesale. A skill that keeps growing is a smell; consider splitting or pruning instead.
- **`description` (trigger) edits are the highest risk** — they change *when* the skill fires. Flag any trigger change prominently for the human.
- **Evidence-cited** — every proposed change names the lesson/feedback/outcome that justifies it. No speculative edits.
- Keep framework skills domain-agnostic.

## Changelog

- 2026-06-17: Initial version (per `docs/design/09_skill_evolution.md`).
- 2026-06-22: Step 5 now requires syncing the `AGENTS.md` catalog row on a name/trigger change and running `tools/check_skill_registry.py` before commit (the registry backstop `e2sa-add-skill` already had; refine could otherwise desync the catalog).
