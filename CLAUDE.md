# maritime-mcp-server

Python FastMCP server exposing maritime vessel data as MCP tools and a resource over stdio.

<!-- SHIPLINE:BEGIN -->
## Shipline

This project runs on Shipline. Work is planned, built, verified and closed in
files under `.shipline/`. Read `.shipline/config.json` before any git or
file-structure operation. It is the source of truth for branch names, protected
branches, verify commands, project conventions and the active milestone.

### Forbidden actions

These are the point of Shipline. They hold in every project.

| # | Rule |
|---|------|
| F1 | Never commit or push without explicit permission in that same message. |
| F2 | Never work directly on a branch listed in `git.protected_branches`. Always cut a working branch first. |
| F3 | Never start implementing before a plan exists in `.shipline/work/` and the user has approved it. |
| F4 | Never mark a phase complete without evidence. Paste the real command output. |
| F5 | Never widen the scope of a story beyond its plan. Out of scope items get written down, not built. |
| F6 | Never edit `.shipline/guardrails.yaml` except to append. Guardrails are retired with a reason, never deleted. |

### Project conventions

Set at init, stored in `config.json` under `conventions`. Change them there, not
here. `ship-init` writes only the lines that apply to this project.

- No emoji anywhere, in code, documents or commit messages.
- No dash punctuation inside sentences, in any copy.
- Never put assistant attribution in a commit. No `Co-Authored-By`, no session trailers, no generated-with footer.
- Commit as `ariefrsee <193463370+ariefrsee@users.noreply.github.com>`. Set it repo-locally and verify with `git log -1 --format='%an <%ae> / %cn <%ce>'` after committing, because environment variables can override git config silently. This shell exports `GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL`, which beat both git config and `git -c`, so they must be overridden in the command environment.
- One branch per story, named with the story id.

### Before implementing anything

1. Load `.shipline/guardrails.yaml` and honour every active guardrail whose `applies_to` matches the work.
2. Confirm an approved plan exists for this story and its phase is `build`.
3. Confirm the current branch is not protected.
4. Read the acceptance criteria in the plan. They are the definition of done.

### After implementing anything

1. Run every command in `verify.commands` and paste the real output.
2. Tick only the acceptance criteria that are genuinely met.
3. Update `pipeline_state` in the plan frontmatter.
4. Stop. Do not commit until asked.

### Commands

- `/ship-status` shows where every piece of work stands.
- `/ship-plan <thing>` writes a plan for one piece of work.
- `/ship-build` implements the approved plan.
- `/ship-close` writes the test script, then the retro, then extracts guardrails.
<!-- SHIPLINE:END -->
