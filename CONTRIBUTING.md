# PR rules

1. **No direct pushes to `main`.** Every change goes through a pull request from a branch.
2. **Branch names:** `feat/<name>`, `fix/<name>`, or `chore/<name>`.
3. **One concern per PR.** Keep PRs small enough to review in a few minutes.
4. **Fill in the PR template** — what, why, how to test.
5. **Never commit secrets.** `SARVAM_API_KEY` lives only in `.env`, which is gitignored.
6. **CI must pass** (`.github/workflows/ci.yml`) before merge.
7. **Squash merge**, with auto-merge enabled so the PR lands as soon as checks pass. The branch is deleted after merge.

## Running locally

```bash
pip3 install -r requirements.txt
cp .env.example .env   # fill in the keys
uvicorn server:app --reload
```

Accounts use Supabase Auth, so `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` are required to sign in.
Sign-up creates users already confirmed (no email step).

## Deploying

1. Run `supabase/schema.sql` in the Supabase SQL editor (safe to re-run after schema changes).
2. Deploy on Render with `render.yaml` (Docker), or run the `Dockerfile` on any host.
3. Set `SARVAM_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` as environment variables.
