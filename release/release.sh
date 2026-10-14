#!/bin/sh
# Publish this source repo's HEAD as a release in the release repo (github.com/andreiverdes/bluedoc).
#
#   release/release.sh [RELEASE_CHECKOUT]     default: ../bluedoc-release next to this repo
#
# The release holds only what agents install: the skill without its examples, the plugin manifests, LICENSE and
# release/plugin-README.md as its README. It is taken from HEAD (git archive), so commit first; the working tree
# must be clean. The version is package.json's, and every manifest must carry the same one. The script commits
# and tags v<version> in the release checkout, and prints the push command; it pushes nothing itself.
set -eu

src=$(cd "$(dirname "$0")/.." && pwd)
dst=${1:-"$src/../bluedoc-release"}
remote=https://github.com/andreiverdes/bluedoc.git

cd "$src"
[ -z "$(git status --porcelain)" ] || { echo "release: commit or stash first; the release is HEAD" >&2; exit 1; }
version=$(python3 -c 'import json; print(json.load(open("package.json"))["version"])')
python3 - "$version" <<'EOF'
import json, sys
v = sys.argv[1]
found = {"plugin.json": json.load(open("plugin.json"))["version"],
         ".claude-plugin/plugin.json": json.load(open(".claude-plugin/plugin.json"))["version"]}
m = json.load(open(".claude-plugin/marketplace.json"))
found["marketplace metadata"] = m["metadata"]["version"]
found.update({f"marketplace plugin {p['name']}": p["version"] for p in m["plugins"]})
bad = {k: x for k, x in found.items() if x != v}
if bad:
    sys.exit(f"release: package.json says {v}, but " + ", ".join(f"{k} says {x}" for k, x in bad.items()))
EOF
sha=$(git rev-parse --short HEAD)

if [ ! -d "$dst/.git" ]; then
  git clone -q "$remote" "$dst" 2>/dev/null || { mkdir -p "$dst"; git -C "$dst" init -q -b main; git -C "$dst" remote add origin "$remote"; }
fi
if git -C "$dst" rev-parse -q --verify "refs/tags/v$version" >/dev/null; then
  echo "release: v$version is already released; bump the version (1.0.0-betaNN) first" >&2; exit 1
fi

# replace everything but .git with HEAD's release files
find "$dst" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
git archive HEAD -- skills ':(exclude)skills/bluedoc/examples' .claude-plugin .agents plugin.json package.json LICENSE \
  | tar -x -C "$dst"
cp release/plugin-README.md "$dst/README.md"
printf '__pycache__/\n*.pyc\n.DS_Store\n*.icons/\n' > "$dst/.gitignore"

cd "$dst"
if command -v claude >/dev/null 2>&1; then claude plugin validate . >/dev/null || { echo "release: claude plugin validate failed" >&2; exit 1; }; fi
git add -A
git commit -q -m "bluedoc $version" -m "Built from andreiverdes/bluedoc-src@$sha."
git tag -a "v$version" -m "bluedoc $version"
echo "released bluedoc $version (source $sha) in $dst"
echo "push: git -C \"$dst\" push origin main \"v$version\""
