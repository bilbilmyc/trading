# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |

## Default Security Posture

This is a **personal use, localhost-first** project. By default:

- API listens on `0.0.0.0:8000` (change to `127.0.0.1` for local-only)
- No API auth (any client on the machine can call any endpoint)
- API keys stored in plain text in `.env` (excluded by `.gitignore`)
- SQLite database at `data/trading.sqlite3` (no encryption, no backup)

**Do not expose the service to a public network without first reading [docs/security.md](docs/security.md) and enabling all recommended mitigations.**

## Reporting a Vulnerability

Please **do not** file a public issue for security problems.

Use GitHub Security Advisories:

1. Go to <https://github.com/bilbilmyc/trading/security/advisories/new>
2. Fill in the title, description, and reproduction steps
3. Submit privately

You should receive an initial response within 7 days. Critical issues will be patched ahead of the next regular release.

## Scope

In scope:

- Server-side: API key handling, SQL injection, auth bypass, XSS in any returned HTML
- LLM: prompt injection vulnerabilities, data leakage through prompts
- Trading: race conditions in order placement, price manipulation via stale data

Out of scope:

- Issues in upstream dependencies (report to those projects)
- Issues requiring physical access to the host
- Theoretical issues with no practical exploit path

## Mitigations to Enable Before Public Exposure

If you must deploy this beyond localhost:

1. **Set `AUTH_API_KEY`** — see [docs/security.md](docs/security.md#启用鉴权)
2. **Use a reverse proxy** (nginx/Caddy) for TLS termination
3. **Restrict bind address** to `127.0.0.1` or your private subnet
4. **Move `.env` to a secret manager** (AWS Secrets Manager, HashiCorp Vault)
5. **Enable SQLite backup** (cron + off-site copy)
6. **Run the test suite** before each deploy (`uv run pytest`)
7. **Monitor audit events** — `GET /api/v1/events/recent` shows all critical state changes
