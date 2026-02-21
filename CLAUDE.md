# Stash Media Stack

Self-contained Docker Compose stack for adult media management with automated scraping, downloading, and organization.

## Services Overview

| Service | Port | Domain | Credentials |
|---------|------|--------|-------------|
| Stash | 9999 | stash.${DOMAIN} | Set in .env / provision configs |
| qBittorrent | 9996 | stash-qbittorrent.${DOMAIN} | Set in provision/qbittorrent/ |
| Deluge | 8112 | stash-deluge.${DOMAIN} | Set in provision/deluge/ |
| Prowlarr | 9697 | stash-prowlarr.${DOMAIN} | Set on first login |
| Whisparr | 6969 | whisparr.${DOMAIN} | Set on first login |
| WhisparrV1 | 6961 | whisparrv1.${DOMAIN} | Set on first login |
| XBVR | 9997 | xbvr.${DOMAIN} | (no auth) |
| FlareSolverr | 8191 | stash-flaresolverr.${DOMAIN} | (internal) |

## Quick Start

```bash
cp .env.example .env
# Edit .env with your domain, paths, and API keys
./start.sh
```

## Pre-Configured Credentials

Credentials are pre-configured in the `provision/` config files:
- **qBittorrent**: username/password in `provision/qbittorrent/qBittorrent/qBittorrent.conf`
- **Deluge**: password hash in `provision/deluge/config/web.conf`
- **Stash**: API key + username/password hash in `provision/stash/config/config.yml`
- **Prowlarr/Whisparr**: API keys in their respective `config.xml` files

API keys are also set in `.env` for scripts that need them.

## Architecture

```
+------------------------------------------------------------------+
|                        Traefik (public network)                   |
|  *.${DOMAIN} -> containers via Host header routing                |
+------------------------------------------------------------------+
                              |
+-----------------------------+------------------------------------+
|                     stash network (internal)                      |
|                                                                   |
|  +-----------+    +-------------+    +-----------+                |
|  |FlareSolverr|   | qBittorrent |    |  Deluge   |               |
|  |   :8191   |    |   :8080     |    |  :8112    |               |
|  +-----------+    +-------------+    +-----------+                |
|        |                |                  |                      |
|        v                v                  v                      |
|  +-----------+    +---------------------------+                   |
|  | Prowlarr  |--->| Whisparr / WhisparrV1     |                  |
|  |   :9696   |    | :6969 / :6969             |                  |
|  +-----------+    +---------------------------+                   |
|                              |                                    |
|                              v                                    |
|  +-----------+    +-----------+    +---------------+              |
|  |   XBVR    |    |   Stash   |    | stash-watcher |             |
|  |   :9999   |    |   :9999   |<---|   (sync)      |             |
|  +-----------+    +-----------+    +---------------+              |
|                                                                   |
+-------------------------------------------------------------------+
```

## Data Paths

| Path | Purpose |
|------|---------|
| `./provision/` | Service configuration data |
| `${DATA_ROOT}` | Media files and torrents |
| `${REMOTE_APPDATA}` | Generated content and backups |

### Provision Structure

```
provision/
├── deluge/config/        # Deluge daemon config
├── qbittorrent/          # qBittorrent config
├── prowlarr/             # Prowlarr config + indexer definitions
├── whisparr/             # Whisparr V2 config
├── whisparrV1/           # Whisparr V1 config
├── stash/
│   ├── config/           # Stash config + database
│   ├── plugins/          # Stash plugins
│   ├── blobs/            # Binary blob storage (gitignored)
│   ├── metadata/         # Metadata files
│   └── cache/            # Cache files
└── xbvr/
    ├── config/           # XBVR config
    └── data/             # XBVR data
```

## Service Integration

### Download Flow

1. **Prowlarr** aggregates indexers and provides search to Whisparr
2. **Whisparr** manages downloads and sends to qBittorrent/Deluge
3. **qBittorrent/Deluge** downloads to `/data/torrents-stash/`
4. **stash-watcher** monitors and syncs with Stash

### Metadata Flow

1. **Stash** scrapes metadata from StashDB and ThePornDB
2. **stash-watcher** syncs metadata between services
3. **XBVR** provides VR-specific metadata

## Connecting Services

### Prowlarr -> Download Clients

Add download clients in Prowlarr Settings -> Download Clients:

**qBittorrent:**
- Host: `stash-qbittorrent`
- Port: `8080`
- Username/Password: as configured in provision

**Deluge:**
- Host: `stash-deluge`
- Port: `8112`
- Password: as configured in provision

### Prowlarr -> Whisparr

Add Whisparr as application in Prowlarr Settings -> Apps:

**Whisparr V2:**
- Prowlarr Server: `http://stash-prowlarr:9696`
- Whisparr Server: `http://stash-whisparr:6969`
- API Key: from `provision/whisparr/config.xml`

### FlareSolverr

FlareSolverr is used by Prowlarr to bypass Cloudflare:
- URL: `http://stash-flaresolverr:8191`

## Permission Management

All provision directories use:
- **UMASK=002**: Group always gets write access
- **setgid bit**: New files inherit GID 1000 regardless of creator
- **stash-watcher runs as UID 1000**: Not root

The `start.sh` script reapplies ownership and setgid on every startup.

## Backup

Daily encrypted backups via `offen/docker-volume-backup`:
- Schedule: Daily at midnight
- Destination: `${REMOTE_APPDATA}/backups/stash-stack/`
- Encryption: GPG with passphrase in `.env`
- Retention: 30 days

## Troubleshooting

### Container Permissions

All LinuxServer.io containers use `PUID=1000` and `PGID=1000`. If you have permission issues:

```bash
sudo chown -R 1000:1000 ./provision/
sudo find ./provision/ -type d -exec chmod g+s {} +
```

### Reset qBittorrent Password

Delete the password line from:
```
./provision/qbittorrent/qBittorrent/qBittorrent.conf
```

### Reset Deluge Password

Edit `./provision/deluge/config/web.conf` and set `first_login` to `true`.

### Check Service Health

```bash
docker compose ps
docker compose logs -f [service-name]
```

## GPU Support (Stash)

Stash is configured with NVIDIA GPU passthrough for hardware transcoding:
- Devices: `/dev/nvidia*`
- Environment: `NVIDIA_VISIBLE_DEVICES=all`

If you don't have NVIDIA GPU, remove the `devices` section from the stash service.

## Network Requirements

- External network `public` must exist (created by Traefik)
- All services connect to both `public` (for Traefik) and `stash` (internal)

Create the public network if it doesn't exist:
```bash
docker network create public
```
