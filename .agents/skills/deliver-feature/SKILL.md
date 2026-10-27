---
name: deliver-feature
description: Apply GitHub Flow when implementing or finalizing repository changes. Create validated local Conventional Commits, prepare pull requests, and require explicit user approval before pushing or opening a pull request. Do not use for read-only tasks or standalone release and deployment operations.
---

# Deliver Feature

Deliver related repository changes through a short-lived branch and a reviewable pull request, using coherent commits that keep different features separate. Preserve the user's existing work and distinguish local implementation from approval to publish the delivery.

## Scope and project contract

This skill owns the repository workflow: branches, validation, commits, pull requests, review status, and post-merge cleanup. Establish the requested completion milestone, such as validated local commits or a published pull request, and report whether it has been reached. Reuse authorization already given in the session for the same actions and scope.

Derive applicable checks, build commands, compatibility requirements, and pull request templates from the repository's active instructions, documentation, scripts, and workflows. Select validation appropriate to the change; do not prescribe a toolchain based on project type.

Versioning, packaging, release publication, and deployment procedures belong to the project. When the task includes these operations, follow its documented contract and existing automation; use this skill for any repository changes they require. A request to implement or review a change does not authorize a release or deployment.

## Start the change

Before editing repository files:

1. Inspect the working tree, current branch, remotes, and remote default branch.
2. Stop and explain the problem if usable Git metadata, a configured remote, or the remote default branch cannot be established.
3. Do not discard, stash, move, stage, commit, or absorb pre-existing user changes without explicit permission.
4. When remote access is available, fetch the remote default branch. If access is temporarily unavailable, use an existing remote-tracking ref for the known default branch and report that it could not be refreshed. Do not introduce a merge commit while synchronizing it.
5. If the current non-default branch already matches the requested change, reuse it. Otherwise, create a branch or worktree from the remote default branch, preserving any pending work.
6. Inspect open pull requests and other worktrees for overlapping changes, using the coordination rules below before implementing.

Name new branches `<type>/<issue-id>-<slug>`, omitting the issue ID when unavailable. Use lowercase kebab-case. Choose the narrowest applicable type, normally `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`, `ci`, or `chore`.

## Continue before pull request publication

When the user requests another feature while delivery approval is pending, continue implementation without treating the new request as approval to push or open a pull request. For related features on an unpublished branch, reuse it and rename it with `git branch -m` when its name no longer describes the combined scope. Preserve logical commit boundaries within and between features. Use a separate branch/worktree for independent features.

For branch renaming, amendment, and other history rewrites, an unpublished branch must never have been pushed, and the commits being rewritten must not have been shared through another branch, tag, or pull request. Check remote refs and known publication history; a missing remote branch or an upstream pointing at the base does not establish this. If publication status is uncertain, preserve the existing name and commits.

Before starting the next feature, validate and commit any completed feature using the local commit rules below. Preserve unfinished or failing work without committing it just to switch tasks. Refresh the delivery package to cover the accumulated features, current branch name, and complete commit list; an earlier package does not approve an expanded scope.

## Implement and validate

- Follow the repository's active instructions and load only the project documentation relevant to the change.
- Keep the branch and pull request focused on related changes. A feature may span one or more commits, each covering a coherent, reviewable change with its relevant tests/documentation. Keep different features in separate commits.
- Add or update tests when behavior changes.
- Run the narrowest relevant checks first, followed by the repository's required validation commands when applicable.
- After a coherent implementation step, feature, or adjustment is complete and its applicable checks pass, inspect the diff, stage only task-owned changes, recheck the staged diff, and create a local Conventional Commit without a separate confirmation. Never include unrelated pre-existing user changes or unfinished/failing work.
- Report local commit identifiers and validation results. Do not claim that a check passed unless it was run successfully.

For a follow-up adjustment, use `git commit --amend` only when it belongs to the same coherent change as the branch's latest commit, that commit was created by the agent for this task, is not a merge commit, and the branch and commit satisfy the unpublished conditions above. Validate the adjustment first and include only changes within that commit's scope. Update the commit message if necessary to describe its final behavior.

If the adjustment belongs to an older commit, covers a separate coherent change, or the branch has been published, create a new commit for the adjustment. Do not automatically fold adjustments into older feature commits or rewrite pre-existing user commits. After an amendment or added commit, refresh any pending delivery package with the new identifiers, scope, and validation results.

## Coordinate branches and pull requests

Compare changed-file lists from open pull requests and other worktrees first, then read relevant diff ranges for overlapping functions, behavior, or contracts. Include uncommitted work when checking related worktrees, without modifying it. File overlap alone is an alert, not a reason to block independent work. Record dependencies and the proposed integration order; sequence changes to the same behavior when practical.

Before requesting publication approval, fetch the target base again. With the requested changes committed and the working tree clean, synchronize the feature branch with the latest remote base:

- For an unpublished branch, rebase onto the base only when all commits being replayed are task-owned and satisfy the unpublished conditions above. Preserve feature boundaries and the logical separation of commits; this synchronization does not authorize folding adjustments into older feature commits.
- For a published/shared branch, prefer merging the base into the feature branch, creating a local synchronization commit. Do not rename it, rebase published commits, or force-push without separate explicit authorization.

Do not stash or discard changes to synchronize. Preserve pre-existing user history; if it prevents a safe update, explain the issue rather than rewriting it. Resolve conflicts within the requested scope, preserving each feature's intended behavior; ask for clarification when the correct behavior is ambiguous. Rerun applicable validation when synchronization changes the branch and refresh the delivery package.

After another pull request merges, refresh the base and reassess overlap, dependencies, and mergeability for remaining related work. Update branches within the active task's scope; report other affected branches without changing another worktree's ongoing work. Once published, verify mergeability and CI against the latest head; earlier successful checks do not validate a changed head.

When repository-level enforcement is requested, recommend required CI checks and an up-to-date base before merging. Treat changes to GitHub protection rules as separate configuration work requiring explicit authorization.

## Prepare the delivery package

Once requested changes are committed, the branch is synchronized, and validation is complete, inspect the complete diff from the base to the branch head and present:

- branch name and base branch, with their current base and head commit identifiers;
- concise summary of the change;
- changed and untracked files intended for delivery;
- validation commands and their results, including any failures or commands that could not run;
- existing local commits with their identifiers and exact Conventional Commit messages;
- proposed pull request title, body, base branch, and draft or ready-for-review state;
- automatic effects of the proposed push, pull request, or authorized merge, such as preview or production deployments, when applicable;
- known risks, limitations, or follow-up work when relevant.

Use Conventional Commits 1.0.0 for each commit. Keep scopes optional and repository-specific. Mark breaking changes with `!` and explain them in the commit body or footer. Prefer a Conventional Commit title for the pull request so squash merges preserve the convention.

Use the repository's pull request template when present. Otherwise, use this default Markdown structure:

```markdown
## Summary

<Explain why this change is needed, who or what it affects, and the result. Link an issue when relevant.>

## Changes

- <Describe a behavior or capability change and its user or project impact.>
- <Describe supporting documentation, configuration, or tests when relevant.>

## Validation

- `<command>` — passed: <relevant result>.
- `<manual check>` — <result>.
- Not run: `<relevant check>` — <reason>.

## Compatibility and rollout

- <Breaking changes, migration steps, changed defaults or configuration, data impact, or deployment steps.>
- None.

## Risks and follow-ups

- <Known limitation or unresolved work; link an issue or name an owner when useful.>
- None.
```

For the default template, keep all five headings in this order. Replace the instructional placeholders and remove unused example bullets, but do not remove a section. Keep the summary to one or two short paragraphs. Describe reviewable behavior and impact under `Changes` instead of listing files or commits. Under `Validation`, list materially relevant automated and manual checks with their results, and give a reason for each relevant check that was not run. Under `Compatibility and rollout`, state `- None.` when the change has no compatibility, migration, configuration, data, or deployment impact. Under `Risks and follow-ups`, state `- None.` when no known issues remain. Put issue links, screenshots, breaking-change details, rollout notes, and other context inside the closest matching section rather than adding ad hoc headings. Focus on the final implementation, without conversational history or abandoned approaches.

Create the pull request using the exact title and body shown in the approved delivery package. Preserve Markdown with a body file or an equivalent structured tool argument rather than assembling multiline prose through fragile shell quoting.

Unless already authorized for the displayed scope, ask one explicit confirmation covering publication of the displayed commits, the push target, the pull request, and any automatic deployment effects. Local commits do not require this confirmation. Do not treat approval of implementation or additional features as publication approval.

## Publish the pull request after approval

After the user approves the displayed delivery package:

1. Fetch the target base again and recheck that the working tree is clean and the committed scope, messages, and validation results match the approved package. If the base advanced, apply the coordination rules and refresh the package before publishing, requesting renewed approval when it changes materially.
2. Push the branch to the approved remote and set its upstream.
3. Check whether a pull request already exists before creating one, especially after a failed or uncertain retry.
4. Open the pull request with the approved title, body, base branch, and review state.
5. Check mergeability and CI for the exact published head. Wait for applicable checks when feasible and report passed, failed, pending, or unavailable results accurately. Recheck after any change to the head; earlier successful checks do not validate new commits.
6. Return the commit identifiers, validation summary, pull request link, and current review and CI status. Distinguish a published pull request from a merged change or a deployed product.

Request approval again if the content, commit plan, remote, base branch, pull request state, or automatic deployment effects change materially. Report failures without inventing a successful result or creating duplicate pull requests. Never merge the pull request without separate explicit authorization; an authorized merge must satisfy the repository's required reviews, checks, and base synchronization policy.

## Clean up after merge

When the user reports that a pull request was merged, first confirm through GitHub that its state is `MERGED`, record its exact head branch and commit, base branch, and repository default branch, and check that the working tree is clean. If any check fails, stop and explain the problem.

Before asking for cleanup, refresh the remote-tracking refs and inspect all local branches, their pull request status, and `git worktree list`. Include other obsolete local branches when their tips are ancestors of the remote base (`git merge-base --is-ancestor <branch> <remote>/<base>`). A local-only branch without a pull request can qualify: a previous push is unnecessary when all its commits are already on the base.

Exclude the base and default branches, branches checked out in another worktree, branches with open pull requests, and branches with unmerged commits. A closed-unmerged pull request does not by itself disqualify a branch whose recorded tip is already an ancestor of the base, such as a superseded branch integrated through another pull request. Verify that integration before including it in the approval list. Retain and report branches whose eligibility cannot be confirmed.

Present the exact cleanup list, including the merged pull request's head and any qualifying additional local branches, record their current tips, and ask for one explicit confirmation covering that list. Explain any retained branches. The merge report alone is not approval to clean up.

After explicit confirmation:

1. Recheck that the working tree is clean. Stop if it changed; do not stash or discard changes to perform cleanup.
2. Switch to the base branch, fetch the remote with pruning, and update the local base by fast-forward only.
3. Recheck the recorded tips and cleanup eligibility. Delete only the approved local branches with `git branch -d`. Retain and report any branch that changed, no longer qualifies, or cannot be deleted safely. Never use force deletion.
4. Verify that the repository's automatic branch deletion removed the remote pull request head branch. If it remains, report it instead of deleting it without additional authorization.
5. Confirm the final working-tree state and report any remaining local branches and why they were retained.

Do not delete branches with unmerged work or unverified status. Cleanup confirmation authorizes only the exact local branches listed, not other branches or remote deletion.
