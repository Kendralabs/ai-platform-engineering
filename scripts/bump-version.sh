#!/bin/bash
#
# Generic Semantic Version Bump Script
# =====================================
# Portable version-bump tool, config-driven so it carries no project-specific
# paths. Copy this file (and bump-version.config.example) into any repo's
# scripts/ directory and fill in a .bump-version.config.
#
# Usage: ./scripts/bump-version.sh [major|minor|patch|rc|release]
#
# See VERSIONING-GENERIC.md (next to this script) for the full explanation.

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
VERSION_FILE="$PROJECT_ROOT/VERSION"
CONFIG_FILE="$PROJECT_ROOT/.bump-version.config"

# ── Load config ─────────────────────────────────────────────────────────────
#
# .bump-version.config is a plain-text file, one directive per line, paths
# relative to the repo root. Blank lines and lines starting with # are
# ignored. Two directive kinds:
#
#   file:<path>        a JSON (package.json-style "version": "...") or TOML
#                       (pyproject.toml-style version = "...") file whose
#                       version field must track VERSION. Detected by
#                       extension (.json → JSON form, .toml → TOML form).
#   builddate:<path>   a file containing a line like
#                       BUILD_DATE = "YYYY-MM-DD"  # ...
#                       whose date gets set to today whenever the version
#                       changes. Any language works as long as the line
#                       matches that shape (quotes + assignment).
#
# Example .bump-version.config:
#   file:pyproject.toml
#   file:package.json
#   file:ui/dashboard/package.json
#   builddate:src/__version__.py
#
# No config file? The script still updates VERSION and git itself; it just
# has no other files to sync, so say so and continue.

FILES=()
BUILDDATE_FILES=()

if [ -f "$CONFIG_FILE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        line="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        [ -z "$line" ] && continue
        case "$line" in
            \#*) continue ;;
            file:*) FILES+=("${line#file:}") ;;
            builddate:*) BUILDDATE_FILES+=("${line#builddate:}") ;;
        esac
    done < "$CONFIG_FILE"
else
    echo "No .bump-version.config found at $CONFIG_FILE — only VERSION and git will be updated."
    echo "See scripts/generic/bump-version.config.example to add synced files."
fi

# ── Parse semantic version ───────────────────────────────────────────────────
parse_version() {
    local version=$1
    if [[ $version =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)(-rc\.([0-9]+))?$ ]]; then
        MAJOR="${BASH_REMATCH[1]}"
        MINOR="${BASH_REMATCH[2]}"
        PATCH="${BASH_REMATCH[3]}"
        RC_NUM="${BASH_REMATCH[5]}"
    else
        echo "Invalid version format: $version (expected: major.minor.patch or major.minor.patch-rc.N)"
        exit 1
    fi
}

if [ ! -f "$VERSION_FILE" ]; then
    echo "No VERSION file found. Creating one at 0.1.0 — re-run with your intended bump type."
    echo "0.1.0" > "$VERSION_FILE"
    exit 0
fi

CURRENT_VERSION=$(cat "$VERSION_FILE" | tr -d '[:space:]')
echo "Current version: $CURRENT_VERSION"

parse_version "$CURRENT_VERSION"

# ── Determine new version ────────────────────────────────────────────────────
BUMP_TYPE="${1:-patch}"

case "$BUMP_TYPE" in
    major)
        MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0
        NEW_VERSION="$MAJOR.$MINOR.$PATCH"
        ;;
    minor)
        MINOR=$((MINOR + 1)); PATCH=0
        NEW_VERSION="$MAJOR.$MINOR.$PATCH"
        ;;
    patch)
        PATCH=$((PATCH + 1))
        NEW_VERSION="$MAJOR.$MINOR.$PATCH"
        ;;
    rc)
        if [ -z "$RC_NUM" ]; then
            RC_NUM=1
        else
            RC_NUM=$((RC_NUM + 1))
        fi
        NEW_VERSION="$MAJOR.$MINOR.$PATCH-rc.$RC_NUM"
        ;;
    release)
        if [ -z "$RC_NUM" ]; then
            echo "Not a release candidate version, already at $CURRENT_VERSION"
            exit 1
        fi
        NEW_VERSION="$MAJOR.$MINOR.$PATCH"
        ;;
    *)
        echo "Usage: $0 [major|minor|patch|rc|release]"
        exit 1
        ;;
esac

echo "New version: $NEW_VERSION"
read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 0
fi

# ── Update VERSION ───────────────────────────────────────────────────────────
echo "$NEW_VERSION" > "$VERSION_FILE"
echo "✓ Updated VERSION"

# ── Update synced version files ──────────────────────────────────────────────
CHANGED_FILES=("VERSION")

for rel in "${FILES[@]}"; do
    f="$PROJECT_ROOT/$rel"
    if [ ! -f "$f" ]; then
        echo "⚠ Skipping $rel (not found)"
        continue
    fi
    case "$f" in
        *.json)
            sed -i '' "s/\"version\": *\"[^\"]*\"/\"version\": \"$NEW_VERSION\"/" "$f"
            ;;
        *.toml)
            sed -i '' "s/^version = \"[^\"]*\"/version = \"$NEW_VERSION\"/" "$f"
            ;;
        *)
            echo "⚠ Skipping $rel (unsupported extension — only .json/.toml auto-detected; add handling if needed)"
            continue
            ;;
    esac
    echo "✓ Updated $rel"
    CHANGED_FILES+=("$rel")
done

# ── Update BUILD_DATE-style files ────────────────────────────────────────────
TODAY=$(date +%Y-%m-%d)
for rel in "${BUILDDATE_FILES[@]}"; do
    f="$PROJECT_ROOT/$rel"
    if [ ! -f "$f" ]; then
        echo "⚠ Skipping $rel (not found)"
        continue
    fi
    sed -i '' -E "s/^(BUILD_DATE[[:space:]]*=[[:space:]]*)\"[^\"]*\"(.*)$/\1\"$TODAY\"\2/" "$f"
    echo "✓ Updated $rel (BUILD_DATE=$TODAY)"
    CHANGED_FILES+=("$rel")
done

# ── Commit and tag ───────────────────────────────────────────────────────────
cd "$PROJECT_ROOT"
git add "${CHANGED_FILES[@]}" 2>/dev/null || true
git commit -m "chore: bump version to $NEW_VERSION" || true
git tag -a "v$NEW_VERSION" -m "Release $NEW_VERSION" || echo "Tag v$NEW_VERSION already exists"

echo ""
echo "✓ Version bumped from $CURRENT_VERSION to $NEW_VERSION"
echo "✓ Git commit and tag created (v$NEW_VERSION)"
echo ""
echo "Next steps:"
echo "  1. Review changes: git log --oneline -3"
echo "  2. Push to remote: git push origin <branch> && git push origin v$NEW_VERSION"
