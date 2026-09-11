---
name: deliver-feature
description: Apply the repository delivery workflow when implementing or finalizing a code change. Use GitHub Flow and Conventional Commits, and require explicit user approval before committing, pushing, or opening a pull request. Do not use for read-only analysis, diagnosis, review, or status requests.
---

# Deliver Feature

Deliver one coherent repository change through a short-lived branch and a reviewable pull request. Preserve the user's existing work and treat approval for implementation as distinct from approval to publish the delivery.

## Start the change

Before editing repository files:

1. Inspect the working tree, current branch, remotes, and remote default branch.
2. Stop and explain the problem if usable Git metadata or a required remote is unavailable.
3. Do not discard, stash, move, stage, commit, or absorb pre-existing user changes without explicit permission.
4. When remote access is available, fetch the remote default branch. Do not introduce a merge commit while synchronizing it.
5. If the current non-default branch already matches the requested change, reuse it. Otherwise, create a branch from the remote default branch.

Name new branches `<type>/<issue-id>-<slug>`, omitting the issue ID when unavailable. Use lowercase kebab-case. Choose the narrowest applicable type, normally `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`, `ci`, or `chore`.

## Implement and validate

- Follow the repository's active instructions and load only the project documentation relevant to the change.
- Keep the branch and pull request focused on one coherent change.
- Add or update tests when behavior changes.
- Run the narrowest relevant checks first, followed by the repository's required validation commands when applicable.
- Do not create commits during implementation. Do not claim that a check passed unless it was run successfully.

## Prepare the delivery package

After implementation and validation, inspect the complete diff and present:

- branch name and base branch;
- concise summary of the change;
- changed and untracked files intended for delivery;
- validation commands and their results, including any failures or commands that could not run;
- proposed atomic commits with their exact Conventional Commit messages;
- proposed pull request title, body, base branch, and draft or ready-for-review state;
- known risks, limitations, or follow-up work when relevant.

Use Conventional Commits 1.0.0 for each commit. Keep scopes optional and repository-specific. Mark breaking changes with `!` and explain them in the commit body or footer. Prefer a Conventional Commit title for the pull request so squash merges preserve the convention.

Ask one explicit confirmation covering the displayed commits, push target, and pull request. Do not treat approval of the implementation request as delivery approval.

## Publish only after approval

After the user approves the displayed delivery package:

1. Stage only the approved files and recheck the staged diff for unrelated or sensitive content.
2. Create the approved commits without silently changing their scope or messages.
3. Push the branch to the approved remote and set its upstream.
4. Check whether a pull request already exists before creating one, especially after a failed or uncertain retry.
5. Open the pull request with the approved title, body, base branch, and review state.
6. Return the commit identifiers, validation summary, and pull request link.

Request approval again if the content, commit plan, remote, base branch, or pull request state changes materially. Report failures without inventing a successful result or creating duplicate pull requests. Never merge the pull request or delete its branch without separate explicit authorization.
