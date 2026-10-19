#!/usr/bin/env bash
# Runs the test suite inside a Linux container, as CI does on its runner: hardcharger-server
# from ghcr.io/gizmodata/hardcharger:main (a Linux binary), the Hardcharger ADBC driver built
# from gizmodata/hardcharger-adbc at the commit pinned in .github/hardcharger-adbc.ref, and an
# S3 gateway (Versity) next to it for the S3 test.
#
#   scripts/test-in-docker.sh [pytest arguments]
#
# Needs:
#   DBT_HARDCHARGER_TEST_ADBC_SRC  a gizmodata/hardcharger-adbc checkout that has the pinned
#                                  commit (git fetch), with its Go modules downloaded on this
#                                  machine (`go mod download` in its go/ directory): the
#                                  container reads them from this machine's module cache.
#   docker, logged in to ghcr.io with read access to gizmodata/hardcharger.
# Optional: DBT_HARDCHARGER_TEST_PYTHON (default 3.14), DBT_HARDCHARGER_TEST_IMAGE (default
# ghcr.io/gizmodata/hardcharger:main), DBT_HARDCHARGER_TEST_LOWEST=1 (install the lowest
# versions pyproject.toml allows, as CI's lowest-dependencies job does).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${DBT_HARDCHARGER_TEST_ADBC_SRC:-}"
[ -n "$SRC" ] && [ -d "$SRC" ] || { echo "DBT_HARDCHARGER_TEST_ADBC_SRC must name a hardcharger-adbc checkout" >&2; exit 1; }
REF="$(tr -d '[:space:]' < "$ROOT/.github/hardcharger-adbc.ref")"
[ -n "$REF" ] || { echo ".github/hardcharger-adbc.ref is empty" >&2; exit 1; }
IMAGE="${DBT_HARDCHARGER_TEST_IMAGE:-ghcr.io/gizmodata/hardcharger:main}"
PYTHON="${DBT_HARDCHARGER_TEST_PYTHON:-3.14}"
GOMODCACHE_HOST="$(go env GOMODCACHE)"
WORK="$ROOT/.local-test"
mkdir -p "$WORK"

# The driver's source at the pinned commit (not the checkout's working tree).
git -C "$SRC" cat-file -e "$REF^{commit}" || { echo "$SRC has no commit $REF: git fetch it" >&2; exit 1; }
rm -rf "$WORK/hardcharger-adbc" && mkdir -p "$WORK/hardcharger-adbc"
git -C "$SRC" archive "$REF" | tar -x -C "$WORK/hardcharger-adbc"

# hardcharger-server out of the image.
docker pull -q "$IMAGE" >/dev/null
rm -rf "$WORK/hardcharger"
id=$(docker create "$IMAGE")
docker cp -q "$id:/opt/hardcharger" "$WORK/hardcharger"
docker rm "$id" >/dev/null
echo "hardcharger-server from $IMAGE ($(docker inspect --format '{{.Created}}' "$IMAGE"))"

TEST_IMAGE=dbt-hardcharger-test
docker build -q -t "$TEST_IMAGE" "$ROOT/tests/docker" >/dev/null

# The S3 gateway, on a network shared with the test container.
NETWORK=dbt-hardcharger-test
docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null
docker rm -f dbt-hardcharger-test-s3 >/dev/null 2>&1 || true
docker run -d --rm --name dbt-hardcharger-test-s3 --network "$NETWORK" \
  -e ROOT_ACCESS_KEY=dbt-hardcharger-test -e ROOT_SECRET_KEY=dbt-hardcharger-test-secret \
  --tmpfs /data versity/versitygw:v1.8.0 --port :9000 posix --sidecar /tmp /data >/dev/null
trap 'docker rm -f dbt-hardcharger-test-s3 >/dev/null 2>&1 || true' EXIT

docker run --rm -i --network "$NETWORK" \
  -v "$ROOT":/src \
  -v "$GOMODCACHE_HOST":/gomod:ro \
  -v dbt-hardcharger-test-gocache:/root/.cache/go-build \
  -v dbt-hardcharger-test-uv:/root/.cache/uv \
  -e GOMODCACHE=/gomod -e GOFLAGS=-mod=mod -e GOPROXY=off -e GOSUMDB=off \
  -e PYTHON="$PYTHON" -e LOWEST="${DBT_HARDCHARGER_TEST_LOWEST:-}" \
  -e DBT_HARDCHARGER_TEST_SERVER_BINARY=/src/.local-test/hardcharger/bin/hardcharger-server \
  -e DBT_HARDCHARGER_TEST_S3_ENDPOINT=dbt-hardcharger-test-s3:9000 \
  -w /src "$TEST_IMAGE" bash -euo pipefail -s -- "$@" <<'SCRIPT'
adbc=/src/.local-test/hardcharger-adbc
(cd "$adbc/go" && CGO_ENABLED=1 go build -tags driverlib -buildmode=c-shared \
   -o ../python/src/adbc_driver_hardcharger/libadbc_driver_hardcharger.so ./pkg/hardcharger)
venv=/tmp/venv
uv venv -q "$venv" --python "$PYTHON"
resolution=()
[ -n "$LOWEST" ] && resolution=(--resolution lowest-direct)
uv pip install -q --python "$venv/bin/python" "${resolution[@]}" "$adbc/python" -e "/src[test,dev]"
"$venv/bin/python" -m pytest "$@"
SCRIPT
