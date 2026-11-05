# Завдання 5-6: тайм-аути, недоступність сервера,
# тимчасові помилки та повторні запити
import uuid
import pytest
import requests

from network_client import get_with_retry

# ---------- Завдання 5. Тайм-аут


def test_request_has_timeout(base_url):
    try:
        response = requests.get(f"{base_url}/api/products", timeout=3)

        assert response.status_code < 500

    except requests.exceptions.Timeout:
        # Тайм-аут оброблено контрольовано.
        pass


def test_slow_response_raises_timeout(base_url):
    # сервер затримує відповідь на 3 с, клієнт чекає лише 1 с
    with pytest.raises(requests.exceptions.Timeout):
        requests.get(f"{base_url}/api/slow?delay=3", timeout=1)


def test_response_within_timeout(base_url):
    response = requests.get(f"{base_url}/api/slow?delay=0.5", timeout=3)

    assert response.status_code == 200
    assert response.elapsed.total_seconds() >= 0.5


def test_retry_after_timeout_gives_up(base_url):
    response, attempts = get_with_retry(
        f"{base_url}/api/slow?delay=2", retries=2, timeout=0.5
    )

    assert response is None
    assert attempts == 2


def test_server_unavailable(base_url):
    # на порту 8999 сервер не запущено
    response, attempts = get_with_retry(
        "http://localhost:8999/api/products", retries=3, timeout=1
    )

    assert response is None
    assert attempts == 3


# ---------- Завдання 6. Повторні запити


def test_temporary_error_is_retried(base_url):
    key = uuid.uuid4().hex
    response, attempts = get_with_retry(
        f"{base_url}/api/unstable?fail=2&key={key}", retries=3
    )

    assert response.status_code == 200
    assert attempts == 3


def test_temporary_error_without_enough_retries(base_url):
    key = uuid.uuid4().hex
    response, attempts = get_with_retry(
        f"{base_url}/api/unstable?fail=5&key={key}", retries=3
    )

    assert response.status_code == 503
    assert response.headers.get("Retry-After") == "1"
    assert attempts == 3


def test_repeated_order_with_same_key_is_not_duplicated(base_url, user_a):
    key = uuid.uuid4().hex
    headers = dict(user_a["headers"])
    headers["Idempotency-Key"] = key
    body = {"items": [{"product_id": 5, "quantity": 1}]}

    first = requests.post(
        f"{base_url}/api/orders", json=body, headers=headers, timeout=5
    )
    second = requests.post(
        f"{base_url}/api/orders", json=body, headers=headers, timeout=5
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json() == first.json()
    orders = requests.get(
        f"{base_url}/api/orders", headers=user_a["headers"], timeout=5
    ).json()
    assert len(orders) == 1


def test_repeated_order_without_key_creates_duplicate(base_url, user_a):
    # без ключа ідемпотентності сервер не відрізняє повтор від нового
    # замовлення
    body = {"items": [{"product_id": 5, "quantity": 1}]}

    first = requests.post(
        f"{base_url}/api/orders",
        json=body,
        headers=user_a["headers"],
        timeout=5,
    )
    second = requests.post(
        f"{base_url}/api/orders",
        json=body,
        headers=user_a["headers"],
        timeout=5,
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
