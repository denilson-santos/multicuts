---
name: manage-feature-plans
description: Create, update, or review documented implementation plans organized as feature packages and actionable tasks. Use when a project needs a maintained plan index, execution order, dependencies, status, and pull-request tracking; do not use to implement product code.
---

# Manage Feature Plans

Create or review implementation plans that another agent can execute without inventing product requirements. A package represents one cohesive, reviewable feature. Its tasks describe work and acceptance, not commits: a task may require multiple commits, and a package may span multiple pull requests.

## Ground the work

- Read repository instructions and only the documentation needed for the requested planning work. Use the user's explicit requirements and established project documentation, architecture, conventions, and decisions to define intended behavior.
- Inspect existing plans before choosing a layout. Consult relevant code and tests when needed to understand current behavior, interfaces, integration points, and implementation state. Use Git history when needed to verify prior decisions or known PRs. If implementation conflicts with stated requirements, record the conflict instead of silently treating current behavior as the requirement.
- Identify the next supported features that unlock downstream work and can be implemented as coherent review units. State unresolved requirements as assumptions, open questions, or dependencies instead of silently deciding them.

## Create or update plans

- Preserve an existing plan layout and document conventions. If none exists, use `docs/plans/README.md` as the index and `NNN-feature-slug/` for each package, with a package `README.md` and numbered, descriptive task files.
- Keep the index README authoritative for package status, priority, dependencies, known PR links, and recommended execution order. Keep each package README authoritative for its objective, context, included and excluded scope, established decisions, completion criteria, suggested task sequence, task index, risks, and open questions. Include likely components and validation where they improve execution. Link requirements to their sources when useful.
- Record task status, priority, dependencies, and known PRs in the package task index. Make each task specific enough to implement and verify; include expected changes, acceptance criteria, and tests where applicable. Do not prescribe one commit per task.
- Use only these five statuses for packages and tasks: `planned`, `in-progress`, `in-review`, `blocked`, and `completed`. Define priorities by sequencing impact in the index. Mark an item `in-review` when its planned implementation and validation are complete with a pull request open for review. A blocked item names its blocker; a completed item requires its acceptance criteria and validation to be satisfied after integration. A merged PR alone does not establish completion.
- Allow multiple PR links for a package or task. Initialize new plans as `planned`. Show `—` when no PR is known; verify progress before changing status and never invent a PR. Keep duplicated metadata in task files synchronized with the READMEs when the repository's convention includes it.
- Order packages by actual prerequisites and identify work that can proceed independently. Keep feature boundaries small enough for focused review without splitting tasks merely to match commits or PRs.

## Review and report

- Check requirement support, scope, task actionability, acceptance and tests, dependency order or cycles, status evidence, PR links, and consistency between the index, package READMEs, and task files. Separate verified findings from assumptions and proposed changes.
- For a review-only request, report findings without editing files. When asked to revise or create plans, update only the authorized planning files; do not implement product code as part of this skill.
- Finish with a short summary of packages created or revised, recommended execution order, and material open questions or blockers.
