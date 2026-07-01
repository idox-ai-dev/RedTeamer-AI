# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| `main` branch | Yes |

We address security issues on the `main` branch only. Older tags are not patched.

---

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Email us at **security@idox.ai** with:

1. A description of the vulnerability and its potential impact.
2. Steps to reproduce or a proof-of-concept (be as specific as possible).
3. Any suggested remediation, if you have one.

We will do our best to review reports and coordinate fixes when possible, but we cannot guarantee a specific response or remediation timeline.

---

## Scope

Issues in scope for this project:

- **API server** (`cloud-redteam/api-server/`) — authentication bypass, IDOR, injection, privilege escalation.
- **Attack agent** (`cloud-redteam/attack-agent/`) — command injection via scenario payloads, path traversal.
- **Observer plugin** (`observer-plugin/`) — event data leakage, server-side request forgery via the embedded HTTP API.
- **Scenario evaluation** — prompt injection that causes the LLM evaluator to produce systematically wrong verdicts.

Out of scope:

- Vulnerabilities in third-party dependencies (report upstream).
- Attacks that require physical access to the host.
- Denial-of-service issues without meaningful security impact.

---

## Disclosure Policy

- We aim to follow a coordinated disclosure process. We ask that you give us reasonable time to investigate and address the issue before public disclosure.
- After a fix is released, we will publish a security advisory crediting the reporter (unless anonymity is requested).

---

## Security Design Notes

This platform is designed for **controlled, authorized autonomous red teaming** in isolated environments. Operators should:

- Run the platform on an isolated network segment, not exposed to the public internet.
- Rotate `BYPASS_API_KEY` and `ADMIN_TOKEN` before each engagement.
- Treat the observer event log as sensitive — it may contain tool outputs from the agent under test.
- Use strong, randomly generated tokens (e.g. `openssl rand -hex 32`).
