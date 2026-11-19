#!/usr/bin/env bash
set -euo pipefail
package=${1:?Usage: scripts/publish.sh kraken-cli[-bin]}
case "$package" in kraken-cli|kraken-cli-bin) ;; *) exit 2 ;; esac
: "${AUR_SSH_KEY:?Configure the aur environment secret}"
: "${AUR_KNOWN_HOSTS:?Configure verified AUR host keys}"
: "${AUR_GIT_NAME:?Configure the publishing Git name}"
: "${AUR_GIT_EMAIL:?Configure the publishing Git email}"
root=$(cd "$(dirname "$0")/.." && pwd)
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
chmod 700 "$temporary"
printf '%s\n' "$AUR_SSH_KEY" > "$temporary/key"
chmod 600 "$temporary/key"
printf '%s\n' "$AUR_KNOWN_HOSTS" > "$temporary/known_hosts"
ssh-keygen -F aur.archlinux.org -f "$temporary/known_hosts" > /dev/null
export GIT_SSH_COMMAND="ssh -F /dev/null -i $temporary/key -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$temporary/known_hosts"
git clone "ssh://aur@aur.archlinux.org/$package.git" "$temporary/aur"
cd "$temporary/aur"
git config user.name "$AUR_GIT_NAME"
git config user.email "$AUR_GIT_EMAIL"
cp "$root/packages/$package/PKGBUILD" "$root/packages/$package/.SRCINFO" .
git add PKGBUILD .SRCINFO
if git diff --cached --quiet; then
  echo "$package is already published"
  exit 0
fi
version=$(awk '/^[[:space:]]*pkgver = / {print $3}' .SRCINFO)
release=$(awk '/^[[:space:]]*pkgrel = / {print $3}' .SRCINFO)
git commit -m "Update $package to $version-$release"
git push origin HEAD:master
