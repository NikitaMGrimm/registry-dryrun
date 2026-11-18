#!/usr/bin/env bash
# Installs cargo-horizon-mod from the exact reviewed engine commit in .github/horizon-rev, never a floating branch.
# The pin is read beside this script, so a job takes it from the same trusted checkout as its scripts (check.yml:
# main's, never the pull request's). A file, not a repository variable: fork pull requests get no variables.
# Trusted jobs never restore executable or Cargo caches from mod-building jobs.
set -euo pipefail
pin="$(dirname "$0")/../.github/horizon-rev"
rev="$(tr -d '[:space:]' < "$pin")"
if [[ ! "$rev" =~ ^[0-9a-f]{40}$ ]]; then
  echo "::error::$pin must hold one exact 40-character lowercase commit"
  exit 1
fi
cargo install --locked --force --git https://github.com/horizon-rust/horizon --rev "$rev" cargo-horizon-mod
