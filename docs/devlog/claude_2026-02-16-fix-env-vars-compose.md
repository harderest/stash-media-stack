# Fix env vars and compose for service interop

**Date:** 2026-02-16

## Problems Found

1. **`.env` `STASH_BASE_URL=http://stash:9999`** - Used docker service name, but `start.sh` runs `sync_stashdb_to_tpdb_whisparr_stashapp.py` on the host where `stash` hostname doesn't resolve. Changed to `http://localhost:9999`.

2. **`start.sh` curl used `https://stash.fhijazi.me/graphql`** - Went through Cloudflare/Traefik roundtrip unnecessarily. Changed to `http://localhost:${STASH_PORT}/graphql` for reliability.

3. **`start.sh` had `docker compose down -v`** - The `-v` flag removes anonymous volumes, which is risky. Removed the flag.

4. **stash-watcher missing `DATA_ROOT` env var** - `stash_watcher.py` uses `DATA_ROOT` to create torrent directories (`torrents-stash/.downloading/`, etc.). Added `DATA_ROOT=/data` since data is mounted at `/data` in the container.

5. **`start.sh` health check used subshell with single quotes** - `STASH_PORT` wouldn't expand inside `bash -c '...'`. Changed to double quotes.

## Key Design: Dual URL Context

The `.env` file is sourced by both:
- **Host scripts** (`start.sh`, `sync_stashdb_to_tpdb_whisparr_stashapp.py`) - need `localhost` URLs
- **Docker containers** (via docker-compose.yml) - need docker service name URLs

Solution: `.env` uses `localhost` (for host scripts), and `docker-compose.yml` hardcodes docker service names in the stash-watcher environment section (overriding `.env`).

## Permission Hardening

**Problem:** Containers running as root (stash, stash-watcher) could create files with restrictive ownership/perms, breaking access for containers that drop to UID 1000 (prowlarr, qbittorrent, whisparr).

**Analysis:**
- `DATA_ROOT` (`/mnt/d2`) is NTFS-FUSE: always `777 root:root`, permissions not enforceable. No fix needed.
- `./provision/` is ext4: permissions matter. Each service has its own subdir, but stash-watcher mounts ALL of `./provision/`.

**Fixes applied:**
1. **UMASK 022 → 002**: Group always gets write access. All lsio/hotio containers use GID 1000.
2. **stash-watcher `user: "1000:1000"`**: No longer runs as root. It's just a Python script, doesn't need root.
3. **setgid bit on all provision dirs**: New files/dirs inherit group ownership (GID 1000) regardless of which process creates them.
4. **`start.sh` reapplies on every startup**: `chown -R 1000:1000 ./provision/` + `find -type d -exec chmod g+s` runs before containers start.
