# TylonERP

Multi-tenant ERP built with Flask: stock (barcode, photo or scent recognition), quick sell, sales and receipts,
clients and debtors, per-tenant branding, and a system administrator console.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
make install
cp .env.example .env     # then edit
make run                 # http://localhost:8080
```

With no `DATABASE_URL` it uses a local SQLite file. Set `ADMIN_PASSWORD` to create the system administrator
(`ADMIN_EMAIL`, default `admin@erp.co.zw`) on first start.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Signs session cookies. Must be long and random in production. | insecure dev value |
| `DATABASE_URL` | SQLAlchemy URL (Postgres in production) | `sqlite:///tylonerp.db` |
| `COOKIE_SECURE` | `1` sends cookies over HTTPS only; use `0` for local http | `1` |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | System administrator seed | none |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | Connection pool | 10, 20 |

## Development

`make lint`, `make fmt`, `make test`, `make audit`. CI runs the same checks on every pull request.

## Layout

- `app/__init__.py`: app factory, sessions, theme, bootstrap
- `app/models.py`: tenants, users, products, clients, sales
- `app/routes.py`: sign-in and system administrator routes
- `app/workspace.py`: tenant workspace routes
- `railway.json`: Railway start command and health check (`/healthz`)

## Deployment

Railway deploys from `master`. Set `SECRET_KEY`, `DATABASE_URL` (reference the Postgres service) and
`ADMIN_PASSWORD` as service variables.

## Security settings

`app/config.py` reads every setting. In production (`ENV=production`, or any Railway environment) the app
refuses to start with the built-in dev `SECRET_KEY`, and logs warnings for a short key, SQLite, or
`COOKIE_SECURE=0`. Sign-in is limited to `LOGIN_RATE_LIMIT` (default `10 per minute`) per client IP, and every
failed sign-in shows the same message. Responses carry CSP, frame, nosniff, referrer and permissions headers,
and HSTS over HTTPS; pages are sent `Cache-Control: no-store`. The rate limiter counts in memory per gunicorn
worker; set `RATELIMIT_STORAGE_URI` to a Redis URL to share counts across workers.
