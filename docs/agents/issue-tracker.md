# Issue Tracker: GitHub

Issues and PRDs for this repository live as GitHub Issues. Use the `gh` CLI from
inside the clone so it infers `kyphucclv/ConMeoGauGau` from the remote.

## Conventions

- Create: `gh issue create --title "..." --body-file <file>`.
- Read: `gh issue view <number> --comments` and include labels when processing
  issue state.
- List: `gh issue list --state open --json number,title,body,labels,comments` with
  the appropriate state/label filters.
- Comment: `gh issue comment <number> --body "..."`.
- Label: `gh issue edit <number> --add-label "..."` or `--remove-label "..."`.
- Close: `gh issue close <number> --comment "..."`.

Use body files for multiline issue content; do not construct shell strings from
untrusted issue text.

## Pull Requests As A Triage Surface

External pull requests are **not** a request or triage surface for this
repository. Do not pull them into the issue queue or apply the issue triage state
machine to them. Normal pull-request review remains unaffected.

## Skill Translation

- “Publish to the issue tracker” means create a GitHub Issue.
- “Fetch the relevant ticket” means read the full GitHub Issue and comments.
- A bare `#42` can share GitHub's number space with pull requests; confirm the
  object type when ambiguity matters.
