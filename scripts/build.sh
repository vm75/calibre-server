#!/usr/bin/env bash
set -euo pipefail
project_root=$(builtin cd -- "$(dirname -- "$0")/.." >/dev/null && builtin pwd)
source "$project_root/scripts/lib.sh"
[[ $# == 1 || $# == 2 ]] || die "Usage: $0 UPSTREAM_VERSION [LOCAL_IMAGE]"
validate_version "$1"
container_engine
version_tag=$1
local_image=${2:-localhost/calibre-server:$version_tag}
upstream_image=ghcr.io/linuxserver/calibre:$version_tag

# Pull exactly the release tag; freeze that result before any source download.
"$CALIBRE_ENGINE" pull --platform linux/amd64 "$upstream_image"
base_id=$("$CALIBRE_ENGINE" image inspect "$upstream_image" --format '{{.Id}}')
base_ref=$("$CALIBRE_ENGINE" image inspect "$upstream_image" --format '{{index .RepoDigests 0}}')
[[ $base_ref == ghcr.io/linuxserver/calibre@sha256:* ]] || die 'Could not resolve the upstream registry digest.'
upstream_digest=${base_ref##*@}
architecture=$("$CALIBRE_ENGINE" image inspect "$base_id" --format '{{.Architecture}}')
[[ $architecture == amd64 ]] || die 'Only the tested linux/amd64 architecture is supported.'
calibre_version=$("$CALIBRE_ENGINE" run --rm --network none --entrypoint /opt/calibre/calibre-debug "$base_id" \
    -c 'from calibre.constants import numeric_version; print(".".join(map(str, numeric_version)))')
[[ $calibre_version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die 'Unexpected Calibre version from upstream image.'
revision=$(git -C "$project_root" rev-parse --verify HEAD 2>/dev/null || printf development)
if [[ -n $(git -C "$project_root" status --porcelain) ]]; then revision+=-dirty; fi

build_dir=$(mktemp -d)
trap 'rm -rf -- "$build_dir"' EXIT
printf 'Upstream: %s\nResolved: %s\nCalibre: %s\nSource revision: %s\n' "$upstream_image" "$base_ref" "$calibre_version" "$revision"
curl --fail --location --show-error --silent --retry 3 \
    "https://codeload.github.com/kovidgoyal/calibre/tar.gz/refs/tags/v${calibre_version}" \
    --output "$build_dir/source.tar.gz"
tar -xzf "$build_dir/source.tar.gz" -C "$build_dir" --strip-components=1 "calibre-${calibre_version}/src"
rm "$build_dir/source.tar.gz"
cp "$project_root/Containerfile" "$project_root/LICENSE" "$project_root/.dockerignore" "$build_dir/"
cp "$project_root"/patches/* "$build_dir/"
if [[ $CALIBRE_ENGINE == docker ]]; then
    pull_option=--pull=false
    build_base=$base_ref
else
    pull_option=--pull=never
    build_base=$base_id
fi
"$CALIBRE_ENGINE" build "$pull_option" --network=none --platform linux/amd64 \
    --build-arg "BASE_IMAGE=$build_base" --build-arg "RELEASE_VERSION=$version_tag" \
    --build-arg "SOURCE_REVISION=$revision" --build-arg "UPSTREAM_IMAGE=$upstream_image" \
    --build-arg "UPSTREAM_DIGEST=$upstream_digest" \
    --iidfile "$build_dir/image-id" --file "$build_dir/Containerfile" "$build_dir"
candidate_id=$(cat "$build_dir/image-id")
for suite in test_auth.py test_remember.py; do
    "$CALIBRE_ENGINE" run --rm --network none --user abc \
        -e CALIBRE_CONFIG_DIRECTORY=/tmp/auth-test-config -e QT_QPA_PLATFORM=offscreen \
        --entrypoint /opt/calibre/calibre-debug \
        -v "$project_root/tests/runtime/$suite:/tmp/$suite:ro,Z" "$candidate_id" "/tmp/$suite"
done
# A failed patch, build, or test must never replace a previously tested tag.
"$CALIBRE_ENGINE" tag "$candidate_id" "$local_image"
printf 'Tests passed: %s\n' "$local_image"
