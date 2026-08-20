#!/usr/bin/env bash
set -euo pipefail

# Dev-only maintainer script: symlink every skill in this repo into the local
# skill directories of each agent harness, so a `git pull` keeps installed
# skills current. Re-run after adding, removing, or renaming a skill.
#   - ~/.claude/skills: Claude Code
#   - ~/.agents/skills: Codex and other Agent Skills-compatible harnesses

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DESTS=("$HOME/.claude/skills" "$HOME/.agents/skills")

for dest in "${DESTS[@]}"; do
  mkdir -p "$dest"
  for skill in "$REPO"/skills/*/*/; do
    [ -f "$skill/SKILL.md" ] || continue
    name="$(basename "$skill")"
    ln -sfn "${skill%/}" "$dest/$name"
    echo "linked $dest/$name"
  done
done
