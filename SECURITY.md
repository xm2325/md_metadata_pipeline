# Security policy

## Supported versions

Security fixes are made on `main` and are intended for the next immutable container release. There
is currently no supported production release. Once production publication begins, the support
policy must identify the supported image digest and dataset snapshot explicitly.

## Reporting a vulnerability

Do not disclose suspected vulnerabilities, credentials, private data, or exploit details in a
public issue. Contact repository owner `@xm2325` through an established private channel, or use a
private GitHub security advisory if private vulnerability reporting is enabled for the repository.

Include the affected commit, image or dataset digest, reproduction conditions, potential impact,
and whether a credential or personal/restricted data may have been exposed. Reports are reviewed
on a best-effort basis; this project does not currently promise a response or remediation SLA.

If a credential may have leaked, revoke or rotate it immediately; do not wait for code remediation.
Production promotion must stop until affected artifacts have been identified and replaced.
