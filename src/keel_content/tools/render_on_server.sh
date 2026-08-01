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
# UNIQUE per invocation. Keying the remote dir on the local dir's basename alone
# made every concurrent render of the same batch share one remote dir, and step 3
# copied the WHOLE dir back down — so one agent's download could overwrite a
# sibling agent's freshly patched bundle with the copy it had staged moments
# earlier. That loss is silent: the bundle simply lacks its hero or its images.
REMOTE_DIR="pipeline-render/$DIRNAME.$$-$(date +%s%N)"   # under the server user's HOME

# Rewrite @W -> /work in every argv token (the staged dir is mounted at /work).
ARGS=()
for a in "$@"; do ARGS+=("${a//@W//work}"); done

# The render reads image config (API key, model id, endpoint) from AiSetting in
# the DB, exactly like the live web container. Give the isolated container the
# live container's own DB + secret env (written to a 600 file on the server) and
# put it on the DB network, so that resolution works natively — no piecemeal
# fetching, no stale schema defaults.
# Written per invocation and read once by --env-file; a single shared path would
# let one render read it while a concurrent one truncates it mid-write.
RENDER_ENV="\$HOME/.cache/keel-render.$$-$(date +%s%N).env"
ssh "$HOST" "mkdir -p ~/.cache && podman exec $WEB_CONTAINER env \
  | grep -E '^(POSTGRES_|DJANGO_SECRET_KEY|REDIS_URL|CELERY_)' > $RENDER_ENV \
  && chmod 600 $RENDER_ENV"

# 1) stage the bundle dir up (the dir is single-use, so it starts empty and can
#    never inherit a previous batch's artifacts), then drop a marker so step 3
#    can tell which files this render actually produced.
ssh "$HOST" "rm -rf ~/$REMOTE_DIR && mkdir -p ~/$REMOTE_DIR"
scp -q -r "$LOCAL_DIR/." "$HOST:~/$REMOTE_DIR/"
ssh "$HOST" "touch ~/$REMOTE_DIR/.render-marker"

# 2) render inside an isolated, memory-capped, throwaway container on the DB
#    network. --entrypoint python bypasses the web entrypoint (no
#    migrate/collectstatic, no db-wait) and just runs the command. A render spike
#    is capped here and can never OOM the live web/gunicorn or postgres.
ssh "$HOST" "podman run --rm --memory=$MEMORY --network $NETWORK \
  --env-file $RENDER_ENV -w /app/backend --entrypoint python \
  -v ~/$REMOTE_DIR:/work:z -v $MEDIA_VOLUME:/app/backend/media:z \
  $IMAGE manage.py ${ARGS[*]}"

# 3) pull back ONLY what this render wrote (+ the bundle json it patched), never
#    the whole staged mirror — anything else in the dir may have been updated
#    locally by a sibling agent while this render was running.
CHANGED="$(ssh "$HOST" "cd ~/$REMOTE_DIR && find . -type f -newer .render-marker -printf '%P\n'")"
for f in $CHANGED; do
  mkdir -p "$LOCAL_DIR/$(dirname "$f")"
  scp -q "$HOST:~/$REMOTE_DIR/$f" "$LOCAL_DIR/$f"
done

# 4) the staging dir is single-use — leave nothing behind to accumulate or leak.
ssh "$HOST" "rm -rf ~/$REMOTE_DIR $RENDER_ENV"
