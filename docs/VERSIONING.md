<!-- (c) 2026 Kendra Laboratories Limited. Private and Confidential -->

# Generic Version Bump Script

A portable `bump-version.sh` any Kendra project can drop in, so every repo
(KCG, korchestrator, kiam, kfabric, k-telemetry-py, ...) bumps versions the
same way instead of each hand-rolling its own.

Unlike `scripts/bump-version.sh` at the KCG repo root — which hardcodes KCG's
specific files (`pyproject.toml`, `ui/kcg-dashboard/package.json`, etc.) —
this version takes no project-specific paths at all. It reads a small config
file telling it what to sync, so the script itself never needs editing
between projects.

## What it does

1. Reads the current version from a `VERSION` file at the repo root (semver,
   optionally with an `-rc.N` suffix).
2. Computes the next version for the bump type you asked for:
   `major`, `minor`, `patch`, `rc`, or `release` (RC → stable).
3. Writes the new version back to `VERSION`.
4. Syncs every file listed in `.bump-version.config` — JSON `"version"`
   fields and TOML `version = "..."` fields are handled automatically.
5. Optionally updates a `BUILD_DATE = "..."` line in any file you name, so a
   status/About page can show when the running version was actually cut
   (not just what the version number is).
6. Commits the changed files and creates an annotated git tag (`vX.Y.Z`).

No other repo assumptions are built in — a repo with only a `package.json`
syncs just that; a repo with no version-bearing files beyond `VERSION` itself
still gets the commit + tag.

## Setup in this repo

`scripts/bump-version.sh` and `scripts/bump-version.config.example` are
already in place.

1. Create `.bump-version.config` at the repo root from the example:
   ```bash
   cp scripts/bump-version.config.example .bump-version.config
   ```
2. Edit `.bump-version.config` to list this repo's actual version-bearing
   files (see the example file for the directive syntax).
3. Create a starting `VERSION` file if one doesn't exist yet:
   ```bash
   echo "0.1.0" > VERSION
   ```
4. Run it:
   ```bash
   ./scripts/bump-version.sh minor
   ```

## Usage

```bash
./scripts/bump-version.sh [major|minor|patch|rc|release]
```

| Bump type | Effect | Example |
|---|---|---|
| `major` | Breaking changes | `1.2.0` → `2.0.0` |
| `minor` | New features, backward compatible | `1.2.0` → `1.3.0` |
| `patch` | Bug fixes | `1.2.0` → `1.2.1` |
| `rc` | Next release candidate | `1.2.0-rc.1` → `1.2.0-rc.2` |
| `release` | Promote the current RC to stable | `1.2.0-rc.2` → `1.2.0` |

The script asks for confirmation before writing anything, and always prints
a git push reminder at the end — it never pushes on its own.

## `.bump-version.config` syntax

```
# comments and blank lines are ignored
file:pyproject.toml
file:package.json
file:ui/dashboard/package.json
builddate:src/version.py
```

- `file:<path>` — synced by extension: `.json` files get their `"version"`
  field rewritten, `.toml` files get their `version = "..."` line rewritten.
  Anything else is skipped with a warning (extend the script if a repo needs
  another format, e.g. a `Cargo.toml` is already TOML-shaped and works as-is,
  but a hand-rolled `VERSION.go` constant would need its own case).
- `builddate:<path>` — rewrites a line shaped like
  `BUILD_DATE = "2026-01-01"  # anything after this is preserved` to today's
  date. Language-agnostic: it only looks for that exact assignment shape, so
  it works the same in a Python module, a JS constants file, etc.

No config file present → the script still updates `VERSION` and makes the
git commit/tag; it just has nothing else to touch, which is correct for a
repo that keeps version state in `VERSION` alone.

## Why a separate script from KCG's own `bump-version.sh`

KCG's root `scripts/bump-version.sh` is intentionally the specific,
zero-config version for this repo — it lists KCG's five version files
directly, so running it here needs no setup. This generic version trades
that convenience for portability: every other repo gets the same behavior
without forking and hand-editing the script's internals. If KCG's own
hardcoded list ever needs to change, update `scripts/bump-version.sh`
directly rather than this file — they're intentionally two separate scripts,
not one script with an if-branch for "which repo am I in."

## Displaying the version in an app

The bump script only writes files — showing the version to users is each
app's own job. The pattern KCG's dashboard uses (see `docs/VERSIONING.md`
and `src/__version__.py` / `AboutPage.tsx`):

1. A small module reads the installed package version at runtime (e.g.
   Python's `importlib.metadata.version(...)`, or Node's own
   `require('./package.json').version`) rather than hardcoding a copy of the
   version string a second time — a hardcoded copy is exactly what drifts.
2. An API endpoint (or equivalent) serves that value live.
3. The frontend fetches it and renders it — never hardcodes its own copy of
   the version for display, even as a "fallback," without that fallback
   being clearly a last-resort default that gets overwritten the moment the
   live call succeeds.

This is the mistake this script's `BUILD_DATE` support and the config
pattern are both designed to prevent: a UI-side constant that nothing keeps
in sync with the real version, silently going stale after the next bump.
