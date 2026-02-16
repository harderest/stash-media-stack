#!/bin/bash

set -a && source .env && set +a

# Fix provision dir ownership and setgid so containers don't break each other's perms
sudo chown -R ${PUID}:${PGID} ./provision/
sudo find ./provision/ -type d -exec chmod g+s {} +

sudo chown -R $USER:$USER ${DATA_ROOT}/*/*parr*
sudo chmod -R 777 ${DATA_ROOT}/*/*parr* &

docker compose down
docker compose up -d --build

# Wait for stash to be healthy before running sync
echo "Waiting for Stash to be healthy..."
timeout 120 bash -c "until curl -sf http://localhost:${STASH_PORT}/; do sleep 3; done"
echo "Stash is ready."

TTL_WEEKS=1 python ./sync_stashdb_to_tpdb_whisparr_stashapp.py

curl -X POST "http://localhost:${STASH_PORT}/graphql" \
  -H 'content-type: application/json' \
  -H "ApiKey: ${STASH_API_KEY}" \
  --data-raw '{"operationName":"MetadataClean","variables":{"input":{"dryRun":false}},"query":"mutation MetadataClean($input: CleanMetadataInput!) {\n  metadataClean(input: $input)\n}"}'

docker compose logs -f
