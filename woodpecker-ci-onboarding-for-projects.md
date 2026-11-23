# Onboarding Your Project onto Woodpecker CI (kctl)

Kendra Labs runs one shared, self-hosted CI/CD server for all projects —
you don't stand up your own CI. This doc is everything your project needs
to hook in.

- **Dashboard:** https://kctl.kendralabs.com:9443
- **Login:** your own GitHub account (org-wide OAuth App, already
  configured — nothing for you to register)
- **Access:** restricted to admins/approved accounts. If you can't log in,
  ask to be added.

You do **not** need a new user, a new OAuth app, or a new CI agent per
project — all of that is shared infrastructure that already exists.

## What you need to do, per repo

### 1. Ask to have your repo enabled
Someone with Woodpecker admin access needs to toggle your repo on in the
UI (`https://kctl.kendralabs.com:9443`). Tell them the exact GitHub
`org/repo` name.

### 2. Add your repo's secrets
In your repo's page in the Woodpecker UI, add whatever your pipeline
needs — e.g.:
- `VPS_SSH_KEY` — deploy key, if you deploy to the VPS
- `VPS_HOST`
- any API tokens your build/test/deploy steps require

These are scoped to your repo only — other projects can't see them.

### 3. Add a `.woodpecker.yml` to your repo
Put this at the root of your repo. Start from a template rather than
writing from scratch — ask your Woodpecker admin for a copy of the
relevant one from `~/kendra-ci/templates/` on the VPS:

| Template | Use for |
|---|---|
| `compose-deploy` | Full-stack apps deployed via podman/docker-compose |
| `python-lib-ci` | Python libraries — lint + pytest |
| `node-lib-ci` | JS/TS libraries |

The syntax is close enough to GitHub Actions that if you already have
`.github/workflows/*.yml`, you can usually port it with minor changes
rather than a rewrite.

### 4. Add `docs/LIFECYCLE.md` to your repo
Copy the template from `~/kendra-ci/templates/docs/LIFECYCLE.md` and fill
it in: stack, environments, CI/CD, deploy runbook, health/monitoring,
backups, and a "known gaps" section. This file is what CAIPE's RAG
ingestion treats as the authoritative source for your repo's ops info —
keep it current as your pipeline evolves.

### 5. Verify before cutting over
Keep your existing GitHub Actions workflow (if you have one) running
until your new Woodpecker pipeline has gone green on a real push/deploy.
Don't remove the old CI until the new one is proven.

## Questions / access requests

Contact whoever administers `kendra-ci` (VPS path:
`/home/caipeadmin/kendra-ci`) to:
- get your repo enabled
- get added as an approved Woodpecker login
- get a copy of the pipeline templates
