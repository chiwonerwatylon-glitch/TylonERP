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

## Design

The interface is Bootstrap 5.3.8 (vendored under `app/static/vendor`) with a design layer in `app/static/style.css`:

- **Palette:** bottle green `#0f5c4a` on a cool sage canvas `#eef1ef`, maize `#e8b230` for low stock and today's bar,
  and a deep ink sidebar. Dark mode mirrors it. A tenant's own accent (Login page settings) replaces the green.
- **Type:** Bricolage Grotesque for headings and money figures, Instrument Sans for everything else. Both are
  self-hosted in `app/static/fonts` (SIL Open Font License) because the content security policy only allows local fonts.
- **Layout:** sidebar grouped into Sell, Records and Settings; bottom tab bar on phones; a dashboard "till" with
  30-day takings and a 14-day bar chart; status badges as soft tints; designed 403/404/429/500 pages.
- **Sign-in:** one card on the app canvas. A business page uses the business's accent or picture; the administrator
  console uses the sidebar's ink, so the two are never confused.
- **Tenant accents:** `accent_palette()` derives readable light and dark variants from any colour, so a very light or
  very dark accent still gives legible buttons, links and panels.
- **Forms:** `app/static/app.js` locks a form's button while it posts (no double sales or payments) and shows styled
  confirmation dialogs for risky actions.

## Adding stock

The **Stock** page offers five ways in. Every addition is logged under *Recent stock added* with who did it and how.

- **Barcode**: scan with the camera or type a code. Set *Units per scan* to count a whole carton with one scan. An
  unknown code asks for a name and price and registers the product.
- **Photo** and **Scent**: register a product from a picture (and a scent description); Quick sell can then match it
  by photo.
- **Manual**: type the name, price and quantity, with an optional SKU and barcode. No camera needed.
- **Import list**: upload a CSV (or paste rows) with `name, price, quantity, barcode, sku, reorder_level`. Rows that
  match an existing product by barcode, SKU or name add to its stock; new rows create products. Bad rows are skipped
  and reported by line number. A template CSV is linked on the page.

Each product row also has an **Add** box to top up its stock by hand.

### One barcode, one product

A barcode never creates a second product, however it reaches the app (`app/barcodes.py`):

- Codes are cleaned before they are stored: scanner prefixes such as `]E0`, tabs and line breaks are removed, and a
  12-digit UPC-A is stored as its 13-digit EAN-13 form. Lookups also match codes stored with or without leading zeros.
- Scanning an unknown code offers to link it to a product that has no barcode yet. Registering it under the name of
  an existing product (ignoring case and spaces) links it to that product instead of creating a copy.
- A label held in front of the camera counts once; the same code counts again only after it has left the view.
- Each scan carries an id, so a resent or double-tapped request counts once. Every counted line has **Undo**.
- **Possible duplicates** on the Stock page lists products that share a name or barcode. An admin can merge them:
  stock, sales and stock history move into the product kept.

## Android app

`android/` is an Android Studio project (Android 7.0 and later). Online it shows this web app; offline it sells,
counts stock and records payments on the phone, then uploads them through the phone API in `app/api.py`:

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/login` | Business, email and password give a token (90 days; changing the password signs phones out) |
| `GET /api/v1/catalog` | Products, clients and open debts for the phone's offline copy |
| `POST /api/v1/sync` | Changes made on the phone. Each has an `op_id`; its result is stored (`sync_ops`), so a retried upload never records twice |
| `POST /t/<slug>/mobile-session` | Signs the app's web view in with its token |

See `android/README.md` to build the APK.

## Mobile money payments

On **Quick sell** and **Sales**, choose a payment method:

- **EcoCash** charges the customer's wallet through the [EcoCash Online Payments API](https://developers.ecocash.co.zw/docs/online-payments). The customer approves with their PIN. The sale is kept only if the charge succeeds; if EcoCash does not answer, it stays *Pending* and **Check payment** looks it up. Admins can **Refund** a paid EcoCash sale (stock is returned).
- **OneMoney (NetOne)** records the customer's number and the NetOne transaction code. There is no API call: the cashier confirms the payment on the phone first.

Every tenant enables EcoCash for itself: a workspace admin opens **Payments** and enters their own merchant account (API username and password, merchant code and PIN, merchant number). Passwords and PINs are stored encrypted with a key derived from `SECRET_KEY`, so changing `SECRET_KEY` means re-entering them. Payments go to that tenant's account only; there is no shared platform account. The default URL is the sandbox; set `ECOCASH_BASE_URL` to the production URL EcoCash sends you at go-live.
