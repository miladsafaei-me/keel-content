#!/usr/bin/env bash
# Run ONE content-pipeline render (nb2_image / figure_raster) on the prod server.
#
# The box driving generation (Windows/macOS/Linux) needs NO local Linux render
# tooling — only ssh + scp. This wrapper stages the bundle directory to the
# server, runs the requested management command inside an isolated, memory-capped
# ephemeral container (its own container so a render spike can never OOM the live
# web/gunicorn or postgres), then copies the rendered files back.
#
# Usage:
#   render_on_server.sh <local_bundle_dir> <manage.py argv...>
# Use the literal token @W wherever an in-container path to the staged dir is
# needed; the wrapper rewrites @W -> /work. Example:
#   render_on_server.sh /out/dir nb2_image --bundle @W/x.bundle.json --id img-1
#   render_on_server.sh /out/dir figure_raster --svg @W/x.figures/fig-1.svg
#
# All host/infra values are project-specific and REQUIRED via env (no defaults —
# the package carries no server identity):
#   PIPELINE_SSH_HOST     user@host of the prod server
#   PIPELINE_IMAGE        the web image ref (e.g. ghcr.io/<org>/<project>-web:latest)
#   PIPELINE_MEMORY       container memory cap (default 1500m)
#   PIPELINE_NETWORK      the podman network the DB is on
#   PIPELINE_MEDIA_VOLUME the media volume to mount (so blog_add_images etc. land in
#                         the same volume the live web/nginx serves)
#   PIPELINE_WEB_CONTAINER the live web container name (env is copied from it)
set -euo pipefail

LOCAL_DIR="${1:?usage: render_on_server.sh <local_bundle_dir> <manage.py argv...>}"
shift
[[ -d "$LOCAL_DIR" ]] || { echo "no such dir: $LOCAL_DIR" >&2; exit 1; }
[[ $# -ge 1 ]] || { echo "missing manage.py argv" >&2; exit 1; }

HOST="${PIPELINE_SSH_HOST:?set PIPELINE_SSH_HOST=user@host}"
IMAGE="${PIPELINE_IMAGE:?set PIPELINE_IMAGE=<web image ref>}"
MEMORY="${PIPELINE_MEMORY:-1500m}"
NETWORK="${PIPELINE_NETWORK:?set PIPELINE_NETWORK=<podman network>}"
MEDIA_VOLUME="${PIPELINE_MEDIA_VOLUME:?set PIPELINE_MEDIA_VOLUME=<media volume>}"
WEB_CONTAINER="${PIPELINE_WEB_CONTAINER:?set PIPELINE_WEB_CONTAINER=<web container name>}"

DIRNAME="$(basename "$LOCAL_DIR")"
REMOTE_DIR="pipeline-render/$DIRNAME"          # under the server user's HOME

# Rewrite @W -> /work in every argv token (the staged dir is mounted at /work).
ARGS=()
for a in "$@"; do ARGS+=("${a//@W//work}"); done

# The render reads image config (API key, model id, endpoint) from AiSetting in
# the DB, exactly like the live web container. Give the isolated container the
# live container's own DB + secret env (written to a 600 file on the server) and
# put it on the DB network, so that resolution works natively — no piecemeal
# fetching, no stale schema defaults.
RENDER_ENV="\$HOME/.cache/keel-render.env"
ssh "$HOST" "mkdir -p ~/.cache && podman exec $WEB_CONTAINER env \
  | grep -E '^(POSTGRES_|DJANGO_SECRET_KEY|REDIS_URL|CELERY_)' > $RENDER_ENV \
  && chmod 600 $RENDER_ENV"

# 1) stage the bundle dir up. The remote dir is keyed only on the local dir's
#    basename, so a later batch reusing that name would inherit whatever the
#    previous batch left behind — and step 3 copies the WHOLE dir back down,
#    re-injecting those stale artifacts into the live batch. Wipe before staging
#    so the remote side is always an exact mirror of this batch.
ssh "$HOST" "rm -rf ~/$REMOTE_DIR && mkdir -p ~/$REMOTE_DIR"
scp -q -r "$LOCAL_DIR/." "$HOST:~/$REMOTE_DIR/"

# 2) render inside an isolated, memory-capped, throwaway container on the DB
#    network. --entrypoint python bypasses the web entrypoint (no
#    migrate/collectstatic, no db-wait) and just runs the command. A render spike
#    is capped here and can never OOM the live web/gunicorn or postgres.
ssh "$HOST" "podman run --rm --memory=$MEMORY --network $NETWORK \
  --env-file $RENDER_ENV -w /app/backend --entrypoint python \
  -v ~/$REMOTE_DIR:/work:z -v $MEDIA_VOLUME:/app/backend/media:z \
  $IMAGE manage.py ${ARGS[*]}"

# 3) pull the rendered files (+ patched bundle json) back down
scp -q -r "$HOST:~/$REMOTE_DIR/." "$LOCAL_DIR/"
