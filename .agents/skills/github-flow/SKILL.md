---
name: github-flow
description: Manage branches, validation, local commits, and pull requests for repository changes. Use during implementation and finalization; exclude read-only work, standalone releases, and deployments.
---

# GitHub Flow

Deliver the requested repository changes as validated local commits or an
authorized pull request. Follow the repository's instructions, checks, and
templates.

## Authorization and preservation

- Preserve pre-existing changes and history. Do not discard, stash, move,
  stage, or commit the user's existing work without permission.
- Branch creation, implementation, validation, and local commits are part
  of the requested implementation unless the user restricts them.
- Pushing, creating or updating a pull request, merging, and deleting
  branches require explicit authorization for those actions.
- Reuse authorization already given for the same scope and targets.
  Additional implementation requests do not authorize publication.
- Treat a branch or commit as shared once it has been pushed or otherwise
  published. If its publication history is uncertain, preserve its name
  and history.
- Do not rewrite user-owned or shared history, rename shared branches, or
  force-push without explicit authorization.
- Releases and deployments follow the project's procedures and require
  authorization. Disclose known automatic deployment effects before
  requesting publication approval.

## 1. Prepare the branch

Before editing:

1. Read the applicable repository instructions.
2. Inspect the working tree, current branch, remotes, and worktrees.
   Check for an existing branch or pull request for this task.
3. Use the requested base or the existing pull request's base.
   Otherwise, use the remote default branch. Do not guess its name.
4. Fetch the base when remote access is available. If access fails,
   use a known tracking ref and report that it could not be refreshed.
   Local-only work may use a known local base.
5. Reuse a branch that matches the task. Otherwise, create a branch
   from the selected base. Use a separate worktree when needed to
   preserve existing work.
6. Check related pull requests and worktrees for overlapping changes.
   Inspect relevant diffs before deciding whether coordination is needed.

Name new branches `<type>/<issue-id>-<slug>`. Omit the issue ID when
unavailable. Use lowercase kebab-case and an appropriate Conventional
Commit type.

If a required fact cannot be established, explain what is missing and
pause the affected action. Continue independent work when safe.

## 2. Implement, validate, and commit

- Keep related changes together. Use separate branches for independent work.
- Follow the project's testing requirements. Run narrow checks first,
  followed by the required validation.
- Before committing, inspect the diff, stage only task-owned changes,
  and inspect the staged diff.
- Create local Conventional Commits for completed, validated changes.
  Keep different features in separate commits.
- Do not commit unfinished work or work with failing applicable checks.
  Report required checks that could not run; do not describe that work
  as fully validated.
- Use Conventional Commits 1.0.0. Keep scopes optional. Mark breaking
  changes with `!` and explain them in the body or footer.

For a follow-up adjustment, create a new commit by default. Amend only
when the adjustment belongs to the latest commit, that commit was created
by the agent for this task, it is not a merge commit, and neither the
branch nor the commit has been shared. Validate before amending.

For another related request, continue on the same branch when appropriate.
Commit completed work before starting the next feature. Preserve unfinished
work without committing it just to switch tasks.

Rename a branch only when its name no longer fits and it has never been
shared. Refresh any pending delivery summary after changes.

## 3. Prepare publication

With the task changes committed and the task worktree clean:

1. Fetch the target base again.
2. Synchronize the feature branch:
   - Rebase only when every replayed commit is task-owned and unshared.
   - Otherwise, merge the base without rewriting existing history.
3. Resolve conflicts within the requested scope. Ask when the intended
   behavior is ambiguous.
4. Rerun applicable checks after synchronization changes the branch.
5. Review the complete diff from the target base to the branch head.

Do not stash or discard existing work to synchronize. Reassess related
branches after dependencies merge, without changing another worktree's
ongoing work.

Present one delivery summary containing:

- Remote, feature branch, target base, and base/head commit identifiers.
- Summary of the final changes and affected files.
- Commit identifiers and exact commit messages.
- Validation results, including failures and checks that could not run.
- Proposed pull request title, body, and draft or ready state.
- Known risks, compatibility changes, and automatic deployment effects.

Use the repository's pull request template. Otherwise, include:

- `Summary`: the problem and resulting behavior.
- `Validation`: relevant checks, results, and reasons for checks not run.
- `Compatibility and rollout`: include when applicable.
- `Risks and follow-ups`: include when applicable.

Describe the final implementation. Keep the description proportional to
the change. Prefer a Conventional Commit pull request title.

If publication is not already authorized for this scope, ask one
confirmation covering the commits, push target, pull request, and
disclosed automatic effects.

## 4. Publish

After authorization:

1. Refresh the target base and verify that the changes and targets
   still match the approved delivery.
2. If synchronization is needed, follow the previous section and refresh
   the delivery summary.
3. Push the approved branch to the approved remote and set its upstream.
4. Check for an existing pull request before creating one, including
   after a failed or uncertain attempt.
5. Create or update the pull request with the approved title, body,
   base, and review state. Preserve Markdown using a body file or a
   structured tool argument.
6. Check mergeability and CI for the exact published head. Report passed,
   failed, pending, or unavailable results accurately.

Request renewed approval when the changes, targets, review state, or
automatic effects materially differ from what was authorized. A new
commit identifier alone does not establish a scope change.

Return the pull request link, commit identifiers, validation summary,
and current CI/review status.

Merge only with explicit authorization and after satisfying the
repository's required checks, reviews, and synchronization policy.
A published pull request does not establish that the change is merged
or deployed.

## 5. Clean up after merge

When cleanup is requested or the user reports a merge:

1. Confirm through GitHub that the pull request is merged. Record its
   head branch, head commit, base branch, and repository default branch.
2. Check that the working tree is clean and refresh remote-tracking refs.
3. Inspect cleanup candidates. Consider the task's branch by default;
   include other branches when requested.
4. Exclude base/default branches, branches used by other worktrees,
   branches with open pull requests, and branches whose tips are not
   confirmed ancestors of the remote base.
5. Present the exact eligible branches and their current tips.
   Obtain authorization for that list unless already authorized.

After authorization:

1. Recheck the working tree, recorded tips, and cleanup eligibility.
2. Switch to the base branch, fetch with pruning, and update the local
   base by fast-forward only.
3. Delete only approved, still-eligible local branches with `git branch -d`.
   Retain and report branches that changed or cannot be deleted safely.
4. Check whether automatic branch deletion removed the remote PR branch.
   Report any remaining remote branch; local cleanup approval does not
   authorize remote deletion.
5. Report the final working-tree state and any retained candidates.

Never force-delete a branch or delete work whose integration cannot
be verified.
