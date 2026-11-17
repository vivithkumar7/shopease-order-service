import time
import unittest
from decimal import Decimal
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.database.connection import Base, get_db
from app.main import app
from app.models import InventoryOperation, Order
from app.services.product_client import ProductSnapshot


JWT_SECRET = "test-only-order-service-signing-key"
ADDRESS = {
    "recipient_name": "Test Customer",
    "phone_number": "1234567890",
    "address_line1": "123 Test Street",
    "address_line2": None,
    "city": "Test City",
    "state": "Test State",
    "postal_code": "12345",
    "country": "Test Country",
}


class OrderApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.session_factory = sessionmaker(
            bind=cls.engine,
            autoflush=False,
            expire_on_commit=False,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        self.settings_patch = patch.object(settings, "JWT_SECRET_KEY", JWT_SECRET)
        self.settings_patch.start()
        self.mock_address = patch(
            "app.services.order_service.user_client.get_shipping_address",
            return_value=ADDRESS,
        )
        self.mock_profile = patch(
            "app.services.order_service.user_client.get_user_profile",
            return_value={"id": 17},
        )
        self.mock_product = patch(
            "app.services.order_service.product_client.get_product",
            return_value=ProductSnapshot(
                product_id=4,
                name="Product 4",
                sku="SKU-4",
                unit_price=Decimal("12.34"),
                available_stock=5,
            ),
        )
        self.mock_reserve = patch(
            "app.services.order_service.product_client.reserve_inventory"
        )
        self.mock_release = patch(
            "app.services.order_service.product_client.release_inventory"
        )
        self.mock_address.start()
        self.mock_profile.start()
        self.mock_product.start()
        self.reserve = self.mock_reserve.start()
        self.release = self.mock_release.start()

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        self.mock_address.stop()
        self.mock_profile.stop()
        self.mock_product.stop()
        self.mock_reserve.stop()
        self.mock_release.stop()
        self.settings_patch.stop()

    @staticmethod
    def token(user_id: int = 17, role: str = "customer") -> str:
        return jwt.encode(
            {
                "sub": str(user_id),
                "role": role,
                "exp": int(time.time()) + 600,
            },
            JWT_SECRET,
            algorithm="HS256",
        )

    def create_order(self, key: str = "create-order-key-001"):
        return self.client.post(
            "/api/orders/",
            headers={
                "Authorization": f"Bearer {self.token()}",
                "Idempotency-Key": key,
            },
            json={
                "items": [{"product_id": 4, "quantity": 2}],
                "shipping_address_id": 9,
                "notes": "Leave at the front desk",
            },
        )

    def test_authentication_is_required_and_invalid_tokens_are_rejected(self) -> None:
        self.assertEqual(self.client.get("/api/orders/").status_code, 401)
        response = self.client.get(
            "/api/orders/",
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        self.assertEqual(response.status_code, 401)
        create_request = {
            "items": [{"product_id": 4, "quantity": 1}],
            "shipping_address_id": 9,
        }
        missing_token = self.client.post(
            "/api/orders/",
            headers={"Idempotency-Key": "missing-token-key"},
            json=create_request,
        )
        self.assertEqual(missing_token.status_code, 401)
        invalid_token = self.client.post(
            "/api/orders/",
            headers={
                "Authorization": "Bearer not-a-jwt",
                "Idempotency-Key": "invalid-token-key",
            },
            json=create_request,
        )
        self.assertEqual(invalid_token.status_code, 401)

    def test_order_uses_catalog_price_and_retries_idempotently(self) -> None:
        response = self.create_order()
        self.assertEqual(response.status_code, 201, response.text)
        order = response.json()
        self.assertEqual(order["subtotal"], "24.68")
        self.assertEqual(order["discount_amount"], "0.00")
        self.assertEqual(order["tax_amount"], "4.44")
        self.assertEqual(order["shipping_charge"], "50.00")
        self.assertEqual(order["total_amount"], "79.12")
        self.assertEqual(order["items"][0]["product_name"], "Product 4")
        self.assertEqual(order["items"][0]["unit_price"], "12.34")

        retry = self.create_order()
        self.assertEqual(retry.status_code, 201, retry.text)
        self.assertEqual(retry.json()["id"], order["id"])
        self.reserve.assert_called_once()

    def test_order_is_not_visible_to_another_customer(self) -> None:
        created = self.create_order()
        self.assertEqual(created.status_code, 201, created.text)
        response = self.client.get(
            f"/api/orders/{created.json()['id']}",
            headers={"Authorization": f"Bearer {self.token(user_id=99)}"},
        )
        self.assertEqual(response.status_code, 403)

    def test_order_lookup_items_and_pagination(self) -> None:
        first = self.create_order("create-order-key-001")
        second = self.create_order("create-order-key-002")
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)
        headers = {"Authorization": f"Bearer {self.token()}"}

        by_number = self.client.get(
            f"/api/orders/number/{first.json()['order_number']}",
            headers=headers,
        )
        self.assertEqual(by_number.status_code, 200, by_number.text)
        self.assertEqual(by_number.json()["id"], first.json()["id"])

        items = self.client.get(
            f"/api/orders/{first.json()['id']}/items",
            headers=headers,
        )
        self.assertEqual(items.status_code, 200, items.text)
        self.assertEqual(len(items.json()), 1)

        page = self.client.get(
            "/api/orders/?page=1&page_size=1",
            headers=headers,
        )
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(page.json()["total"], 2)
        self.assertEqual(page.json()["page_size"], 1)
        self.assertEqual(len(page.json()["orders"]), 1)

        filtered = self.client.get(
            "/api/orders/?order_status=PENDING&created_from=9999-12-31T23:59:59",
            headers=headers,
        )
        self.assertEqual(filtered.status_code, 200, filtered.text)
        self.assertEqual(filtered.json()["total"], 0)

        admin_orders = self.client.get(
            "/api/orders/",
            headers={"Authorization": f"Bearer {self.token(role='admin')}"},
        )
        self.assertEqual(admin_orders.status_code, 200, admin_orders.text)
        self.assertEqual(admin_orders.json()["total"], 2)

    def test_client_cannot_set_owner_or_price_and_cannot_bypass_cancel_workflow(self) -> None:
        headers = {
            "Authorization": f"Bearer {self.token()}",
            "Idempotency-Key": "create-order-key-001",
        }
        response = self.client.post(
            "/api/orders/",
            headers=headers,
            json={
                "user_id": 99,
                "items": [
                    {"product_id": 4, "quantity": 1, "unit_price": "0.01"}
                ],
                "shipping_address_id": 9,
            },
        )
        self.assertEqual(response.status_code, 422)

        created = self.create_order()
        admin_headers = {"Authorization": f"Bearer {self.token(role='admin')}"}
        bypass = self.client.patch(
            f"/api/orders/{created.json()['id']}/status",
            headers=admin_headers,
            json={"order_status": "CANCELLED"},
        )
        self.assertEqual(bypass.status_code, 409)

    def test_status_changes_require_admin_and_validate_transitions(self) -> None:
        created = self.create_order()
        order_id = created.json()["id"]
        customer_update = self.client.patch(
            f"/api/orders/{order_id}/status",
            headers={"Authorization": f"Bearer {self.token()}"},
            json={"order_status": "CONFIRMED"},
        )
        self.assertEqual(customer_update.status_code, 403)

        admin_headers = {"Authorization": f"Bearer {self.token(role='admin')}"}
        confirmed = self.client.patch(
            f"/api/orders/{order_id}/status",
            headers=admin_headers,
            json={"order_status": "CONFIRMED"},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        invalid_transition = self.client.patch(
            f"/api/orders/{order_id}/status",
            headers=admin_headers,
            json={"order_status": "DELIVERED"},
        )
        self.assertEqual(invalid_transition.status_code, 409)

    def test_cancellation_releases_inventory_once(self) -> None:
        created = self.create_order()
        order_id = created.json()["id"]
        headers = {"Authorization": f"Bearer {self.token()}"}

        cancelled = self.client.post(
            f"/api/orders/{order_id}/cancel",
            headers=headers,
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["order_status"], "CANCELLED")

        retry = self.client.post(
            f"/api/orders/{order_id}/cancel",
            headers=headers,
        )
        self.assertEqual(retry.status_code, 200, retry.text)
        self.release.assert_called_once()
        with self.session_factory() as db:
            release_operation = db.scalar(
                select(InventoryOperation).where(
                    InventoryOperation.operation_type == "RELEASE"
                )
            )
            self.assertIsNotNone(release_operation)
            self.assertEqual(release_operation.state, "COMPLETE")

    def test_cancellation_retry_reuses_operation_after_service_failure(self) -> None:
        created = self.create_order()
        order_id = created.json()["id"]
        headers = {"Authorization": f"Bearer {self.token()}"}
        self.release.side_effect = [
            HTTPException(
                status_code=503,
                detail="Product Catalog inventory service is unavailable",
            ),
            None,
        ]

        failed = self.client.post(
            f"/api/orders/{order_id}/cancel",
            headers=headers,
        )
        self.assertEqual(failed.status_code, 503)
        with self.session_factory() as db:
            order = db.get(Order, order_id)
            release_operation = db.scalar(
                select(InventoryOperation).where(
                    InventoryOperation.operation_type == "RELEASE"
                )
            )
            self.assertEqual(order.order_status, "PENDING")
            self.assertEqual(release_operation.state, "PENDING")
            operation_id = release_operation.operation_id

        retried = self.client.post(
            f"/api/orders/{order_id}/cancel",
            headers=headers,
        )
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.json()["order_status"], "CANCELLED")
        self.assertEqual(self.release.call_count, 2)
        self.assertEqual(
            self.release.call_args_list[0].args[1],
            self.release.call_args_list[1].args[1],
        )
        with self.session_factory() as db:
            release_operation = db.scalar(
                select(InventoryOperation).where(
                    InventoryOperation.operation_type == "RELEASE"
                )
            )
            self.assertEqual(release_operation.operation_id, operation_id)
            self.assertEqual(release_operation.state, "COMPLETE")

    def test_insufficient_inventory_leaves_no_order_record(self) -> None:
        with patch(
            "app.services.order_service.product_client.reserve_inventory",
            side_effect=HTTPException(
                status_code=409,
                detail="Insufficient inventory",
            ),
        ):
            response = self.create_order()
        self.assertEqual(response.status_code, 409)

        with self.session_factory() as db:
            self.assertEqual(db.scalar(select(Order.id)), None)
            operation = db.scalar(select(InventoryOperation))
            self.assertIsNotNone(operation)
            self.assertEqual(operation.state, "FAILED")
            self.assertIsNone(operation.order_id)

    def test_invalid_product_and_shipping_address_are_rejected(self) -> None:
        with patch(
            "app.services.order_service.product_client.get_product",
            side_effect=HTTPException(status_code=422, detail="Unknown product"),
        ):
            invalid_product = self.create_order()
        self.assertEqual(invalid_product.status_code, 422)

        with patch(
            "app.services.order_service.user_client.get_shipping_address",
            side_effect=HTTPException(status_code=422, detail="Unknown address"),
        ):
            invalid_address = self.create_order("create-order-key-002")
        self.assertEqual(invalid_address.status_code, 422)

    def test_inactive_product_is_rejected_without_saving_order(self) -> None:
        with patch(
            "app.services.order_service.product_client.get_product",
            side_effect=HTTPException(
                status_code=409,
                detail="Product 4 is inactive",
            ),
        ):
            response = self.create_order()

        self.assertEqual(response.status_code, 409)
        self.reserve.assert_not_called()
        with self.session_factory() as db:
            self.assertIsNone(db.scalar(select(Order.id)))

    def test_stock_is_checked_before_order_is_saved(self) -> None:
        with patch(
            "app.services.order_service.product_client.get_product",
            return_value=ProductSnapshot(
                product_id=4,
                name="Product 4",
                sku="SKU-4",
                unit_price=Decimal("12.34"),
                available_stock=1,
            ),
        ):
            response = self.create_order()
        self.assertEqual(response.status_code, 409)
        self.reserve.assert_not_called()
        with self.session_factory() as db:
            self.assertEqual(db.scalar(select(Order.id)), None)

    def test_product_service_unavailability_is_reported(self) -> None:
        with patch(
            "app.services.order_service.product_client.get_product",
            side_effect=HTTPException(
                status_code=503,
                detail="Product Catalog Service is unavailable",
            ),
        ):
            response = self.create_order()
        self.assertEqual(response.status_code, 503)

    def test_shipped_and_delivered_orders_cannot_be_cancelled(self) -> None:
        created = self.create_order()
        order_id = created.json()["id"]
        admin_headers = {"Authorization": f"Bearer {self.token(role='admin')}"}
        for next_status in ("CONFIRMED", "PROCESSING", "SHIPPED"):
            updated = self.client.patch(
                f"/api/orders/{order_id}/status",
                headers=admin_headers,
                json={"order_status": next_status},
            )
            self.assertEqual(updated.status_code, 200, updated.text)

        cancelled = self.client.post(
            f"/api/orders/{order_id}/cancel",
            headers={"Authorization": f"Bearer {self.token()}"},
        )
        self.assertEqual(cancelled.status_code, 409)

        delivered = self.client.patch(
            f"/api/orders/{order_id}/status",
            headers=admin_headers,
            json={"order_status": "DELIVERED"},
        )
        self.assertEqual(delivered.status_code, 200, delivered.text)
        delivered_cancellation = self.client.post(
            f"/api/orders/{order_id}/cancel",
            headers={"Authorization": f"Bearer {self.token()}"},
        )
        self.assertEqual(delivered_cancellation.status_code, 409)
        self.release.assert_not_called()
