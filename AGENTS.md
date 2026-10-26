# Project guidance

This repository builds `vm75/calibre-server` by patching the exact tagged
LinuxServer Calibre image. It adds optional persistent browser sessions while
preserving Basic/Digest authentication for OPDS clients.

## Repository map

- `patches/`: Calibre source substitutions, session implementation, browser code.
- `Containerfile`: derived image; source context is prepared by the build helper.
- `scripts/build.sh`: exact upstream pull, matching source, build, runtime tests.
- `scripts/tag.sh`, `scripts/retag.sh`: release the pushed head of `main`.
- `scripts/verify-release.sh`, `scripts/publish.sh`: release guards and publishing.
- `tests/test_release.py`: disposable Git repositories; no real registry writes.
- `tests/runtime/`: integration tests executed with the candidate's calibre-debug.
- `.github/workflows/`: CI and tag-triggered publication.

## Working commands

```sh
scripts/check.sh
CONTAINER_ENGINE=podman scripts/build.sh v9.15.0-ls423 localhost/calibre-server:check
scripts/tag.sh v9.15.0-ls423 --dry-run
```

Python 3.10+, Bash, Git, Node.js, curl, tar, and Docker or Podman are required.
GitHub Actions uses Docker; local development defaults to Podman. Runtime tests
require Calibre's bundled Python, not the host Python environment.

## Boundaries

- Keep changes simple and task-relevant; search before reading large files.
- Preserve unrelated changes and existing conventions.
- Never mount production data in tests or commit credentials/tokens.
- Preserve OPDS Basic authentication, permission checks, CSRF protection, token
  hashing, revocation, and password-change invalidation.
- A patch mismatch, build failure, or failed test must stop publication.
- Release versions come from Git tags and match upstream tags exactly.
- Retagging the same version is explicitly supported. Image tags are mutable;
  source commit/base digest labels and immutable image digests identify builds.
- Publish only from a current tag on `main`, never from pull requests.
- Keep the per-tag concurrency and pre-push stale-tag checks intact.
- No automatic production deployment is part of this repository.

## Done and documentation

Run script/release checks and relevant candidate-image tests. Review workflow
changes for credential exposure and tag races. Update only documentation made
inaccurate by the change: usage/session behavior in `README.md`, release and
registry setup in `DOCKERHUB.md`, coding/build boundaries here. Do not claim
registry publication or browser behavior without observing it.
