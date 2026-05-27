#!/bin/bash
DB_PATH="${DATABASE_FILE:-/app/data/finnish_paradigm.sqlite}"
BACKUP_DIR="$(dirname "$DB_PATH")/backups"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/fp_backup_$TIMESTAMP.sqlite"
MAX_BACKUPS=30

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_PATH" ]; then
    echo "Database not found at $DB_PATH"
    exit 1
fi

sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

if [ $? -eq 0 ]; then
    echo "Backup created: $BACKUP_FILE"
    ls -t "$BACKUP_DIR"/fp_backup_*.sqlite | tail -n +$((MAX_BACKUPS + 1)) | xargs -r rm
    echo "Backups retained: $(ls "$BACKUP_DIR"/fp_backup_*.sqlite 2>/dev/null | wc -l)"
else
    echo "Backup failed"
    exit 1
fi
