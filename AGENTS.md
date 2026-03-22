# AGENTS

## Workflow

- Use `bd status` and `bd list` for read-only issue inspection.
- If `bd q` or other write commands fail with a Dolt connection error, restart the local server with `bd dolt start`.
- The current `.beads` setup is unstable for writes in this environment, so verify the server before relying on issue creation.

## Repo habits

- Run `gofmt -w` on edited Go files before verification.
- In this sandbox, use `GOCACHE=/tmp/gclaw-gocache` for Go commands.
- Lightweight verification that currently completes reliably:
  - `go test ./pkg/replication`
  - `go test ./pkg/swarm`
- Heavier packages such as `./cmd/gclaw`, `./pkg/agent`, and `./pkg/tools` pull a large dependency graph and may need longer timeouts than the default sandbox window.

## First-run path

- The installer is expected to handle interactive onboarding through `/dev/tty`.
- After onboarding, helper setup should complete before launching the gateway.
- The living dashboard is served from `http://127.0.0.1:18790/dashboard`.
