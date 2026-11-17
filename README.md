# ShopEase Order Management Service

An independent FastAPI service for creating and managing orders. It owns its
order database and communicates with Authentication, User Management, and
Product Catalog services over HTTP only; it does not copy user or product
master records.

## Project layout

```text
app/
  core/          Settings and JWT authorization
  database/      SQLAlchemy engine, base, and session dependency
  models/        Orders, order items, and durable inventory-operation state
  routers/       Order and order-item HTTP endpoints
  schemas/       Request and response validation
  services/      Order workflows and User/Product service clients
alembic/         Database migrations
tests/           Focused API workflow tests
```

## Requirements and local setup

Python 3.11+, MySQL 8+, and the dependencies in `requirements.txt` are
required.

1. Copy `.env.example` to `.env` and set the database password, the JWT
   signing key shared with the Authentication Service, and the User and
   Product service URLs. Never commit `.env` or real credentials.
2. Create the `shopease_order_db` MySQL database (or configure `DB_NAME`).
3. Install dependencies and apply migrations:

   ```powershell
   python -m pip install -r requirements.txt
   alembic upgrade head
   ```

4. Start the API:

   ```powershell
   uvicorn app.main:app --reload
   ```

   Swagger UI is at `http://localhost:8000/docs`. `/health` is a liveness
   check; `/health/ready` also checks the database.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `APP_ENV`, `DEBUG` | Runtime environment and debug flag | `development`, `false` |
| `ORDER_SERVICE_PORT` | Host port published by Docker Compose | `8000` |
| `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | This service's MySQL connection | `localhost:3306`, `root`, empty password, `shopease_order_db` |
| `JWT_SECRET_KEY` | Shared HS256 signing key used to validate access tokens | Empty; set before authenticated use |
| `JWT_ALGORITHM` | JWT algorithm | `HS256` |
| `AUTH_SERVICE_URL` | Informational URL for the Authentication Service; validation is local | Empty |
| `USER_SERVICE_URL` | User Management Service base URL | Empty |
| `USER_PROFILE_PATH_TEMPLATE` | Profile lookup path, with `{user_id}` placeholder | `/api/users/{user_id}` |
| `USER_ADDRESS_PATH_TEMPLATE` | Saved-address lookup path, with `{user_id}` and `{address_id}` placeholders | `/api/users/{user_id}/addresses/{address_id}` |
| `PRODUCT_SERVICE_URL` | Product Catalog Service base URL | Empty |
| `PRODUCT_PATH_TEMPLATE` | Product lookup path, with `{product_id}` placeholder | `/api/products/{product_id}` |
| `INVENTORY_RESERVATIONS_PATH` | Atomic reservation endpoint | `/api/inventory/reservations` |
| `SERVICE_TIMEOUT_SECONDS` | Timeout for User/Product HTTP requests | `5` |
| `TAX_RATE` | Tax fraction, from `0` to `1` | `0.18` |
| `SHIPPING_CHARGE` | Flat shipping amount | `50.00` |

The local JWT contract assumed here is a signed HS256 token with a numeric
`sub` user ID, a string `role` (`customer` or `admin`), and a valid expiry.
Missing or invalid credentials return 401; customer access to another
customer's order returns 403; only admins can change order status.

## External service contracts assumed

The services' API specifications were not present in this repository. These
are the explicit contracts the clients currently implement; configure the path
templates where needed or adapt the clients to the actual service APIs before
deployment.

### User Management Service

The service sends the caller's bearer token to both:

```http
GET {USER_SERVICE_URL}/api/users/{user_id}
GET {USER_SERVICE_URL}/api/users/{user_id}/addresses/{address_id}
Authorization: Bearer <access-token>
```

The profile response must contain the authenticated user's `id`; an explicitly
inactive profile is rejected. The address response is either an address object or:

`{ "data": { "address": {...} } }`.
The address must contain `recipient_name`, `phone_number`, `address_line1`,
`city`, `state`, `postal_code`, and `country`; `address_line2` is optional.
If the response includes `id` or `user_id`, those values are checked against
the requested address and authenticated owner. The validated fields are saved
as an immutable order snapshot.

### Product Catalog Service

Product lookup is:

```http
GET {PRODUCT_SERVICE_URL}/api/products/{product_id}
Authorization: Bearer <access-token>
```

The response must include `id`, `name`, `sku`, `price`, `is_active`, and
`available_stock` (or `stock`), optionally wrapped in `data` or `data.product`.
The API rejects unknown/inactive products, malformed responses, and requested
quantities greater than the returned stock.

Stock is then reserved in one atomic batch:

```http
POST {PRODUCT_SERVICE_URL}/api/inventory/reservations
Authorization: Bearer <access-token>
Idempotency-Key: <operation_id>
Content-Type: application/json

{
  "operation_id": "<operation_id>",
  "items": [{"product_id": 1, "quantity": 2}]
}
```

The Product Catalog must treat each operation ID as idempotent and reserve the
whole batch atomically. A 409 means the batch was not reserved. Other failures
may be ambiguous (the server could have committed before a timeout), so the
same client `Idempotency-Key` must be reused when retrying order creation.

Release uses a separate durable operation ID:

```http
POST {PRODUCT_SERVICE_URL}/api/inventory/reservations/{reservation_id}/release
Authorization: Bearer <access-token>
Idempotency-Key: <release_operation_id>
Content-Type: application/json

{"operation_id": "<release_operation_id>"}
```

Repeated release calls with that operation ID must not restore stock twice.
The inventory service must retain idempotency records long enough to cover
order retries. This service does not connect to either service's database.

## Database schema

The service owns `orders` and `order_items`. Monetary amounts use
`DECIMAL(12,2)`. Orders have a unique order number and a JSON shipping-address
snapshot; order items have product name, SKU, and unit-price snapshots. The
order-to-items relationship is one-to-many with cascading deletion.

`inventory_operations` stores durable reservation/release operation IDs,
request hashes, idempotency keys, payloads, and states. It allows retries to
reuse the exact same operation after an ambiguous external response. The
idempotency key is unique per user. A rejected atomic reservation marks the
operation failed and removes its incomplete order record.

To inspect connectivity and the order tables after migration:

```powershell
python test_db.py
```

## API endpoints

All order endpoints require `Authorization: Bearer <access-token>`.

| Method | Endpoint | Access |
| --- | --- | --- |
| `POST` | `/api/orders/` | Authenticated customer; requires an `Idempotency-Key` header |
| `GET` | `/api/orders/` | Customer's own orders; admins can list all |
| `GET` | `/api/orders/{order_id}` | Owner or admin |
| `GET` | `/api/orders/number/{order_number}` | Owner or admin |
| `GET` | `/api/orders/{order_id}/items` | Owner or admin |
| `PATCH` | `/api/orders/{order_id}/status` | Admin only |
| `POST` | `/api/orders/{order_id}/cancel` | Owner or admin |

The create request accepts `items` (`product_id`, `quantity`),
`shipping_address_id`, and optional `notes`. Prices, discounts, tax, shipping,
and ownership are never accepted from the request. Reuse an `Idempotency-Key`
for retries of the same create request; reusing it for different request data
returns 409. Order listing supports `page`, `page_size` (maximum 100),
`order_status`, `created_from`, and `created_to`.

Examples:

```http
POST /api/orders/
Authorization: Bearer <access-token>
Idempotency-Key: checkout-2026-001
Content-Type: application/json
```

```json
{
  "items": [
    {"product_id": 1, "quantity": 2},
    {"product_id": 3, "quantity": 1}
  ],
  "shipping_address_id": 5,
  "notes": "Please deliver during evening hours"
}
```

```http
GET /api/orders/?page=1&page_size=20&order_status=PENDING
GET /api/orders/?created_from=2026-01-01T00:00:00&created_to=2026-01-31T23:59:59
```

## Status and cancellation workflow

Initial order and payment statuses are `PENDING`. Allowed administrator
transitions are:

```text
PENDING -> CONFIRMED -> PROCESSING -> SHIPPED -> DELIVERED
    |           |
    +-> CANCELLED
                +-> CANCELLED
```

Only the cancellation endpoint can set `CANCELLED`; the status endpoint
rejects cancellation so it cannot bypass inventory release. Customers may
cancel their own `PENDING` or `CONFIRMED` orders. `PROCESSING`, `SHIPPED`, and
`DELIVERED` orders cannot be cancelled.

Cancellation persists a release operation before calling Product Catalog.
Until release succeeds, the order is not marked cancelled. If the response is
lost, retrying cancellation reuses the saved release operation ID. The
inventory service's idempotency contract prevents duplicate stock restoration.
Order placement similarly commits a pending operation before reserving stock;
if the reservation response is ambiguous, retry the same create request with
the same `Idempotency-Key` and a valid access token. A definitive insufficient
stock response removes the incomplete local order.

## Pricing rules

For each product, the service fetches the current catalog price and rounds it
to cents using half-up rounding. Duplicate product IDs are combined.

```text
item total = rounded catalog unit price * quantity
subtotal = sum(item totals)
discount = 0.00 (no discount policy is currently configured)
tax = round(subtotal * TAX_RATE, 2)
shipping = SHIPPING_CHARGE
total = subtotal - discount + tax + shipping
```

All calculations use `Decimal`; product prices and order amounts are never
trusted from the client. A future discount policy should be implemented
server-side before populating non-zero discounts.

## Migrations

```powershell
alembic current
alembic revision --autogenerate -m "describe schema change"
alembic upgrade head
```

The current head creates the inventory-operation table after the existing
orders and order-items migration. Review autogenerated revisions before
applying them. Docker applies `alembic upgrade head` before starting Uvicorn.

## Docker Compose

Copy `.env.example` to `.env`, set `DB_PASSWORD`, `JWT_SECRET_KEY`,
`USER_SERVICE_URL`, and `PRODUCT_SERVICE_URL`, then run:

```powershell
docker compose up --build
```

Compose starts a MySQL 8 container with a named persistent volume and health
check, waits for it before starting the API, applies migrations, and publishes
the API on host port `ORDER_SERVICE_PORT` (default `8000`). If that port is
already in use, set `ORDER_SERVICE_PORT` in `.env` to an available port, such
as `8001`. Service URLs must be reachable from inside the
`order-service` container; `localhost` inside a container refers to that
container, not the Windows host. For host services, use `host.docker.internal`
where supported.

To stop containers without removing database data:

```powershell
docker compose down
```

## Verification

Focused API tests run with:

```powershell
python -m unittest discover -s tests -v
```

Latest result: **14 tests passed**. The API tests use an isolated SQLite
database and mocked User/Product service responses. They cover successful
pricing and order creation, invalid/inactive products, insufficient stock,
invalid addresses, missing/invalid JWTs, ownership and admin access,
order-number lookup, pagination and filters, status permissions/transitions,
and cancellation. Inventory failure tests verify that rejected reservations
leave no order and that a failed release can be retried with the same
operation ID without duplicate restoration.

Swagger UI was opened at `http://127.0.0.1:8001/docs`; an unauthenticated
`GET /api/orders/` returned **401**. Docker Compose started MySQL and the API,
applied the Alembic migrations, and `/health/ready` returned **200**. The
migrated `orders`, `order_items`, and `inventory_operations` tables and their
unique/foreign-key constraints were inspected.

**Not verified:** Postman testing (Postman is not available in this
environment), or live authenticated flows against Authentication, User, and
Product services. The actual service URLs, JWT contract/credentials, and
downstream API contracts were not supplied. The mocked tests do not prove
real inventory changes in the Product Catalog database; run the documented
Swagger/Postman scenarios against the target service environment before
release.

The 20-scenario dummy-data report is available as
[swagger_20_scenario_test_report.pdf](./swagger_20_scenario_test_report.pdf).
Its captured Swagger response is also available as
[swagger_ui_output.png](./swagger_ui_output.png).

The additional live Swagger UI run against the isolated dummy-data harness is
documented in [swagger_live_test_report.pdf](./swagger_live_test_report.pdf).
The report includes the 20 requested scenarios, observed results, and the
limits of this test setup. A Swagger UI response capture is available as
[swagger_live_test_output.png](./swagger_live_test_output.png).

The live Swagger UI checks used `http://127.0.0.1:8002/docs`, an in-memory
SQLite database, test-only JWTs, and mocked User/Product/inventory responses.
They exercised successful order creation and lookup, rejected product/address
cases, authentication and ownership failures, list filters, admin/customer
status permissions, invalid transitions, eligible and ineligible cancellation,
and repeated cancellation. These results validate the service routes and
workflow against dummy dependencies; they do not prove calls to real
Authentication, User, or Product services or actual external inventory
restoration. Product-service outage behavior is covered by the automated
service test, not this Swagger run.

## Project publication and team updates

No Git repository or remote URL is configured in this workspace. GitHub
publishing, the designated Excel progress sheet, and Teams updates remain
pending until their repository URL, workbook/sheet, and Teams group/channel
are provided.
