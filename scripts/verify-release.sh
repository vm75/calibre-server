#!/usr/bin/env bash
set -euo pipefail
project_root=$(builtin cd -- "$(dirname -- "$0")/.." >/dev/null && builtin pwd)
source "$project_root/scripts/lib.sh"
[[ $# == 3 ]] || die "Usage: $0 VERSION EXPECTED_COMMIT EXPECTED_TAG_OBJECT"
validate_version "$1"
[[ $2 =~ ^[0-9a-f]{40}$ && $3 =~ ^[0-9a-f]{40}$ ]] || die 'Expected full Git commit/tag SHA values.'
builtin cd -- "$project_root" >/dev/null
tag_ref=refs/tags/$1
expected_commit=$(git rev-parse "$2^{commit}")
[[ $(git rev-parse HEAD) == "$expected_commit" ]] || die 'Checkout does not match the release event.'
git fetch --quiet --no-tags origin '+refs/heads/main:refs/remotes/origin/main'
git merge-base --is-ancestor "$expected_commit" refs/remotes/origin/main || die 'Release commit is not on main.'
remote_line=$(git ls-remote --refs origin "$tag_ref")
remote_oid=${remote_line%%[[:space:]]*}
[[ $remote_oid == "$3" ]] || die 'Release tag was moved or deleted; refusing to publish this stale run.'
[[ $(git rev-parse "$3^{commit}") == "$expected_commit" ]] || die 'Release tag does not point to the expected commit.'
printf 'Verified %s at %s on main; remote tag is current.\n' "$1" "$expected_commit"
