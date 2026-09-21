---
name: deliver-feature
description: Apply the repository delivery workflow when implementing or finalizing a code change. Use GitHub Flow and Conventional Commits, and require explicit user approval before committing, pushing, or opening a pull request. Do not use for read-only analysis, diagnosis, review, or status requests.
---

# Deliver Feature

Deliver one coherent repository change through a short-lived branch and a reviewable pull request. Preserve the user's existing work and treat approval for implementation as distinct from approval to publish the delivery.

## Start the change

Before editing repository files:

1. Inspect the working tree, current branch, remotes, and remote default branch.
2. Stop and explain the problem if usable Git metadata, a configured remote, or the remote default branch cannot be established.
3. Do not discard, stash, move, stage, commit, or absorb pre-existing user changes without explicit permission.
4. When remote access is available, fetch the remote default branch. If access is temporarily unavailable, use an existing remote-tracking ref for the known default branch and report that it could not be refreshed. Do not introduce a merge commit while synchronizing it.
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

Use this exact Markdown structure for every pull request body:

```markdown
## Summary

<State the concrete problem and the behavior after this change in one or two short paragraphs.>

## Changes

- <Describe a reviewable change.>
- <Describe another reviewable change when applicable.>

## Validation

- `<command>` — passed (<concise result when useful>)
- Not run: `<command>` — <reason>

## Risks and follow-ups

- None.
```

Keep all four headings in this order. Replace the instructional placeholders and remove unused example bullets, but do not remove a section. Under `Validation`, list every materially relevant command that ran and its result; list required or relevant checks that could not run with the reason. Under `Risks and follow-ups`, write `- None.` when there are no known items. Include issue links, migration notes, breaking-change details, screenshots, or operational notes inside the most relevant section rather than creating ad hoc headings. Keep the summary focused on the final implementation, without conversational history or abandoned approaches.

Create the pull request using the exact title and body shown in the approved delivery package. Preserve Markdown with a body file or an equivalent structured tool argument rather than assembling multiline prose through fragile shell quoting.

Ask one explicit confirmation covering the displayed commits, push target, and pull request. Do not treat approval of the implementation request as delivery approval.

## Publish only after approval

After the user approves the displayed delivery package:

1. Stage only the approved files and recheck the staged diff for unrelated or sensitive content.
2. Create the approved commits without silently changing their scope or messages.
3. Push the branch to the approved remote and set its upstream.
4. Check whether a pull request already exists before creating one, especially after a failed or uncertain retry.
5. Open the pull request with the approved title, body, base branch, and review state.
6. Return the commit identifiers, validation summary, and pull request link.

Request approval again if the content, commit plan, remote, base branch, or pull request state changes materially. Report failures without inventing a successful result or creating duplicate pull requests. Never merge the pull request without separate explicit authorization.

## Clean up after merge

When the user reports that a pull request was merged, first confirm through GitHub that its state is `MERGED`, record its exact head and base branches, and check that the working tree is clean. If any check fails, stop and explain the problem. Ask the user to confirm cleanup of that specific head branch. The merge report alone is not approval to clean up.

After explicit confirmation:

1. Recheck that the working tree is clean. Stop if it changed; do not stash or discard changes to perform cleanup.
2. Switch to the base branch, fetch the remote with pruning, and update the local base by fast-forward only.
3. Delete the local head branch with `git branch -d`. Never use force deletion.
4. Verify that the repository's automatic branch deletion removed the remote head branch. If it remains, report it instead of deleting it without additional authorization.

Do not delete an open, closed-unmerged, unidentified, or unpushed branch. Cleanup confirmation does not authorize deleting any branch other than the verified head branch of that pull request.
