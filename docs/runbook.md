# Saathi runbook

How to set Saathi up and keep it running. This file grows with the project: each phase adds its own
section. Right now it covers **Phase 0 (Foundation)**.

## Phase 0: from empty folder to a healthy API

### 1. Tools to install

| Tool | Why | Notes |
|---|---|---|
| Git | version control | |
| Docker (Desktop or Engine) with Compose v2 | runs n8n, the API and the dashboard | `docker compose version` must work |
| `make` | the shortcuts in the Makefile | Windows: do everything inside WSL2 (Ubuntu) |
| `psql` (PostgreSQL client) | `make migrate`, `make seed` | Ubuntu: `sudo apt install postgresql-client`; macOS: `brew install libpq` |
| Python 3.12 | run tests locally | |

### 2. Accounts and keys (all free)

1. **Supabase**: create a project. Pick a region near you (Mumbai, `ap-south-1`, for India) and save the
   database password. Open the **Connect** button and copy the **Session pooler** connection string
   (port 5432). Use the pooler, not the "direct" one: the direct connection often fails on home networks
   because it needs IPv6.
2. **Gemini**: create an API key at aistudio.google.com.
3. **Telegram**: message `@BotFather`, send `/newbot`, and copy the bot token. Then message
   `@userinfobot` to get your own numeric Telegram id.
4. **GitHub**: an empty repository for the code (CI runs there).

### 3. Get the code ready

```bash
git init
cp .env.example .env            # then fill it in (step 4)
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r services/api/requirements-dev.txt
make test                       # expect: 9 passed
make lint                       # expect: no errors
```

### 4. Fill in `.env`

Open `.env` and set at least:

- `DATABASE_URL`: the session pooler string. If the password contains special characters
  (`@ : / # ? %`), URL-encode them (for example `@` becomes `%40`) and wrap the whole value in quotes.
- `SAATHI_API_KEY`: `openssl rand -hex 24`
- `N8N_ENCRYPTION_KEY`: `openssl rand -hex 32`. **Back this up in a password manager.** If you lose
  it, every credential saved in n8n becomes unreadable.
- `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `ADMIN_TELEGRAM_CHAT_ID` (your Telegram id).
- `PUBLIC_URL`: leave the placeholder for now. Phase 1 sets it.

### 5. Create the database

```bash
make migrate        # applies db/migrations/001_init.sql (run it once only)
```

Edit the three values at the top of `db/seed.sql` (your name, a one-line "about you", your Telegram id),
then:

```bash
make seed           # prints two rows: you (telegram) and Golden Tester (test)
```

Check the result in the Supabase SQL editor:

```sql
-- expect 13
select count(*) from information_schema.tables
 where table_schema = 'public' and table_type = 'BASE TABLE';

-- expect no rows (every table has row level security on)
select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity;
```

### 6. Start the stack

```bash
docker compose up -d --build api n8n    # first build takes a few minutes
make ps                                 # api and n8n should be "running" / "healthy"
curl -s localhost:8000/health
```

Expected answer: `{"status":"ok","db":true}`.

Open [http://localhost:5678](http://localhost:5678) and create the n8n owner account.

### Phase 0 is done when

- [ ] `make test` and `make lint` pass, and CI is green on GitHub
- [ ] the migration check shows 13 tables and no table without row level security
- [ ] `make seed` shows you and Golden Tester
- [ ] `/health` returns `{"status":"ok","db":true}`
- [ ] n8n opens at [http://localhost:5678](http://localhost:5678)

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `/health` returns `{"status":"degraded","db":false}` | Wrong `DATABASE_URL`, an un-encoded special character in the password, or the direct (IPv6) connection string instead of the session pooler. Also run `make migrate`: the API needs the `vector` extension. |
| `api` container keeps restarting | `make logs`. A `ValidationError` names the missing or invalid setting, for example `SAATHI_API_KEY` shorter than 16 characters. |
| `make migrate` fails with "already exists" | The migration already ran. It is a single transaction, so a failed run leaves nothing behind. To start over on a fresh project, reset the schema in the Supabase SQL editor first. |
| `make` complains about a `.env` line | A value contains `$`, `&`, `#` or spaces. Wrap it in quotes. |
| `docker compose build` reports conflicting package versions | Copy the error. The version ranges in `requirements.txt` need adjusting. |
| `port is already allocated` | Something else uses 5678, 8000 or 8501. Stop it or change the left-hand port in `docker-compose.yml`. |

## Everyday commands

| Command | What it does |
|---|---|
| `make up` / `make down` | start / stop the stack |
| `make logs` | follow all logs |
| `make test` / `make lint` | unit tests / code style |
| `make psql` | open a SQL shell on the database |
| `make backup` | dump the database into `backups/` (script arrives in a later phase) |