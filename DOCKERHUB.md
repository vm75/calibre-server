# Registry publishing

A version tag on a commit belonging to `main` publishes the tested image to:

- `ghcr.io/vm75/calibre-server:VERSION`
- `docker.io/vm75/calibre-server:VERSION`

VERSION is exactly the upstream LinuxServer tag, for example `v9.15.0-ls423`.
There are no separate patch-version or latest aliases. The same version may be
retagged and republished intentionally; consumers needing immutable releases
should use an image digest. Source/base provenance is recorded in OCI labels.

## One-time repository setup

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

## What happens on a version tag

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

## Failure and retry

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
