#!/usr/bin/env bash
set -euo pipefail
package=${1:?Usage: scripts/validate.sh kraken-cli[-bin]}
case "$package" in kraken-cli|kraken-cli-bin) ;; *) exit 2 ;; esac
root=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$root/.build"
output=$(mktemp -d "$root/.build/$package.XXXXXX")
echo "Build output: $output"
docker run --rm --cpus=2 --memory=12g \
  -v "$root:/repo:ro" -v "$output:/out" \
  archlinux:base-devel bash /repo/scripts/container-check.sh build "$package"
docker run --rm --cpus=2 --memory=2g \
  -v "$root:/repo:ro" -v "$output:/out:ro" \
  archlinux:base bash /repo/scripts/container-check.sh smoke "$package"
