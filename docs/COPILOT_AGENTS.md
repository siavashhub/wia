# GitHub Copilot agents for WIA

This repo is wired up for GitHub's hosted Copilot agents. None of them require
extra code — they are toggled at the **repo / org level** in GitHub.com — but
the workflows and instruction files in this repo are what make them produce
useful output.

| Agent | Status | What enables it here |
| --- | --- | --- |
| **Copilot coding agent** | ✅ Supported | [`.github/workflows/copilot-setup-steps.yml`](../.github/workflows/copilot-setup-steps.yml) bootstraps `uv` + Python; [`.github/copilot-instructions.md`](../.github/copilot-instructions.md) and [`AGENTS.md`](../AGENTS.md) define repo conventions. |
| **Copilot code review agent** | ✅ Supported | [`.github/CODEOWNERS`](../.github/CODEOWNERS) routes reviews; the same instruction files steer review comments. |
| **Test agent** *(Copilot "tests" / Autofix tests)* | ✅ Supported | `pytest` config in root `pyproject.toml`, fixtures in `apps/wia-desktop/tests/conftest.py`, CI uploads JUnit + coverage artifacts so Copilot can read failures. |
| **Security agent** *(Copilot Autofix)* | ✅ Supported | Powered by [`codeql.yml`](../.github/workflows/codeql.yml) + [`dependency-review.yml`](../.github/workflows/dependency-review.yml) + [Dependabot](../.github/dependabot.yml). |
| **Azure SRE Agent** | ❌ Not applicable | WIA is a Windows desktop app; it has **no Azure resources** to monitor or remediate. Re-evaluate if a hosted backend is added in a future phase. |

## One-time enablement on GitHub.com

Do these once (org owner / repo admin):

1. **Settings → Code & automation → Copilot → Coding agent** → enable for the
   repo. The first run will execute `copilot-setup-steps.yml`; check the run
   logs if the agent reports a tool-missing error.
2. **Settings → Code & automation → Copilot → Code review** → enable
   *"Automatic Copilot code review"* (or add `copilot` as a default reviewer
   under branch protection for `main`).
3. **Settings → Code security**:
   - Enable **CodeQL analysis (default or advanced)** — our advanced setup
     lives in [`codeql.yml`](../.github/workflows/codeql.yml). Pick "Advanced".
   - Enable **Dependabot alerts**, **Dependabot security updates**, and
     **Dependency review**.
   - Enable **Secret scanning** + **Push protection**.
   - Enable **Copilot Autofix for CodeQL** so the security agent can open PRs.
4. **Settings → Branches** → require status checks **`ci`**, **`codeql`**, and
   **`dependency-review`** on `main`, and require a Copilot review.
5. Edit [`.github/CODEOWNERS`](../.github/CODEOWNERS) and replace
   `@your-gh-handle` with the real maintainer handle/team.

## Driving the coding agent from an issue

1. Open an issue describing the change (acceptance criteria + files to touch).
2. Assign the issue to **`@copilot`** (or hit the "Code with Copilot" button).
3. The agent opens a draft PR, runs `copilot-setup-steps.yml`, and pushes
   commits. Reply on the PR to iterate; CI + CodeQL + Copilot review will all
   run on each push.

## Local equivalents

You can run every CI gate locally before pushing:

```pwsh
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
uv run pyinstaller --noconfirm apps/wia-desktop/pyinstaller.spec
```
