# Security model and gaps

## Implemented
- API-key authentication (hash-only storage, constant-time compare), three roles, per-user run isolation (other users get 404).
- Path-traversal protection: run ids are regex-validated, downloadable file names are whitelisted.
- Strict CSP (`default-src 'self'`), no external assets, `no-store` caching, frame denial.
- Generated code is AST-screened (only `cadquery`/`math` imports, no `open/eval/exec/__import__`, no dunder attributes), executed in a separate `python -I` process with a stripped environment, restricted builtins, memory limit (default 4 GB, `SHIELDCAD_SANDBOX_MEM_MB`), file-size limit, CPU limit, wall-clock timeout (default 90 s) and its own session. Tested: infinite loops are killed, memory bombs are contained, blocked imports fail even if the AST screen is bypassed.
- **Network isolation:** when the host allows it, every job runs in an empty network namespace (`unshare --net`: only loopback exists; verified by test). Each report records whether isolation was active (`report.sandbox`).
- Brute-force lockout (10 bad keys per 5 minutes per IP, configurable), per-user generation rate limit (20/min), API key expiry (`--days`) and rotation (`shieldcad-admin rotate-key`).
- LLM repair loop tested against a mock OpenAI-compatible server: wrong geometry and malicious code are both rejected and fed back for repair; the loop gives up after the retry cap.
- Tamper-evident audit log with concurrent-writer locking.
- Container hardening in docker-compose: non-root, read-only filesystem, all capabilities dropped, memory and pid limits.

## NOT implemented (do before a pilot touches controlled data)
1. **Stronger sandbox isolation.** Process + rlimits + network namespace is a solid layer but not a security boundary against a determined attacker (filesystem is still visible to the job, no seccomp filter). For LLM-written code on controlled data add per-job container or gVisor/Firecracker, seccomp and read-only mounts. Template-generated code is trusted.
2. SSO (OIDC/SAML) and MFA. A TLS reverse proxy config exists (`deploy/Caddyfile`) but is untested. Rate-limit state is in memory, so use a shared store if you run several workers.
3. Encrypted storage at rest; backup and retention policy; audit log shipping to write-once storage.
4. Dependency pinning and SBOM; signed releases and an offline update channel.
5. Independent penetration test.
6. The Docker and Caddy files have not been built or run in the authoring environment (no Docker available there).
7. Run storage is file-based; move to a database with backups before multi-site use.

## Compliance (get professional advice)
- ITAR/EAR: who on your team can access customer data, where servers and staff are, how updates are delivered. Ask an export-controls lawyer before the first pilot.
- Certification path (CMMC, ISO 27001 or national equivalent) once a paying customer requires it.
- Positioning: drafting assistant. A qualified engineer reviews and approves every output.
