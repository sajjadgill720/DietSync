#!/bin/bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/dietsync"
export PYTHONPATH="$DIR:$DIR/app:$PYTHONPATH"
/opt/dietsync_venv/bin/"$@"
