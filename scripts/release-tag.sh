#!/usr/bin/env bash
set -euo pipefail
project_root=$(builtin cd -- "$(dirname -- "$0")/.." >/dev/null && builtin pwd)
source "$project_root/scripts/lib.sh"
[[ $# == 2 || ( $# == 3 && $3 == --dry-run ) ]] || die "Usage: $0 create|retag VERSION [--dry-run]"
mode=$1
version=$2
[[ $mode == create || $mode == retag ]] || die 'Unknown tag operation.'
validate_version "$version"
builtin cd -- "$project_root" >/dev/null
[[ $(git symbolic-ref --quiet --short HEAD) == main ]] || die 'Check out main before tagging.'
[[ -z $(git status --porcelain) ]] || die 'Commit or remove all working-tree changes before tagging.'
git fetch --quiet --no-tags origin '+refs/heads/main:refs/remotes/origin/main'
head_commit=$(git rev-parse HEAD)
[[ $head_commit == "$(git rev-parse refs/remotes/origin/main)" ]] || die 'Push main first; local HEAD must equal origin/main.'
tag_ref=refs/tags/$version
remote_line=$(git ls-remote --refs origin "$tag_ref")
remote_oid=${remote_line%%[[:space:]]*}
local_oid=$(git rev-parse --verify "$tag_ref" 2>/dev/null || true)
if [[ $mode == create ]]; then
    [[ -z $remote_oid && -z $local_oid ]] || die 'Tag already exists. Use scripts/retag.sh to rebuild the same version.'
else
    [[ -n $remote_oid ]] || die 'Remote tag does not exist. Use scripts/tag.sh for its first release.'
fi
printf '%s %s at main %s\n' "$mode" "$version" "$head_commit"
if [[ ${3:-} == --dry-run ]]; then
    printf 'Dry run: no tag or remote ref changed.\n'
    exit 0
fi
# A nonce makes a retry at the same commit a real tag update, even in one second.
attempt=$(python3 -c 'import secrets; print(secrets.token_hex(8))')
message=$(printf 'Build LinuxServer Calibre %s\n\nMain commit: %s\nAttempt: %s' "$version" "$head_commit" "$attempt")
if [[ $mode == retag ]]; then
    git tag -f -a "$version" "$head_commit" -m "$message"
else
    git tag -a "$version" "$head_commit" -m "$message"
fi
new_oid=$(git rev-parse "$tag_ref")
# Update just this tag, and only if nobody changed it since our remote read.
if ! git push "--force-with-lease=$tag_ref:$remote_oid" origin "$tag_ref:$tag_ref"; then
    if [[ -n $local_oid ]]; then
        git update-ref "$tag_ref" "$local_oid" "$new_oid"
    else
        git update-ref -d "$tag_ref" "$new_oid"
    fi
    die 'Tag push failed; the local tag was restored. Fetch/check the remote before retrying.'
fi
printf 'Pushed %s. Watch: https://github.com/vm75/calibre-server/actions\n' "$version"
