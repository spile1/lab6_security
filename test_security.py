# Завдання 2-4: автентифікація, розмежування прав доступу,
# витік конфіденційних даних
import time
import requests

# ---------- Завдання 2. Автентифікація


def test_protected_endpoint_without_token(base_url):
    response = requests.get(f"{base_url}/api/profile", timeout=5)

    assert response.status_code in (401, 403)
    assert response.json()["error"] == "unauthorized"


def test_protected_endpoint_with_wrong_token(base_url):
    response = requests.get(
        f"{base_url}/api/profile",
        headers={"Authorization": "Bearer wrong-token-123"},
        timeout=5,
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def test_protected_endpoint_with_correct_token(base_url, user_a):
    response = requests.get(
        f"{base_url}/api/profile", headers=user_a["headers"], timeout=5
    )

    assert response.status_code == 200
    assert response.json()["username"] == user_a["username"]


def test_token_without_required_rights(base_url, user_a):
    # звичайний покупець звертається до адміністративного ресурсу
    response = requests.get(
        f"{base_url}/api/admin/orders", headers=user_a["headers"], timeout=5
    )

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


def test_expired_token(base_url, user_a):
    login = requests.post(
        f"{base_url}/api/login",
        timeout=5,
        json={
            "username": user_a["username"],
            "password": user_a["password"],
            "ttl_seconds": 1,
        },
    )
    token = login.json()["token"]
    time.sleep(1.5)

    response = requests.get(
        f"{base_url}/api/profile",
        headers={"Authorization": "Bearer " + token},
        timeout=5,
    )

    assert response.status_code == 401
    assert response.json()["error"] == "token_expired"


# ---------- Завдання 3. Розмежування прав доступу


def test_user_a_reads_own_order(base_url, user_a, order_a):
    response = requests.get(
        f"{base_url}/api/orders/{order_a['id']}",
        headers=user_a["headers"],
        timeout=5,
    )

    assert response.status_code == 200
    assert response.json()["id"] == order_a["id"]


def test_user_b_reads_own_order(base_url, user_b, order_b):
    response = requests.get(
        f"{base_url}/api/orders/{order_b['id']}",
        headers=user_b["headers"],
        timeout=5,
    )

    assert response.status_code == 200
    assert response.json()["id"] == order_b["id"]


def test_user_cannot_access_another_users_order(base_url, user_a, order_b):
    response = requests.get(
        f"{base_url}/api/orders/{order_b['id']}",
        headers=user_a["headers"],
        timeout=5,
    )

    assert response.status_code in (403, 404)
    assert "items" not in response.json()


def test_user_cannot_change_another_users_order(
    base_url, user_a, user_b, order_a
):
    response = requests.patch(
        f"{base_url}/api/orders/{order_a['id']}",
        headers=user_b["headers"],
        json={"status": "cancelled"},
        timeout=5,
    )

    assert response.status_code in (403, 404)
    # замовлення користувача А залишилося без змін
    check = requests.get(
        f"{base_url}/api/orders/{order_a['id']}",
        headers=user_a["headers"],
        timeout=5,
    )
    assert check.json()["status"] == "created"


def test_order_list_contains_only_own_orders(
    base_url, user_a, order_a, order_b
):
    response = requests.get(
        f"{base_url}/api/orders", headers=user_a["headers"], timeout=5
    )

    ids = []
    for order in response.json():
        ids.append(order["id"])
    assert ids == [order_a["id"]]


# ---------- Завдання 4. Витік конфіденційних даних


def test_profile_response_does_not_expose_password(base_url, user_a):
    response = requests.get(
        f"{base_url}/api/profile", headers=user_a["headers"], timeout=5
    )

    assert response.status_code == 200

    data = response.json()

    assert "password" not in data
    assert "password_hash" not in data
    assert "token" not in data
    assert user_a["password"] not in response.text
    assert user_a["token"] not in response.text


def test_order_response_does_not_expose_owner_data(base_url, user_a, order_a):
    response = requests.get(
        f"{base_url}/api/orders/{order_a['id']}",
        headers=user_a["headers"],
        timeout=5,
    )

    assert set(response.json().keys()) == {
        "id",
        "user_id",
        "items",
        "total",
        "status",
    }


def test_login_error_does_not_reveal_user_existence(base_url, user_a):
    wrong_password = requests.post(
        f"{base_url}/api/login",
        timeout=5,
        json={"username": user_a["username"], "password": "wrong-password"},
    )
    unknown_user = requests.post(
        f"{base_url}/api/login",
        timeout=5,
        json={
            "username": "nobody_" + user_a["username"],
            "password": "wrong-password",
        },
    )

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


def test_error_responses_have_no_internal_details(base_url):
    cart_id = requests.post(f"{base_url}/api/carts", timeout=5).json()["id"]
    responses = [
        requests.post(
            f"{base_url}/api/carts/{cart_id}/items",
            data="{bad json",
            headers={"Content-Type": "application/json"},
            timeout=5,
        ),
        requests.get(f"{base_url}/api/no-such-endpoint", timeout=5),
        requests.delete(f"{base_url}/api/products", timeout=5),
    ]

    statuses = []
    for response in responses:
        statuses.append(response.status_code)
    assert statuses == [400, 404, 405]
    for response in responses:
        assert response.headers["Content-Type"].startswith("application/json")
        for word in ["Traceback", 'File "', "werkzeug", "/srv/", "line "]:
            assert word not in response.text


def test_security_headers(base_url):
    response = requests.get(f"{base_url}/api/products", timeout=5)

    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"


def test_login_attempts_are_limited(base_url, user_b):
    statuses = []
    for attempt in range(6):
        response = requests.post(
            f"{base_url}/api/login",
            timeout=5,
            json={
                "username": user_b["username"],
                "password": "wrong-" + str(attempt),
            },
        )
        statuses.append(response.status_code)

    assert statuses[:5] == [401, 401, 401, 401, 401]
    assert statuses[5] == 429
    assert "Retry-After" in response.headers
