#!/bin/sh
# Copy default config files into the mounted config volume if they don't exist yet.
# This runs every container start so new installs get the defaults automatically.

CONFIG_DIR="/app/config"
DEFAULTS_DIR="/app/config_defaults"

mkdir -p "$CONFIG_DIR"

for file in "$DEFAULTS_DIR"/*; do
    filename=$(basename "$file")
    dest="$CONFIG_DIR/$filename"
    if [ ! -f "$dest" ]; then
        cp "$file" "$dest"
        echo "[entrypoint] Copied default $filename to $CONFIG_DIR"
    fi
done

exec python main.py
