#!/bin/sh
# Install a published Kioku standalone release for the current user.
set -eu
repo=felipemeriga/kioku
case "$(uname -s)" in Darwin) os=darwin ;; Linux) os=linux ;; *) echo 'Use install.ps1 on Windows' >&2; exit 1 ;; esac
case "$(uname -m)" in x86_64|amd64) arch=x64 ;; arm64|aarch64) arch=arm64 ;; *) echo 'Unsupported architecture' >&2; exit 1 ;; esac
version=${KIOKU_VERSION:-}
if [ -z "$version" ]; then
  version=$(curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 'https://api.github.com/repos/felipemeriga/kioku/releases?per_page=100' | sed -n 's/.*"tag_name": "cli-v\([0-9][0-9.]*\)".*/\1/p' | head -n 1)
fi
printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$' || { echo 'No CLI release found; set KIOKU_VERSION to a published version' >&2; exit 1; }
asset=kioku-$os-$arch
base=https://github.com/$repo/releases/download/cli-v$version
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
curl --fail --silent --show-error --location --retry 3 --proto '=https' --tlsv1.2 "$base/$asset" -o "$tmp/$asset"
curl --fail --silent --show-error --location --retry 3 --proto '=https' --tlsv1.2 "$base/SHA256SUMS" -o "$tmp/SHA256SUMS"
expected=$(awk -v name="$asset" '$2 == name {print $1}' "$tmp/SHA256SUMS")
if command -v sha256sum >/dev/null 2>&1; then actual=$(sha256sum "$tmp/$asset" | awk '{print $1}'); else actual=$(shasum -a 256 "$tmp/$asset" | awk '{print $1}'); fi
[ -n "$expected" ] && [ "$expected" = "$actual" ] || { echo 'Checksum verification failed' >&2; exit 1; }
chmod 755 "$tmp/$asset"
"$tmp/$asset" --version
bin=${KIOKU_INSTALL_DIR:-"$HOME/.local/bin"}
mkdir -p "$bin"
# Replace atomically on the destination filesystem, preserving a running daemon.
cp "$tmp/$asset" "$bin/.kioku-install-$$"
chmod 755 "$bin/.kioku-install-$$"
mv -f "$bin/.kioku-install-$$" "$bin/kioku"
printf 'Installed Kioku %s to %s/kioku\nEnsure %s is on PATH.\n' "$version" "$bin" "$bin"
