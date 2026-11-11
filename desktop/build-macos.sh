#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
npx --yes @tauri-apps/cli@2.12.4 build --config desktop/tauri.conf.json --bundles app
