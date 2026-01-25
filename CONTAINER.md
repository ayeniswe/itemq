# Container setup (Docker/Podman)

## Build + run with Docker Compose

```bash
docker compose up --build
```

The service listens on <http://localhost:8080>.

## Build + run with Podman

```bash
podman build -t itemq:local .

podman volume create itemq_data

podman run --rm -p 8080:8080 \
  -e ITEMQ_DB_PATH=/data/itemq.db \
  -e ITEMQ_DATA_DIR=/data \
  -v itemq_data:/data \
  itemq:local
```

## Data persistence

The container stores the SQLite database at `/data/itemq.db` and media uploads at
`/data/media`. Both locations are on the persistent volume (`itemq_data`).
