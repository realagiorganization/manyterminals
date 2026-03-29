#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_TAG="${MANYTERMINALS_TEST_IMAGE:-manyterminals:test}"
BUILD_TIMEOUT_SECONDS="${MANYTERMINALS_DOCKER_BUILD_TIMEOUT:-30}"

build_remote_image() {
  timeout "${BUILD_TIMEOUT_SECONDS}" docker build -f "$ROOT_DIR/docker/test.Dockerfile" -t "$IMAGE_TAG" "$ROOT_DIR"
}

build_local_fallback_image() {
  echo "remote docker build failed or timed out; building local fallback image" >&2
  python3 "$ROOT_DIR/scripts/build_local_test_image.py" "$IMAGE_TAG"
}

if ! build_remote_image; then
  build_local_fallback_image
fi

docker run --rm \
  --workdir /home/standart/manyterminals \
  -e LANG=C.utf8 \
  -e LC_ALL=C.utf8 \
  -e PYTHONPATH=/opt/manyterminals-venv/lib/python3.13/site-packages \
  "$IMAGE_TAG" \
  /bin/sh -lc 'python3 -m pytest -q && python3 scripts/assert_close_empty_fixture.py tests/fixtures/live-wayland-unavailable.json tests/fixtures/live-wayland-process-tree.json'
