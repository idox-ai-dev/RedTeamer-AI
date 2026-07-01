# Contributing to iDox.ai Red Team™

Thank you for your interest in contributing. **iDox.ai Red Team™** is an autonomous agentic AI red teaming platform; contributions that improve scenario coverage, evaluation quality, observer fidelity, or deployment docs are especially welcome.

---

## Ways to Contribute

- **New attack scenarios** — YAML files that test OWASP LLM categories
- **Bug fixes** — backend (Python), observer plugin (TypeScript), or Web UI
- **Documentation** — clarify setup, architecture, or scenario format
- **Evaluation improvements** — better LLM evaluation prompts or rule logic

---

## Development Setup

### API Server

```bash
cd cloud-redteam/api-server
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your credentials
python main.py
```

### Observer Plugin

```bash
cd observer-plugin
npm install
npm run build          # outputs dist/index.js
```

### Attack Agent

```bash
cd cloud-redteam/attack-agent
pip install -r requirements.txt
cp .env.example .env
python main.py
```

---

## Adding a Scenario

1. Create a YAML file in `cloud-redteam/api-server/scenarios/` following the schema below.
2. The API server seeds built-in scenarios on startup — restart to pick up your file.
3. Test it from the Web UI: trigger the scenario and verify the evaluation result.

### Scenario schema

```yaml
id: ASI-XXX               # unique, uppercase, prefixed ASI-
name: Short description
type: agent_attack
owasp_mapping:
  - "OWASP LLM0X - Category Name"
input:
  user_goal: "adversarial user prompt"
  injected_instruction: ""   # optional injected payload
expected:
  decision: block            # block | allow
assertions:
  - tool_call_captured
  - unsafe_action_not_executed
evaluation:
  guidance: |
    Describe what the evaluator should look for:
    PASS condition — what good agent behavior looks like.
    FAIL condition — what a successful attack looks like.
```

---

## Pull Request Guidelines

- **One concern per PR** — a scenario addition, a bug fix, or a refactor; not all three.
- **English** in all code, comments, docstrings, commit messages, and PR descriptions.
- Keep commit messages concise: `fix: ...`, `feat: ...`, `docs: ...`.
- Do not include `.env` files, database files (`*.db`), or generated scenarios in commits.
- Run through a basic smoke test before opening a PR:
  1. API server starts without errors.
  2. At least one scenario can be triggered and evaluated.

---

## Code Style

- Python: standard PEP 8, no type-annotation enforcement currently.
- TypeScript: project uses `@ts-nocheck` in the observer plugin — keep it consistent.
- No comments that describe *what* the code does; only add comments for non-obvious *why*.

---

## Issue Reporting

Open a GitHub issue with:
- A short title describing the problem.
- Steps to reproduce.
- Expected vs. actual behavior.
- Relevant log output (scrub any credentials before pasting).

---

## Security Issues

Please **do not** open a public issue for security vulnerabilities. See [SECURITY.md](SECURITY.md) for responsible disclosure instructions.

---

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
