#!/usr/bin/env bash
# Install YT2clips as a Claude Code skill (macOS / Linux / Git Bash).
set -e

SKILL_DIR="$HOME/.claude/skills/youtube-clipper"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=$(command -v python3 || command -v python)

echo "Installing to $SKILL_DIR"
if [ -d "$SKILL_DIR" ]; then
    read -p "Existing install found. Replace it? (y/N) " -n 1 -r; echo
    [[ $REPLY =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 0; }
    # keep the user's .env and downloaded models
    [ -f "$SKILL_DIR/.env" ] && cp "$SKILL_DIR/.env" /tmp/ytclipper.env
    rm -rf "$SKILL_DIR"
fi
mkdir -p "$SKILL_DIR"
cp -r "$SRC/SKILL.md" "$SRC/README.md" "$SRC/LICENSE" "$SRC/requirements.txt" \
      "$SRC/.env.example" "$SRC/scripts" "$SRC/references" "$SKILL_DIR/"
rm -rf "$SKILL_DIR/scripts/__pycache__"
[ -f /tmp/ytclipper.env ] && mv /tmp/ytclipper.env "$SKILL_DIR/.env"

echo "Installing Python packages..."
"$PY" -m pip install -q -r "$SKILL_DIR/requirements.txt"

echo
"$PY" "$SKILL_DIR/scripts/check_env.py" || true
echo
echo "Done. In Claude Code, say: \"Make TikToks from https://youtube.com/watch?v=...\""
