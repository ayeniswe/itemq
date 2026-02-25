# ItemQ

ItemQ is a self-hostable inventory and barcode management app built with FastAPI, SQLite, HTMX, and Jinja templates. It helps you track items, generate printable barcode labels, monitor stock, and optionally sync inventory data from Notion.

## What you can do with ItemQ

- Add and manage inventory items with quantities, images, and category metadata.
- Generate barcode labels (multiple formats), preview them, and print labels as a PDF sheet.
- Filter inventory by metadata fields and creation date.
- View dashboard stats and change history (with undo/redo support).
- Connect a Notion database as an optional inventory source and sync its rows.

---

## Quick start (recommended): Docker Compose

If you just want to run ItemQ locally with persistence:

```bash
git clone <your-repo-url> itemq
cd itemq
docker compose up --build
```

Then open:

- `http://localhost:8080` (main app service from `compose.yaml`)

Data is persisted in the Docker volume `itemq_data` (`/data/itemq.db` and `/data/media` in-container).

> `compose.yaml` also includes `itemq-dev` on port `8081` if you want a second isolated instance.

---

## Self-hosting options

### Option A: Docker Compose (single host)

Use this when you want easy startup/restart and persistent volumes.

```bash
docker compose up -d --build
```

Useful lifecycle commands:

```bash
docker compose logs -f itemq
docker compose restart itemq
docker compose down
```

### Option B: Plain Docker

```bash
docker build -t itemq:local .
docker volume create itemq_data

docker run -d --name itemq \
  -p 8080:8080 \
  -e ITEMQ_DB_PATH=/data/itemq.db \
  -e ITEMQ_MEDIA_PATH=/data/media \
  -v itemq_data:/data \
  itemq:local
```

### Option C: Podman

```bash
podman build -t itemq:local .
podman volume create itemq_data

podman run --rm -p 8080:8080 \
  -e ITEMQ_DB_PATH=/data/itemq.db \
  -e ITEMQ_MEDIA_PATH=/data/media \
  -v itemq_data:/data \
  itemq:local
```

### Option D: Native Python (no container)

Use this if you prefer systemd/supervisor or direct Python deployment.

#### 1) Prerequisites

- Python 3.11+
- `pip`

#### 2) Install

```bash
git clone <your-repo-url> itemq
cd itemq
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 3) Configure paths (recommended)

```bash
export ITEMQ_DB_PATH="$PWD/data/itemq.db"
export ITEMQ_MEDIA_PATH="$PWD/data/media"
mkdir -p "$PWD/data/media/inventory" "$PWD/data/media/barcodes"
```

#### 4) Run

```bash
python server.py --host 0.0.0.0 --port 8080
```

Open `http://localhost:8080`.

---

## Configuration reference

ItemQ is configured by environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `ITEMQ_DB_PATH` | `./itemq.db` (runtime fallback) | SQLite DB file location |
| `ITEMQ_MEDIA_PATH` | `data/media` | Root directory for uploaded inventory images and generated barcodes |
| `DEV` | unset | If `1`, `true`, `yes`, or `on`, enables uvicorn reload mode |

### Storage layout

Under your media root (`ITEMQ_MEDIA_PATH`), ItemQ uses:

- `inventory/` for uploaded inventory images
- `barcodes/` for generated barcode images

---

## First-run walkthrough

1. Start ItemQ.
2. Open the app and go to **Inventory**.
3. Add a few items (name, quantity, optional metadata).
4. Go to **Generate** to select items and generate barcode labels.
5. Preview labels and use **Print** to download a PDF sheet.
6. Check **Dashboard** for counts and **History** for change events.

---

## Optional Notion integration

You can sync inventory rows from a Notion database.

### Notion requirements

Your Notion data source must include these properties:

- `Barcode` (type: `rich_text` or `title`)
- `Name` (type: `title` or `rich_text`)
- `Quantity` (type: `number`)

### Connect flow

1. In ItemQ, open **Plugins**.
2. In the Notion section, provide:
   - Integration token
   - Notion database URL
3. Click connect/sync.

Behavior notes:

- On sync, ItemQ imports rows and stores them with source `notion`.
- If a Notion row has an empty barcode, ItemQ generates one and writes it back.
- Disconnecting Notion clears notion-sourced rows from local inventory.

---

## Running behind a reverse proxy (self-hosted production)

Run ItemQ on an internal port (for example `8080`) and place Nginx/Caddy/Traefik in front for:

- TLS termination
- domain routing
- auth/rate limits (if needed)

Make sure proxy body-size/timeouts are sufficient for image uploads.

---

## Backup and restore

Back up both the SQLite DB and media files together.

### Backup (Docker volume example)

```bash
# Stop writes for consistency (recommended)
docker compose stop itemq

# Copy DB + media from the mounted volume path using a helper container
docker run --rm -v itemq_data:/data -v "$PWD":/backup alpine \
  sh -c 'tar czf /backup/itemq-backup.tgz -C /data .'

# Start again
docker compose start itemq
```

### Restore

```bash
docker compose stop itemq
docker run --rm -v itemq_data:/data -v "$PWD":/backup alpine \
  sh -c 'cd /data && rm -rf ./* && tar xzf /backup/itemq-backup.tgz -C /data'
docker compose start itemq
```

---

## Troubleshooting

- **App starts but no CSS/JS/images**: verify `/static` and `/media` are being served and volume paths are correct.
- **Barcode print fails**: generate labels first; print requires existing label images.
- **Notion connection errors**: re-check token permissions, database URL, and required property names/types.
- **Permission issues on host-mounted directories**: ensure container user/process can read/write DB and media paths.

---

## Development tips

Run with reload:

```bash
DEV=1 python server.py --host 0.0.0.0 --port 8080
```

Or use the included dev compose service:

```bash
docker compose up --build itemq-dev
```

Open `http://localhost:8081`.
