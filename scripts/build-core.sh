#!/bin/sh
set -eu
# Build the standard upstream capabilities plus panel traffic accounting.
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
core_os=${GOOS:-$(go env GOOS)}
core_arch=${GOARCH:-$(go env GOARCH)}
core_tags=$(cat release/DEFAULT_BUILD_TAGS_OTHERS)
if [ "$core_os" = linux ]; then
    case "$core_arch" in
        amd64|arm64) core_tags="$(cat release/DEFAULT_BUILD_TAGS),with_purego" ;;
    esac
fi
core_tags="$core_tags,with_v2ray_api"
core_ldflags=$(cat release/LDFLAGS)
go build -trimpath -tags "$core_tags" -ldflags "$core_ldflags -s -w -X github.com/sagernet/sing-box/constant.Version=1.14.3" -o "$output" ./cmd/sing-box
case "$core_os/$core_arch" in
    linux/amd64|linux/arm64)
        # The pinned Go module is verified by go.sum, including this shared library.
        cronet_dir=$(go list -m -f '{{.Dir}}' "github.com/sagernet/cronet-go/lib/linux_$core_arch")
        install -m 755 "$cronet_dir/libcronet.so" "$(dirname "$output")/libcronet.so"
        cp "$cronet_dir/LICENSE" "$(dirname "$output")/libcronet.LICENSE"
        ;;
esac
if [ "$core_os" = "$(go env GOHOSTOS)" ] && [ "$core_arch" = "$(go env GOHOSTARCH)" ]; then
    "$output" version
fi
