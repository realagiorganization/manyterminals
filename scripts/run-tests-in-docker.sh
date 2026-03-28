#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_TAG="${MANYTERMINALS_TEST_IMAGE:-manyterminals:test}"

docker build -f "$ROOT_DIR/docker/test.Dockerfile" -t "$IMAGE_TAG" "$ROOT_DIR"
docker run --rm "$IMAGE_TAG"
