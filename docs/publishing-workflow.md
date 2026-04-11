# Publishing Workflow

> Stable one-command workflow for syncing the local wiki workspace into the GitHub Pages publish repository.

## Overview

This knowledge base is maintained in two separate locations:

| Location | Role |
| --- | --- |
| `/Users/weiqiangyu/Downloads/wiki` | Primary working tree. Edit wiki content here. |
| `/Users/weiqiangyu/Projects/LLM_Knowledge_Base` | Publish repository. This is the GitHub-backed repo that powers GitHub Pages. |

The publish repository exists so the public site can stay small and clean. It contains only the documentation site assets needed for GitHub Pages:

- `docs/`
- `mkdocs.yml`
- `requirements.txt`
- `.github/workflows/pages.yml`
- minimal repo metadata such as `README.md`

Raw source repos like `deepagents/`, `opencode/`, `openclaw/`, `autogen/`, and `claude_code/` stay in the working tree and are **not** pushed to the public publish repository.

## Canonical Rule

Treat `/Users/weiqiangyu/Downloads/wiki` as the source of truth.

Do not manually edit published wiki pages inside `/Users/weiqiangyu/Projects/LLM_Knowledge_Base` unless you are fixing the publishing infrastructure itself. Content changes should be made in the working tree, then synchronized.

## Publish Script

The canonical sync command is:

```bash
/Users/weiqiangyu/Downloads/wiki/scripts/sync_publish.sh
```

The script is backed by:

- `scripts/sync_publish.sh`
- `scripts/prepare_publish_mkdocs.py`

## What The Script Does

When run successfully, `sync_publish.sh` performs these steps:

1. Validates that the working tree contains `docs/` and `mkdocs.yml`.
2. Validates that the publish repository exists at `/Users/weiqiangyu/Projects/LLM_Knowledge_Base` and is a git repository.
3. Synchronizes `docs/` into the publish repository using `rsync --delete`.
4. Removes `.DS_Store` files from the published docs tree.
5. Generates a publish-safe `mkdocs.yml`.
6. Shows `git status --short`.
7. Shows `git diff --stat`.
8. Generates a default commit message if one was not provided.
9. Commits the synchronized changes.
10. Pushes the current branch to GitHub.

If there are no publishable changes, the script exits cleanly without creating a commit.

## `mkdocs.yml` Merge Rule

The working tree's `mkdocs.yml` is the editorial source, but the publish repo must always keep the deployment-specific fields required for GitHub Pages.

`prepare_publish_mkdocs.py` enforces these values in the publish repository:

```yaml
site_url: "https://weiqiangyu0528.github.io/LLM_Knowledge_Base/"
repo_url: "https://github.com/WeiqiangYu0528/LLM_Knowledge_Base"
```

Everything else in `mkdocs.yml` comes from the working tree.

That means:

- navigation changes should be made in `/Users/weiqiangyu/Downloads/wiki/mkdocs.yml`
- theme changes should be made in `/Users/weiqiangyu/Downloads/wiki/mkdocs.yml`
- publish-specific URL settings should **not** be hand-edited in the publish repo

## Standard Commands

### Preview only

Use this to see what would be published without committing or pushing:

```bash
/Users/weiqiangyu/Downloads/wiki/scripts/sync_publish.sh --dry-run
```

### Normal publish

Use this for the standard content update path:

```bash
GITHUB_TOKEN=YOUR_NEW_TOKEN \
/Users/weiqiangyu/Downloads/wiki/scripts/sync_publish.sh
```

### Custom commit message

Use this when the automatic commit message is too generic:

```bash
GITHUB_TOKEN=YOUR_NEW_TOKEN \
/Users/weiqiangyu/Downloads/wiki/scripts/sync_publish.sh \
  --message "Update Deep Agents and AutoGen wiki content"
```

### Commit locally without pushing

Use this when you want to inspect the publish repo before sending changes to GitHub:

```bash
/Users/weiqiangyu/Downloads/wiki/scripts/sync_publish.sh --no-push
```

### Alternate publish repository

Use this only when intentionally publishing to a different clone:

```bash
/Users/weiqiangyu/Downloads/wiki/scripts/sync_publish.sh \
  --publish-dir /path/to/another/LLM_Knowledge_Base
```

## Token Handling

The script can push in two ways:

1. If `GITHUB_TOKEN` is set, it uses a temporary git credential file scoped to the publish repository.
2. If `GITHUB_TOKEN` is not set, it falls back to a normal `git push origin <branch>` and relies on existing local git credentials.

Recommended usage:

```bash
export GITHUB_TOKEN=YOUR_NEW_TOKEN
/Users/weiqiangyu/Downloads/wiki/scripts/sync_publish.sh
```

Security rules:

- Never hardcode tokens into the script.
- Never store the token in committed files.
- If a token is pasted into chat or exposed elsewhere, revoke it and create a new one.

## Commit Message Strategy

If no `--message` is supplied, the script generates a default message from the changed paths:

- `Update Claude Code wiki content`
- `Update Deep Agents wiki content`
- `Update OpenClaw wiki content`
- `Update knowledge base content`
- `Update knowledge base site configuration`

If the generated message is too generic for the change, override it manually with `--message`.

## GitHub Pages Deployment Path

The publish repository is configured to deploy through GitHub Actions.

Relevant files in the publish repository:

- `/Users/weiqiangyu/Projects/LLM_Knowledge_Base/.github/workflows/pages.yml`
- `/Users/weiqiangyu/Projects/LLM_Knowledge_Base/requirements.txt`
- `/Users/weiqiangyu/Projects/LLM_Knowledge_Base/mkdocs.yml`

Deployment flow:

1. `sync_publish.sh` pushes a new commit to GitHub.
2. GitHub Actions runs the `Deploy MkDocs to GitHub Pages` workflow.
3. The workflow installs MkDocs dependencies.
4. The workflow runs `mkdocs build`.
5. The generated `site/` artifact is deployed to GitHub Pages.
6. The site updates at:
   [https://weiqiangyu0528.github.io/LLM_Knowledge_Base/](https://weiqiangyu0528.github.io/LLM_Knowledge_Base/)

## Future Agent Rules

Any future agent working in this workspace should follow these rules:

1. Edit content in `/Users/weiqiangyu/Downloads/wiki`, not in the publish repository.
2. Use `--dry-run` before any risky or broad publish.
3. Preserve the publish repository's GitHub Pages wiring.
4. Do not overwrite `site_url` or `repo_url` with blank local-development values in the publish repository.
5. Do not publish raw source repos unless explicitly asked.
6. Prefer using the sync script instead of manual `cp`, `rsync`, or hand-picked file copies.

## Troubleshooting

### The script says the publish repository is missing

Confirm this directory exists:

```bash
ls /Users/weiqiangyu/Projects/LLM_Knowledge_Base
```

If it does not exist, reclone or restore the publish repository before running the sync.

### The script shows no changes even though I edited content

Check that the edit happened under:

- `/Users/weiqiangyu/Downloads/wiki/docs/`
- or `/Users/weiqiangyu/Downloads/wiki/mkdocs.yml`

Edits outside the publish surface are intentionally ignored.

### Push fails

Likely causes:

- expired or revoked `GITHUB_TOKEN`
- missing local git credentials
- network or GitHub outage

Try:

```bash
GITHUB_TOKEN=YOUR_NEW_TOKEN \
/Users/weiqiangyu/Downloads/wiki/scripts/sync_publish.sh --dry-run
```

Then rerun without `--dry-run`.

### GitHub Pages site did not update

Check the latest workflow run in:

- `https://github.com/WeiqiangYu0528/LLM_Knowledge_Base/actions`

The publish repository, not the working tree, is what drives the public site.

## See Also

- [Claude Code Depth Standard](depth-standard.md)
- [Knowledge Base Home](index.md)
- `scripts/sync_publish.sh`
- `scripts/prepare_publish_mkdocs.py`
