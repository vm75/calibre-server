#!/usr/bin/env bash
set -euo pipefail
project_root=$(builtin cd -- "$(dirname -- "$0")/.." >/dev/null && builtin pwd)
source "$project_root/scripts/lib.sh"
[[ $# == 4 ]] || die "Usage: $0 VERSION TESTED_IMAGE EXPECTED_COMMIT EXPECTED_TAG_OBJECT"
validate_version "$1"
container_engine
version=$1
image=$2
expected_commit=$3
expected_tag=$4
"$project_root/scripts/verify-release.sh" "$version" "$expected_commit" "$expected_tag"
expected_commit=$(git -C "$project_root" rev-parse "$expected_commit^{commit}")
image_version=$("$CALIBRE_ENGINE" image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')
image_revision=$("$CALIBRE_ENGINE" image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
[[ $image_version == "$version" && $image_revision == "$expected_commit" ]] || die 'Candidate image version/source labels do not match this release.'
for destination in "ghcr.io/vm75/calibre-server:$version" "docker.io/vm75/calibre-server:$version"; do
    "$project_root/scripts/verify-release.sh" "$version" "$expected_commit" "$expected_tag"
    "$CALIBRE_ENGINE" tag "$image" "$destination"
    "$CALIBRE_ENGINE" push "$destination"
done
