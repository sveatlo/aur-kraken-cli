#!/usr/bin/env bash
set -euo pipefail
git diff --quiet -- packages && exit 0
version=$(awk '/^pkgver=/ {sub(/^pkgver=/, ""); print}' packages/kraken-cli/PKGBUILD)
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
branch="update/kraken-cli-$version"
state=$(gh pr list --head "$branch" --state all --json state --jq '.[0].state // ""')
if [[ -n "$state" ]]; then
  echo "An update PR already exists for $version ($state); leaving it unchanged"
  exit 0
fi
gh auth setup-git
existing=$(git ls-remote origin "refs/heads/$branch")
if [[ -n "$existing" ]]; then
  git fetch origin "refs/heads/$branch"
  if ! git diff --quiet FETCH_HEAD --; then
    echo "Existing update branch differs from the verified proposal; reconcile it manually" >&2
    exit 1
  fi
else
  git switch -c "$branch"
  git config user.name 'github-actions[bot]'
  git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
  git add packages/*/PKGBUILD packages/*/.SRCINFO
  git commit -m "Update Kraken CLI packages to $version"
  git push origin "$branch"
fi
gh pr create --base master --head "$branch" \
  --title "Update Kraken CLI to $version" \
  --body "Verified all release archives with the pinned upstream Minisign key. Review clean x86_64 build and smoke-test results for each package before merging. ARM runtime remains untested. Packages publish independently after merge."
