# calibre-server

[![CI](https://github.com/vm75/calibre-server/actions/workflows/ci.yml/badge.svg)](https://github.com/vm75/calibre-server/actions/workflows/ci.yml)
[![Publish version](https://github.com/vm75/calibre-server/actions/workflows/publish.yml/badge.svg)](https://github.com/vm75/calibre-server/actions/workflows/publish.yml)
[![Docker Pulls](https://img.shields.io/docker/pulls/vm75/calibre-server)](https://hub.docker.com/r/vm75/calibre-server)
[![Docker Image Size](https://img.shields.io/docker/image-size/vm75/calibre-server/v9.15.0-ls423)](https://hub.docker.com/r/vm75/calibre-server)
[![GitHub release (latest by date)](https://img.shields.io/github/v/tag/vm75/calibre-server?label=latest%20tag)](https://github.com/vm75/calibre-server/tags)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)

LinuxServer Calibre with optional remembered browser sessions. It retains the
upstream desktop, configuration, and libraries, and preserves HTTP Basic/Digest
authentication for OPDS clients such as Moon+ Reader and Librera.

Images are published under the **same version tag** as the upstream image:

```
ghcr.io/vm75/calibre-server:v9.15.0-ls423
docker.io/vm75/calibre-server:v9.15.0-ls423
```

These are the release destinations, not a claim that a given tag has already
been published. Only `linux/amd64` is currently built and tested. There is no
automatically moving `latest` tag.

## Using the image

Use a published version in place of `ghcr.io/linuxserver/calibre` / `linuxserver/calibre`,
keeping your existing PUID, PGID, TZ, `/config`/library mounts, and port mappings.
Enable the optional browser login with the exact public HTTPS origin:

```yaml
services:
  calibre-server:
    image: docker.io/vm75/calibre-server:v9.15.0-ls423
    container_name: calibre-server
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Etc/UTC
      - CALIBRE_REMEMBER_ORIGIN=https://books.example.com
    volumes:
      - /path/to/calibre/config:/config
      - /path/to/calibre/library:/books
    ports:
      - 8080:8080
      - 8081:8081
    restart: unless-stopped
```

Authentication and users must still be enabled/configured in Calibre's Content
server settings. Use Basic mode behind an HTTPS reverse proxy. The proxy must
preserve Host and Authorization; it must not replace Authorization with an
empty value. No additional nginx authentication is needed.

Visit `/auth/login` and use an existing Calibre account. Choose:

| Choice | Server/session behavior |
| --- | --- |
| This browser session | Session cookie; server expiry after at most 24 hours. Browser session restore may restore session cookies. |
| 30 days | Persistent cookie and fixed 30-day server expiry. |
| Until I sign out | No server expiry; revocable persistent login. |

Permanent login renews its browser cookie during use. Chrome caps individual
cookies at 400 days, so an unused browser may still expire it; clearing browser
data or leaving a private session also removes it. On first use, fully exit a
browser that has old native Basic credentials cached, then reopen the form.
Explicit Authorization headers retain precedence over cookie authentication.

Use **Account · sign out** or `/auth/sessions` to sign out, revoke a listed
session, or sign out of all remembered browsers. Changing a password or deleting
the account revokes its remembered sessions. This does not revoke Basic passwords
saved in separate reader applications.

OPDS clients continue using `/opds` and the same Calibre credentials. Without
CALIBRE_REMEMBER_ORIGIN, remembered-session routes are disabled and native HTTP
authentication remains available.

## Storage and security

Sessions use the existing `/config` volume. Their separate mode-0600 SQLite
file is named after the users database with `.sessions` appended (normally
`/config/.config/calibre/server-users.sqlite.sessions`). It stores token hashes,
username, duration, timestamps, expiry, and a keyed credential fingerprint—not
raw bearer tokens or copied passwords. Keep it with your configuration backups.

Cookies are host-only, Secure, SameSite=Lax, and HttpOnly for the bearer token.
Cookie-authenticated writes require CSRF tokens, including GET-capable database
mutations. The browser integration supplies these for same-origin XHR/fetch.
Library restrictions and read-only permissions are checked using the restored
Calibre username. The login form validates its canonical origin and uses
Calibre's login-failure banning. HTTP origins are allowed only on loopback for
isolated tests. Authentication endpoints and the generated library page are
not cacheable; the latter explicitly declares its HTML content type.

## Registry publishing

A version tag on a commit belonging to `main` publishes the tested image to:

- `ghcr.io/vm75/calibre-server:VERSION`
- `docker.io/vm75/calibre-server:VERSION`

VERSION is exactly the upstream LinuxServer tag, for example `v9.15.0-ls423`.
There are no separate patch-version or latest aliases. The same version may be
retagged and republished intentionally; consumers needing immutable releases
should use an image digest. Source/base provenance is recorded in OCI labels.

### One-time repository setup

GitHub Actions must be enabled. GHCR uses the automatic GITHUB_TOKEN with the
workflow's `packages: write` permission; no separate GHCR PAT is required. If a
pre-existing GHCR package belongs to another repository, grant this repository
write access in its package settings. GHCR packages can initially be private;
set the package visibility to public after its first publish if desired.

Create Docker Hub repository `vm75/calibre-server` and configure these Actions
secrets in `vm75/calibre-server`:

| Secret | Value |
| --- | --- |
| DOCKERHUB_USERNAME | Docker Hub account authorized to push to vm75/calibre-server. |
| DOCKERHUB_TOKEN | Docker Hub access token with write access to that repository. |

Do not commit tokens or put them in command-line arguments. Configure them at
<https://github.com/vm75/calibre-server/settings/secrets/actions>. The publish
workflow fails if either secret is absent; pull-request CI does not need secrets.
If repository rules prohibit tag updates, allow the release operator to update
these version tags so `scripts/retag.sh` can perform the requested retry workflow.

### What happens on a version tag

1. Verify tag syntax, checkout/event consistency, and ancestry on main.
2. Check registry secret configuration and run release-helper tests.
3. Pull `ghcr.io/linuxserver/calibre:VERSION`, freeze its digest, download the
   matching Calibre source, apply the patch, build, and run isolated auth tests.
4. Log in to both registries without exposing passwords in arguments.
5. Verify the tag is still current, then push the tested image to GHCR; recheck
   the tag again before pushing the same image to Docker Hub.

Tag pushes trigger GitHub Actions directly; a GitHub Release object is not
required. Helpers use annotated tags with unique attempt metadata, so retagging
the same version/commit still generates a new push event. They push only the
tag; commit/push main before running them.

### Failure and retry

If a patch, build, or test fails, nothing is published by that run. Correct code
on main and run `scripts/retag.sh VERSION`; do not invent a new upstream version.
Superseded runs are cancelled and stale-tag guards prevent a completed old build
from proceeding as the current release.

Publishing to two registries is not a single atomic transaction. A registry
outage or access error can leave only one updated. Fix credentials/access and
retag the same version, including at the same commit, to publish both again.
Cancel an obsolete run if needed and inspect Actions logs before retrying.

Confirm success in the [Actions page](https://github.com/vm75/calibre-server/actions)
and inspect both registry tags. For a deployment, replace the image in your
existing Compose/Quadlet configuration with a published tag or digest and keep
CALIBRE_REMEMBER_ORIGIN set. Retagging a registry image does not restart running
containers; explicitly pull/recreate them when ready.

## Build and test locally

Requirements: Bash, Git, Python 3.10+, Node.js, curl, tar, and Podman or Docker.
No production configuration, users, or books are required for tests.

```sh
scripts/check.sh
scripts/build.sh v9.15.0-ls423 localhost/calibre-server:check
# Or use Docker:
CONTAINER_ENGINE=docker scripts/build.sh v9.15.0-ls423 localhost/calibre-server:check
```

The build helper pulls the exact upstream version, resolves its digest, detects
the embedded Calibre version, and downloads matching official source. It requires
each source substitution to match once, checks binary/source versions, preserves
compiled resources, and precompiles Qt forms. It tests the candidate as `abc`
with isolated temporary users/libraries before assigning the requested local
image tag. A failed build/test does not replace that local tag.

The runtime suite covers Basic/Digest/OPDS, embedded-server startup, login modes,
restarts, expiry and permanent renewal, hashed token storage, CSRF, session
revocation/ownership, API/GUI password changes, account removal, permissions,
and explicit HTML responses. Release-helper tests use disposable Git remotes.

## Release and retry

Push committed fixes to `main`, then tag its head with an upstream version:

```sh
git switch main
git push origin main
scripts/tag.sh v9.15.0-ls423
```

The tag must exist on `ghcr.io/linuxserver/calibre`. Full build tags such as
`v9.15.0-ls423` are recommended. The workflow pulls precisely that tag and, only
after patching/building/testing, publishes that same tag to both registries.

If patching fails, fix the source substitutions/code, commit and push main, then:

```sh
scripts/retag.sh v9.15.0-ls423
```

Both helpers require a clean checkout of `main` at exactly `origin/main`.
`tag.sh` refuses an existing tag; `retag.sh` requires one and uses a lease to
replace only the expected remote tag. Retagging also works at the same commit
to retry transient build/registry failures. Append `--dry-run` to either helper
to validate without changing a tag.

CI builds/tests the known-compatible version on main/PRs without publishing.
Version-tag pushes trigger publication. Per-tag concurrency cancels superseded
runs; current tag/main checks run before publication and before each push.
No public image is pushed by a failed patch/test. Since a version may be rebuilt,
pin an image digest when you need an immutable deployment. OCI labels identify
the source commit and exact upstream image/digest.

No workflow deploys to your running Calibre service. Docker Hub repo overview
and repository description are documented in [DOCKERHUB.md](DOCKERHUB.md).

## License

The patch project is [GPL-3.0](LICENSE). Calibre is developed by Kovid Goyal and
contributors; the base image is maintained by LinuxServer.io. Their projects
and bundled components retain their own notices/licenses. Matching Calibre
source is obtained from `https://github.com/kovidgoyal/calibre` during builds.
