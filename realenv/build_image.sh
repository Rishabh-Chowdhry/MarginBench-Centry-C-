#!/usr/bin/env bash
# Build the device image used by the SQA campaign. If an outbound TLS-intercepting
# proxy CA is present (as in managed sandboxes), it is added to the image's trust store.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
ctx="$(mktemp -d)"
cp "$here/docker/Dockerfile" "$ctx/"
if [ -f /root/.ccr/ca-bundle.crt ]; then cp /root/.ccr/ca-bundle.crt "$ctx/ca-proxy.crt"; else : > "$ctx/ca-none.crt"; fi
docker build --network host ${HTTPS_PROXY:+--build-arg HTTPS_PROXY=$HTTPS_PROXY} -t quintet-device:1 "$ctx"
rm -rf "$ctx"
