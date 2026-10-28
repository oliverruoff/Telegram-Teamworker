#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -f .env ]; then
    echo "Copy .env.example to .env and set token, group ID and operator ID first."
    exit 1
fi
docker build -t telegram-teamworker .
mkdir -p workspace
# Replace only this project's named container, after a successful image build.
if docker container inspect telegram-teamworker >/dev/null 2>&1; then
    docker stop telegram-teamworker
    docker rm telegram-teamworker
fi
docker run -d --name telegram-teamworker \
    --env-file .env \
    -v "$PWD/workspace:/workspace" \
    --restart unless-stopped \
    --shm-size=256m \
    telegram-teamworker
