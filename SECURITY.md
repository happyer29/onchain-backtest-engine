# Security Policy

## Supported versions

Before the first tagged release, security fixes are accepted for the current
`main` branch. After release, `main` and the latest published `0.1.x` series are
supported. Older development snapshots may require artifact preparation again
and do not automatically receive an in-place migration.

## Reporting a vulnerability

Use **Security → Report a vulnerability** in the GitHub repository. This opens
a private security advisory without disclosing details publicly.

If private vulnerability reporting has not been enabled yet, do not create a
public issue. Contact a maintainer privately through the contact on their
GitHub profile and request a secure reporting channel.

Include:

- The affected version or commit.
- Minimal reproduction steps.
- The expected impact.
- A safe proof of concept, when necessary.
- A possible fix or mitigation.

Do not send real credentials, private keys, seed phrases, a complete `.env`,
private indexer dumps, or another person's personal data. Use fictitious or
revoked values.

## What qualifies as a security issue

- Bypassing localhost, Host/Origin, CSRF, or request-size protections.
- Path traversal or arbitrary reads of local artifacts.
- Leaking a secret, endpoint, raw traceback, or large execution artifact to a
  browser, API, or log.
- Unsafe deserialization or execution of user-supplied code.
- Violating artifact integrity/publication, job authority, or privilege
  boundaries.
- A dependency vulnerability with an applicable exploit path.

Ordinary strategy defects, configuration questions, and feature requests may
be reported through the issue templates.

## Deployment note

The Control API must remain on `127.0.0.1`/`::1`. Remote access is allowed only
through an authenticated TLS reverse proxy or a VPN/SSH tunnel. Read-only
ClickHouse access without verified TLS or a verified tunnel requires a separate
local opt-in; that flag does not make the connection secure.

---

Language: **English** · [Русский](SECURITY.ru.md)
