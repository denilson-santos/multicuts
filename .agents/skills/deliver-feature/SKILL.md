---
name: deliver-feature
description: Apply the repository delivery workflow when implementing or finalizing a code change. Use GitHub Flow and Conventional Commits, create validated local commits, and require explicit user approval before pushing or opening a pull request. Do not use for read-only analysis, diagnosis, review, or status requests.
---

# Deliver Feature

Deliver related repository changes through a short-lived branch and a reviewable pull request, keeping each feature in a separate atomic commit. Preserve the user's existing work and distinguish local implementation from approval to publish the delivery.

## Start the change

Before editing repository files:

1. Inspect the working tree, current branch, remotes, and remote default branch.
2. Stop and explain the problem if usable Git metadata, a configured remote, or the remote default branch cannot be established.
3. Do not discard, stash, move, stage, commit, or absorb pre-existing user changes without explicit permission.
4. When remote access is available, fetch the remote default branch. If access is temporarily unavailable, use an existing remote-tracking ref for the known default branch and report that it could not be refreshed. Do not introduce a merge commit while synchronizing it.
5. If the current non-default branch already matches the requested change, reuse it. Otherwise, create a branch or worktree from the remote default branch, preserving any pending work.

Name new branches `<type>/<issue-id>-<slug>`, omitting the issue ID when unavailable. Use lowercase kebab-case. Choose the narrowest applicable type, normally `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`, `ci`, or `chore`.

## Continue before publication

When the user requests another feature while delivery approval is pending, continue implementation without treating the new request as approval to push or open a pull request. For related features on an unpublished branch, reuse it and rename it with `git branch -m` when its name no longer describes the combined scope. Preserve each completed feature in its own commit. Use a separate branch/worktree for independent features.

For branch renaming, amendment, and other history rewrites, an unpublished branch must never have been pushed, and the commits being rewritten must not have been shared through another branch, tag, or pull request. Check remote refs and known publication history; a missing remote branch or an upstream pointing at the base does not establish this. If publication status is uncertain, preserve the existing name and commits.

Before starting the next feature, validate and commit any completed feature using the local commit rules below. Preserve unfinished or failing work without committing it just to switch tasks. Refresh the delivery package to cover the accumulated features, current branch name, and complete commit list; an earlier package does not approve an expanded scope.

## Implement and validate

- Follow the repository's active instructions and load only the project documentation relevant to the change.
- Keep the branch and pull request focused on related changes, with a separate atomic commit for each feature and its tests/documentation.
- Add or update tests when behavior changes.
- Run the narrowest relevant checks first, followed by the repository's required validation commands when applicable.
- After a requested feature or adjustment is complete and its applicable checks pass, inspect the diff, stage only task-owned changes, recheck the staged diff, and create a local Conventional Commit without a separate confirmation. Never include unrelated pre-existing user changes or unfinished/failing work.
- Report local commit identifiers and validation results. Do not claim that a check passed unless it was run successfully.

For a follow-up adjustment to the same feature, use `git commit --amend` only when the feature commit is the branch's latest commit, was created by the agent for this task, is not a merge commit, and the branch and commit satisfy the unpublished conditions above. Validate the adjustment first and include only changes belonging to that feature. Update the commit message if necessary to describe its final behavior.

If other features have been committed afterward, or the branch has been published, create a new commit for the adjustment. Do not automatically rewrite older feature commits or pre-existing user commits. After an amendment or added commit, refresh any pending delivery package with the new identifiers, scope, and validation results.

## Releases

For release work, read the target repository's version source, release policy,
tag convention, and verification gates. Choose the next version from changes
since the previous release, applying SemVer when the repository uses it. Update
the version in a release PR when required and run the repository's version and
build checks. Ordinary feature PRs do not bump the version unless the project
policy calls for it.

Include the proposed version, tag, and intended target commit in the delivery
package. When publishing a GitHub Release, draft its description in a temporary
Markdown file at release time using the format below. Compare changes with the
previous released tag when one exists; for the first release, summarize the
shipped baseline. Use the project's changelog, merged changes, and verified
behavior as evidence.

Write for people choosing whether and how to upgrade. Lead with the main
user-visible outcome, group changes by purpose, and explain their effects
instead of listing commits or pull requests. Include exact migration steps,
new prerequisites or defaults, material security actions, and known issues or
workarounds when relevant. Omit internal maintenance and claims that are not
verified. Replace every placeholder, remove empty optional sections, and set
the release title separately. Do not commit per-version notes unless the project
requests them.

```markdown
<In one to three sentences, say what this release is, who benefits, and its main
outcome. Mention preview or development status when relevant.>

## Highlights

- **<Feature or area>:** <What users can do now and how it helps them. Add a
  documentation link when useful.>

## Fixes and improvements

- **<Area>:** <The user-visible problem addressed and the result.>

## Upgrade notes

- **Breaking changes:** <Who is affected and the exact migration steps.>
- **Requirements or configuration:** <New prerequisites, required settings, or
  changed defaults.>
- If no action or compatibility change is required, replace these bullets with:
  `No migration steps are required.`

## Security

- **<Advisory or affected component>:** <Affected versions and the action users
  should take. Link the advisory or fix; omit exploit details.>

## Known issues

- **<Issue>:** <User impact and a known workaround or status.>
```

Keep `Upgrade notes` and state explicitly when no migration is required. Remove
`Highlights`, `Fixes and improvements`, `Security`, or `Known issues` when they
have no entries.

Create the tag only after the repository's required merge and verification
gates pass. After any tag checks pass, publish the GitHub Release for the
existing remote tag using the completed temporary notes file. Confirm that the
remote tag targets the intended commit before publication. Obtain explicit
authorization for tag creation and release publication unless already given in
the session. Never move or reuse a released tag.

## Prepare the delivery package

After implementation, validation, and local commits, inspect the complete diff from the base to the branch head, confirm that intended changes are committed, and present:

- branch name and base branch;
- concise summary of the change;
- changed and untracked files intended for delivery;
- validation commands and their results, including any failures or commands that could not run;
- existing local commits with their identifiers and exact Conventional Commit messages;
- proposed pull request title, body, base branch, and draft or ready-for-review state;
- known risks, limitations, or follow-up work when relevant.

Use Conventional Commits 1.0.0 for each commit. Keep scopes optional and repository-specific. Mark breaking changes with `!` and explain them in the commit body or footer. Prefer a Conventional Commit title for the pull request so squash merges preserve the convention.

Use this exact Markdown structure for every pull request body:

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

Keep all five headings in this order. Replace the instructional placeholders and remove unused example bullets, but do not remove a section. Keep the summary to one or two short paragraphs. Describe reviewable behavior and impact under `Changes` instead of listing files or commits. Under `Validation`, list materially relevant automated and manual checks with their results, and give a reason for each relevant check that was not run. Under `Compatibility and rollout`, state `- None.` when the change has no compatibility, migration, configuration, data, or deployment impact. Under `Risks and follow-ups`, state `- None.` when no known issues remain. Put issue links, screenshots, breaking-change details, rollout notes, and other context inside the closest matching section rather than adding ad hoc headings. Focus on the final implementation, without conversational history or abandoned approaches.

Create the pull request using the exact title and body shown in the approved delivery package. Preserve Markdown with a body file or an equivalent structured tool argument rather than assembling multiline prose through fragile shell quoting.

Ask one explicit confirmation covering publication of the displayed commits, the push target, and the pull request. Local commits do not require this confirmation. Do not treat approval of implementation or additional features as publication approval.

## Publish only after approval

After the user approves the displayed delivery package:

1. Recheck that the working tree is clean and the committed scope, messages, and validation results match the approved package.
2. Push the branch to the approved remote and set its upstream.
3. Check whether a pull request already exists before creating one, especially after a failed or uncertain retry.
4. Open the pull request with the approved title, body, base branch, and review state.
5. Return the commit identifiers, validation summary, and pull request link.

Request approval again if the content, commit plan, remote, base branch, or pull request state changes materially. Report failures without inventing a successful result or creating duplicate pull requests. Never merge the pull request without separate explicit authorization.

## Clean up after merge

When the user reports that a pull request was merged, first confirm through GitHub that its state is `MERGED`, record its exact head branch and commit, base branch, and repository default branch, and check that the working tree is clean. If any check fails, stop and explain the problem.

Before asking for cleanup, refresh the remote-tracking refs and inspect all local branches, their pull request status, and `git worktree list`. Include other obsolete local branches when their tips are ancestors of the remote base (`git merge-base --is-ancestor <branch> <remote>/<base>`). A local-only branch without a pull request can qualify: a previous push is unnecessary when all its commits are already on the base. Exclude the base and default branches, branches checked out in another worktree, and branches with open or closed-unmerged pull requests. Retain and report branches whose eligibility cannot be confirmed.

Present the exact cleanup list, including the merged pull request's head and any qualifying additional local branches, record their current tips, and ask for one explicit confirmation covering that list. Explain any retained branches. The merge report alone is not approval to clean up.

After explicit confirmation:

1. Recheck that the working tree is clean. Stop if it changed; do not stash or discard changes to perform cleanup.
2. Switch to the base branch, fetch the remote with pruning, and update the local base by fast-forward only.
3. Recheck the recorded tips and cleanup eligibility. Delete only the approved local branches with `git branch -d`. Retain and report any branch that changed, no longer qualifies, or cannot be deleted safely. Never use force deletion.
4. Verify that the repository's automatic branch deletion removed the remote pull request head branch. If it remains, report it instead of deleting it without additional authorization.
5. Confirm the final working-tree state and report any remaining local branches and why they were retained.

Do not delete branches with unmerged work or unverified status. Cleanup confirmation authorizes only the exact local branches listed, not other branches or remote deletion.
