#!/usr/bin/env bash
set -euo pipefail
mode=${1:?}
package=${2:?}
case "$package" in kraken-cli|kraken-cli-bin) ;; *) exit 2 ;; esac
export LC_ALL=C.UTF-8
if [[ "$mode" == build ]]; then
  pacman -Syu --noconfirm --needed python minisign namcap sudo shellcheck actionlint git
  shellcheck /repo/scripts/*.sh
  (cd /repo && actionlint .github/workflows/*.yml)
  python -m unittest discover -s /repo/tests -v
  useradd --create-home builder
  printf 'builder ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/builder
  install -d -o builder -g builder /build
  cp /repo/packages/"$package"/{PKGBUILD,.SRCINFO} /build/
  chown -R builder:builder /build
  cd /build
  version=$(awk '/^pkgver=/ {sub(/^pkgver=/, ""); print}' PKGBUILD)
  runuser -u builder -- python /repo/scripts/update.py --verify-only --package "$package" --version "$version"
  runuser -u builder -- makepkg --printsrcinfo > /tmp/SRCINFO
  diff -u .SRCINFO /tmp/SRCINFO
  export CARGO_BUILD_JOBS=2
  runuser -u builder -- makepkg --syncdeps --noconfirm --cleanbuild
  namcap PKGBUILD ./*.pkg.tar.zst | tee /tmp/namcap.log
  if grep -q ' E: ' /tmp/namcap.log; then
    exit 1
  fi
  cp ./*.pkg.tar.zst /out/
elif [[ "$mode" == smoke ]]; then
  pacman -Syu --noconfirm
  shopt -s nullglob
  archives=(/out/"$package"-[0-9]*-x86_64.pkg.tar.zst)
  [[ ${#archives[@]} == 1 ]]
  pacman -U --noconfirm "${archives[0]}"
  useradd --create-home smoke
  for command in kraken kraken-mcp kraken-shell; do
    ldd "/usr/bin/$command" | tee "/tmp/$command.libraries"
    if grep -q 'not found' "/tmp/$command.libraries"; then exit 1; fi
    runuser -u smoke -- env -i HOME=/home/smoke PATH=/usr/bin \
      timeout 30 "$command" --help > "/tmp/$command.help"
    test -s "/tmp/$command.help"
  done
  runuser -u smoke -- env -i HOME=/home/smoke PATH=/usr/bin \
    timeout 30 kraken --version | grep -F "$(pacman -Q "$package" | awk '{sub(/-[^-]*$/, "", $2); print $2}')"
else
  exit 2
fi
