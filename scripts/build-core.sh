#!/bin/sh
set -eu
# Build the standard upstream capabilities plus panel traffic accounting.
# Requires the pinned compatible Go toolchain, Python 3 and Git.
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# A pipe falls back on transport/server errors too; commas only handle 404/410.
export GOPROXY="${GOPROXY:-https://proxy.golang.org|direct}"
export GOSUMDB="${GOSUMDB:-sum.golang.org}"
export GOMAXPROCS="${GOMAXPROCS:-2}"
export GOGC="${GOGC:-50}"
build_jobs=${NARA_BUILD_JOBS:-1}
case "$build_jobs" in ""|*[!0-9]*|0) echo "NARA_BUILD_JOBS must be a positive integer" >&2; exit 1 ;; esac
version=v1.14.3
output=${1:-./dist/sing-box}
case "$output" in /*) ;; *) output="$PWD/$output" ;; esac
mkdir -p "$(dirname "$output")"
log=${NARA_BUILD_LOG:-$(dirname "$output")/build.log}
# Build logs contain dependency diagnostics; keep them private after failures too.
umask 077
: >> "$log"
chmod 600 "$log"
printf '[NARA] Build diagnostics: %s\n' "$log"
printf '[NARA] Downloading dependencies before compilation; parallel build jobs: %s\n' "$build_jobs"
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
# Resolve only dependencies for the selected platform/tags, not all platform libs.
python3 "$script_dir/build-step.py" --label 'Download core dependencies' --log "$log" --attempts 3 --timeout 900 --quiet-stdout -- go list -mod=readonly -deps -tags "$core_tags" ./cmd/sing-box
printf '[NARA] Dependencies ready. Verifying module checksums...\n'
python3 "$script_dir/build-step.py" --label 'Verify module cache' --log "$log" -- go mod verify
python3 "$script_dir/build-step.py" --label 'Compile Sing-box' --log "$log" -- go build -mod=readonly -p "$build_jobs" -trimpath -tags "$core_tags" -ldflags "$core_ldflags -s -w -X github.com/sagernet/sing-box/constant.Version=1.14.3" -o "$output" ./cmd/sing-box
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
