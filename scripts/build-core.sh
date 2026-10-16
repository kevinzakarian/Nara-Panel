#!/bin/sh
set -eu
# Build the feature that official default releases do not include.
# Requires Go >= 1.26, git and network access to the official Go module sources.
version=v1.14.3
output=${1:-./dist/sing-box}
case "$output" in /*) ;; *) output="$PWD/$output" ;; esac
mkdir -p "$(dirname "$output")"
build_dir=$(mktemp -d)
trap 'rm -rf "$build_dir"' EXIT HUP INT TERM
git clone --quiet --depth 1 --branch "$version" https://github.com/SagerNet/sing-box.git "$build_dir/core"
cd "$build_dir/core"
test "$(git rev-parse HEAD)" = 7054cac5124465ffdb145870d7c01885566711b1 || { echo "Unexpected upstream commit" >&2; exit 1; }
go build -trimpath -tags with_quic,with_v2ray_api -ldflags "-s -w -X github.com/sagernet/sing-box/constant.Version=1.14.3" -o "$output" ./cmd/sing-box
"$output" version
