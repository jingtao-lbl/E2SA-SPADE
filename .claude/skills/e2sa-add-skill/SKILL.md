---
name: e2sa-add-skill
description: Scaffold and register a new E2SA skill so the steps are never half-done. Use when the human or agent wants to create a new capability — "add a skill", "create a new skill", "scaffold a skill", "make this reusable as a skill", "distill X into a skill". Creates the SKILL.md with correct frontmatter, registers it in the AGENTS.md capability catalog (the manual registry), seeds a Changelog, and stops for human review before commit. Human-gated.
allowed-tools: [Read, Glob, Grep, Write, Edit, Bash]
---

# e2sa-add-skill

Scaffolds a new skill AND registers it, because the two-step "create the `SKILL.md` and update the `AGENTS.md` catalog" is easy to half-do (it was, for `e2sa-add-data-source`). Design: `docs/design/09_skill_evolution.md`.

## When to fire

- The human asks to add/create/scaffold a skill.
- The agent recognizes a recurring procedure worth making reusable (propose it; do not self-create without surfacing).

## Procedure

1. **Name + scope.** Pick a kebab-case `<name>`. Framework-general capability → `e2sa-<name>`; project-specific → consider scoping under the project. Confirm the name with the human if unsure (the directory name becomes the `/<name>` slash command).
2. **Write `.claude/skills/<name>/SKILL.md`** with the frontmatter:
   - `name:` matching the directory.
   - `description:` — this IS the trigger the harness matches; write it as "what it does + when to use it + example phrasings." Highest-leverage line; get it right.
   - `allowed-tools:` — the minimal tool set.
   - Body: a short purpose line, "When to fire", a numbered "Procedure", "Guardrails", and a `## Changelog`.
3. **Register it (the manual step):** add a row to the **"Capability catalog" table in `AGENTS.md`** (`| `<name>` | invoke when… | notes |`). This is the human-facing registry; auto-discovery handles the functional side.
4. **Seed the `## Changelog`** with a dated "Initial version" line, and (optional) a `signals:` note pointing to where evidence for future refinement will live (`memory/knowledge/lessons/`).
5. **Verify the registry (mechanical backstop):** run `python tools/check_skill_registry.py` — it must exit 0. This confirms the new skill has its `AGENTS.md` catalog row, its frontmatter `name:` matches the directory, and it carries a `## Changelog`. If it reports DRIFT, you skipped step 3; fix and re-run.
6. **Stop for human review**, then commit (`.claude/skills/<name>/` + `AGENTS.md`) with a plain message. Do not commit unreviewed.

## Guardrails

- **Register or it drifts:** never finish without the `AGENTS.md` catalog row. `tools/check_skill_registry.py` (step 5) is the enforceable backstop — wire it into CI / pre-commit so the invariant holds even when this skill isn't used.
- **Minimal procedure:** a skill encodes the easy-to-get-wrong conventions, not an essay. If it is one obvious step, it may not need to be a skill.
- **Framework skills stay domain-agnostic** (no project sites/paths baked in); project-specific logic lives under `projects/<project>/`.
- **Mark non-user-invocable / auto-fire skills** explicitly in the description (like `e2sa-lessons-capture`).
- Human-gated: propose + review before commit.

## Changelog

- 2026-06-17: Initial version (per `docs/design/09_skill_evolution.md`).
- 2026-06-17: Broadened the trigger to include "distill X into a skill" (a natural team/`09` phrasing for creating a new skill from existing knowledge).
- 2026-06-17: Added step 5 — mechanical registry verification via `tools/check_skill_registry.py` (drift backstop; the motivating `e2sa-add-data-source` gap is now enforceable, not just convention).
