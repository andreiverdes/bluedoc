#!/bin/sh
# Install (or update) bluedoc as a Gemini CLI extension from this checkout: the plan gate (hooks/), its plan-mode
# policy (policies/), the /bluedoc-* commands (commands/) and the bluedoc skill with its scripts (skills/).
# Gemini reads an extension's hooks only from <extension>/hooks/hooks.json, so the extension is staged from gemini/
# plus skills/ rather than installed from the repository root (whose hooks/ are Claude Code's).
set -eu
repo=$(cd "$(dirname "$0")/.." && pwd)
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir "$stage/bluedoc"
cp -R "$repo/gemini/gemini-extension.json" "$repo/gemini/hooks" "$repo/gemini/policies" "$repo/gemini/commands" \
  "$repo/skills" "$repo/LICENSE" "$stage/bluedoc/"
find "$stage/bluedoc" -name __pycache__ -prune -exec rm -rf {} +
if [ -d "${GEMINI_CLI_HOME:-$HOME}/.gemini/extensions/bluedoc" ]; then
  gemini extensions uninstall bluedoc
fi
gemini extensions install "$stage/bluedoc" --consent
