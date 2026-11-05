# Тестові облікові записи створюються під час запуску з випадковими паролями,
# тому в репозиторії немає жодних паролів чи токенів.
import os
import secrets
import pytest
import requests

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")


def create_user(prefix):
    username = prefix + "_" + secrets.token_hex(4)
    password = secrets.token_urlsafe(16)
    response = requests.post(
        BASE_URL + "/api/register",
        json={"username": username, "password": password},
        timeout=5,
    )
    assert response.status_code == 201
    response = requests.post(
        BASE_URL + "/api/login",
        json={"username": username, "password": password},
        timeout=5,
    )
    assert response.status_code == 200
    token = response.json()["token"]
    return {
        "username": username,
        "password": password,
        "token": token,
        "headers": {"Authorization": "Bearer " + token},
    }


def create_order(user, product_id):
    response = requests.post(
        BASE_URL + "/api/orders",
        headers=user["headers"],
        json={"items": [{"product_id": product_id, "quantity": 1}]},
        timeout=5,
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture
def user_a():
    return create_user("user_a")


@pytest.fixture
def user_b():
    return create_user("user_b")


@pytest.fixture
def order_a(user_a):
    return create_order(user_a, 4)


@pytest.fixture
def order_b(user_b):
    return create_order(user_b, 7)
