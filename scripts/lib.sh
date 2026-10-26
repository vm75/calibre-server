#!/usr/bin/env bash
# Shared validation only; callers enable strict shell options.
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
validate_version() {
    [[ ${1:-} =~ ^v?[0-9]+\.[0-9]+\.[0-9]+(-ls[0-9]+)?$ ]] ||
        die 'Use an exact LinuxServer version tag, for example v9.15.0-ls423 (not latest).'
}
container_engine() {
    CALIBRE_ENGINE=${CONTAINER_ENGINE:-podman}
    [[ $CALIBRE_ENGINE == docker || $CALIBRE_ENGINE == podman ]] || die 'CONTAINER_ENGINE must be docker or podman.'
    command -v "$CALIBRE_ENGINE" >/dev/null || die "$CALIBRE_ENGINE is not installed."
}
