#!/bin/sh
# Nightly SQLite backup with rotation.
#
# Uses `.backup`, which takes a consistent snapshot of a live database — unlike
# copying the file, which can catch a half-written WAL. Runs as the same uid as
# the app so the -wal/-shm files keep their ownership.

set -eu

DB="${DB_PATH:-/data/timeme.db}"
OUT="${BACKUP_DIR:-/backups}"
AT="${BACKUP_AT:-03:30}"
KEEP="${KEEP_DAYS:-30}"

log() { echo "[backup] $(date '+%Y-%m-%d %H:%M:%S') $*"; }

run_backup() {
    if [ ! -f "$DB" ]; then
        log "no database at $DB yet, skipping"
        return 0
    fi
    stamp=$(date '+%Y%m%d-%H%M%S')
    tmp="$OUT/.timeme-$stamp.sqlite"
    final="$OUT/timeme-$stamp.sqlite.gz"

    if ! sqlite3 "$DB" ".backup '$tmp'"; then
        log "ERROR: sqlite3 .backup failed"
        rm -f "$tmp"
        return 1
    fi
    # Verify before keeping it: a backup nobody can restore is not a backup.
    if [ "$(sqlite3 "$tmp" 'PRAGMA integrity_check;')" != "ok" ]; then
        log "ERROR: integrity check failed, discarding"
        rm -f "$tmp"
        return 1
    fi

    gzip -c "$tmp" > "$final"
    rm -f "$tmp"
    log "wrote $final ($(wc -c < "$final") bytes)"

    deleted=$(find "$OUT" -name 'timeme-*.sqlite.gz' -type f -mtime "+$KEEP" -print -delete | wc -l)
    [ "$deleted" -gt 0 ] && log "pruned $deleted backup(s) older than $KEEP days"
    return 0
}

# "03" -> 3, "00" -> 0. Leading zeros would otherwise be read as octal.
dec() {
    v=${1#0}
    [ -z "$v" ] && v=0
    echo "$v"
}

seconds_until() {
    target=$(( $(dec "${AT%%:*}") * 3600 + $(dec "${AT##*:}") * 60 ))
    now=$(( $(dec "$(date '+%H')") * 3600 + $(dec "$(date '+%M')") * 60 + $(dec "$(date '+%S')") ))
    diff=$(( target - now ))
    [ "$diff" -le 0 ] && diff=$(( diff + 86400 ))
    echo "$diff"
}

mkdir -p "$OUT"
log "started; nightly at $AT, keeping $KEEP days, source $DB"

# One immediate backup so a fresh deployment is covered before the first night.
run_backup || true

while true; do
    wait_for=$(seconds_until)
    log "sleeping ${wait_for}s until the next run"
    sleep "$wait_for"
    run_backup || true
    # Guard against a same-second wake-up looping twice.
    sleep 60
done
