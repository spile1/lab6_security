# Навчальний інтернет-магазин TestShop.
# Контрольоване тестове середовище для лабораторних робіт 4-6
# з дисципліни «Тестування ІКТ».
# Запуск: python shop_app/app.py  (сервер працює на http://localhost:8000)

import os
import time
import secrets
import threading

from flask import (
    Flask,
    request,
    jsonify,
    render_template,
    redirect,
    url_for,
    session,
    abort,
)
from werkzeug.security import generate_password_hash, check_password_hash

from data import PRODUCTS

app = Flask(__name__)
# Ключ для підпису cookie сесії (кошик у веб-інтерфейсі)
# береться зі змінної середовища.
app.json.ensure_ascii = False  # кирилиця у JSON без екранування
app.json.sort_keys = False  # поля у відповіді в порядку оголошення
app.secret_key = os.environ.get("SHOP_SECRET_KEY", secrets.token_hex(16))

TOKEN_LIFETIME = 1800  # час життя токена за замовчуванням, секунд
MAX_FAILED_LOGINS = 5  # дозволена кількість невдалих входів за хвилину
lock = threading.Lock()

# Дані зберігаються в пам'яті й скидаються після перезапуску сервера
users = {}  # username -> {"id", "username", "email", "role", "password_hash"}
tokens = {}  # token -> {"username", "expires"}
carts = {}  # cart_id -> {"id", "items": {product_id: quantity}}
orders = {}  # order_id -> замовлення
idempotency = {}  # (username, ключ) -> order_id
failed_logins = {}  # username -> [час невдалої спроби, ...]
unstable_calls = {}  # key -> кількість звернень до /api/unstable
next_user_id = 1
next_order_id = 1001


# --------------------------------------------------------- допоміжні функції


def find_product(product_id):
    for product in PRODUCTS:
        if product["id"] == product_id:
            return product
    return None


def search_products(query):
    query = query.strip().lower()
    found = []
    for product in PRODUCTS:
        if query in product["name"].lower():
            found.append(product)
    return found


def product_json(product):
    return {
        "id": product["id"],
        "name": product["name"],
        "category": product["category"],
        "price": product["price"],
        "stock": product["stock"],
    }


def error(status, code, message, **extra):
    body = {"error": code, "message": message}
    body.update(extra)
    return jsonify(body), status


def is_integer(value):
    # bool у Python є підкласом int, тому true/false окремо відкидаються
    return isinstance(value, int) and not isinstance(value, bool)


def cart_json(cart):
    items = []
    total = 0
    for product_id, quantity in cart["items"].items():
        product = find_product(product_id)
        line_total = product["price"] * quantity
        total = total + line_total
        items.append(
            {
                "product_id": product_id,
                "name": product["name"],
                "price": product["price"],
                "quantity": quantity,
                "line_total": line_total,
            }
        )
    return {"id": cart["id"], "items": items, "total": total}


def current_user():
    # Повертає (користувач, None) або (None, відповідь з помилкою)
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None, error(401, "unauthorized", "Потрібна автентифікація")
    token = header[len("Bearer ") :]
    info = tokens.get(token)
    if info is None:
        return None, error(401, "invalid_token", "Недійсний токен")
    if info["expires"] < time.time():
        del tokens[token]
        return None, error(401, "token_expired", "Термін дії токена минув")
    return users[info["username"]], None


def public_user(user):
    # Поля, які можна віддавати клієнту
    return {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "role": user["role"],
    }


def validate_items(items):
    # Перевіряє позиції замовлення, повертає відповідь з помилкою або None
    if not isinstance(items, list) or len(items) == 0:
        return error(
            422,
            "validation_error",
            "Поле items має бути непорожнім списком",
            field="items",
        )
    for item in items:
        if not isinstance(item, dict):
            return error(
                422,
                "validation_error",
                "Позиція має бути об'єктом",
                field="items",
            )
        for field in ["product_id", "quantity"]:
            if field not in item:
                return error(
                    422,
                    "validation_error",
                    "Відсутнє обов'язкове поле",
                    field=field,
                )
            if not is_integer(item[field]):
                return error(
                    422,
                    "validation_error",
                    "Поле має бути цілим числом",
                    field=field,
                )
        if item["quantity"] <= 0:
            return error(
                422,
                "validation_error",
                "Кількість має бути додатною",
                field="quantity",
            )
        product = find_product(item["product_id"])
        if product is None:
            return error(404, "product_not_found", "Товар не знайдено")
        if item["quantity"] > product["stock"]:
            return error(
                409,
                "out_of_stock",
                "Недостатньо товару на складі",
                available=product["stock"],
            )
    return None


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


# ------------------------------------------------------------- веб-інтерфейс


@app.context_processor
def cart_counter():
    count = 0
    for quantity in session.get("cart", {}).values():
        count = count + quantity
    return {"cart_count": count}


@app.route("/")
def home():
    return render_template("home.html", products=PRODUCTS)


@app.route("/search")
def search_page():
    query = request.args.get("q", "")
    if query.strip() == "":
        return render_template(
            "search.html", query=query, products=[], empty_query=True
        )
    found = search_products(query)
    return render_template(
        "search.html", query=query.strip(), products=found, empty_query=False
    )


@app.route("/product/<int:product_id>")
def product_page(product_id):
    product = find_product(product_id)
    if product is None:
        abort(404)
    message = session.pop("message", None)
    return render_template("product.html", product=product, message=message)


@app.route("/cart/add/<int:product_id>", methods=["POST"])
def cart_add(product_id):
    product = find_product(product_id)
    if product is None:
        abort(404)
    cart = session.get("cart", {})
    key = str(product_id)
    in_cart = cart.get(key, 0)
    if in_cart + 1 > product["stock"]:
        session["message"] = "Недостатньо товару на складі"
    else:
        cart[key] = in_cart + 1
        session["cart"] = cart
        session["message"] = "Товар додано до кошика"
    return redirect(url_for("product_page", product_id=product_id))


@app.route("/cart")
def cart_page():
    rows = []
    total = 0
    for key, quantity in session.get("cart", {}).items():
        product = find_product(int(key))
        line_total = product["price"] * quantity
        total = total + line_total
        rows.append(
            {
                "product": product,
                "quantity": quantity,
                "line_total": line_total,
            }
        )
    return render_template("cart.html", rows=rows, total=total)


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return error(404, "not_found", "Ресурс не знайдено")
    return render_template("not_found.html"), 404


@app.errorhandler(405)
def not_allowed(e):
    return error(405, "method_not_allowed", "Метод не підтримується")


@app.errorhandler(500)
def server_error(e):
    # Клієнт не отримує трасування стека чи внутрішні подробиці
    return error(500, "internal_error", "Внутрішня помилка сервера")


@app.template_filter("uah")
def format_uah(value):
    return "{:,}".format(value).replace(",", " ") + " ₴"


# ------------------------------------------------------ API товарів і кошика


@app.route("/api/products")
def api_products():
    query = request.args.get("search")
    if query is None:
        found = PRODUCTS
    else:
        found = search_products(query)
    result = []
    for product in found:
        result.append(product_json(product))
    return jsonify(result)


@app.route("/api/products/<product_id>")
def api_product(product_id):
    if not product_id.isdigit():
        return error(400, "invalid_id", "Ідентифікатор має бути цілим числом")
    product = find_product(int(product_id))
    if product is None:
        return error(404, "product_not_found", "Товар не знайдено")
    return jsonify(product_json(product))


@app.route("/api/carts", methods=["POST"])
def api_create_cart():
    cart_id = secrets.token_hex(8)
    carts[cart_id] = {"id": cart_id, "items": {}}
    return jsonify(cart_json(carts[cart_id])), 201


@app.route("/api/carts/<cart_id>")
def api_get_cart(cart_id):
    cart = carts.get(cart_id)
    if cart is None:
        return error(404, "cart_not_found", "Кошик не знайдено")
    return jsonify(cart_json(cart))


@app.route("/api/carts/<cart_id>/items", methods=["POST"])
def api_add_to_cart(cart_id):
    cart = carts.get(cart_id)
    if cart is None:
        return error(404, "cart_not_found", "Кошик не знайдено")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error(400, "invalid_json", "Тіло запиту має бути JSON-об'єктом")
    problem = validate_items([data])
    if problem is not None:
        return problem
    product = find_product(data["product_id"])
    in_cart = cart["items"].get(product["id"], 0)
    if in_cart + data["quantity"] > product["stock"]:
        return error(
            409,
            "out_of_stock",
            "Недостатньо товару на складі",
            available=product["stock"] - in_cart,
        )
    cart["items"][product["id"]] = in_cart + data["quantity"]
    return jsonify(cart_json(cart)), 201


@app.route("/api/carts/<cart_id>/items/<int:product_id>", methods=["DELETE"])
def api_remove_from_cart(cart_id, product_id):
    cart = carts.get(cart_id)
    if cart is None or product_id not in cart["items"]:
        return error(404, "not_found", "Позицію не знайдено")
    del cart["items"][product_id]
    return "", 204


# ------------------------------------------------- користувачі та замовлення


@app.route("/api/register", methods=["POST"])
def api_register():
    global next_user_id
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error(400, "invalid_json", "Тіло запиту має бути JSON-об'єктом")
    username = data.get("username")
    password = data.get("password")
    if (
        not isinstance(username, str)
        or not isinstance(password, str)
        or len(password) < 8
    ):
        return error(
            422,
            "validation_error",
            "Потрібні username і пароль від 8 символів",
        )
    with lock:
        if username in users:
            return error(409, "user_exists", "Користувач уже існує")
        user = {
            "id": next_user_id,
            "username": username,
            "email": data.get("email", username + "@testshop.local"),
            # роль адміністратора через реєстрацію не видається
            "role": "customer",
            "password_hash": generate_password_hash(password),
        }
        users[username] = user
        next_user_id = next_user_id + 1
    return jsonify(public_user(user)), 201


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error(400, "invalid_json", "Тіло запиту має бути JSON-об'єктом")
    username = str(data.get("username", ""))
    password = str(data.get("password", ""))

    now = time.time()
    attempts = []
    for moment in failed_logins.get(username, []):
        if now - moment < 60:
            attempts.append(moment)
    failed_logins[username] = attempts
    if len(attempts) >= MAX_FAILED_LOGINS:
        response = error(
            429, "too_many_requests", "Забагато спроб входу, спробуйте пізніше"
        )
        response[0].headers["Retry-After"] = "60"
        return response

    user = users.get(username)
    if user is None or not check_password_hash(
        user["password_hash"], password
    ):
        failed_logins[username].append(now)
        # однакове повідомлення, щоб не розкривати, чи існує користувач
        return error(
            401,
            "invalid_credentials",
            "Неправильне ім'я користувача або пароль",
        )

    lifetime = data.get("ttl_seconds", TOKEN_LIFETIME)
    if not is_integer(lifetime) or lifetime < 1 or lifetime > TOKEN_LIFETIME:
        lifetime = TOKEN_LIFETIME
    token = secrets.token_hex(32)
    tokens[token] = {"username": username, "expires": now + lifetime}
    return jsonify(
        {"token": token, "token_type": "Bearer", "expires_in": lifetime}
    )


@app.route("/api/profile")
def api_profile():
    user, problem = current_user()
    if problem is not None:
        return problem
    return jsonify(public_user(user))


def order_json(order):
    return {
        "id": order["id"],
        "user_id": order["user_id"],
        "items": order["items"],
        "total": order["total"],
        "status": order["status"],
    }


@app.route("/api/orders", methods=["POST"])
def api_create_order():
    global next_order_id
    user, problem = current_user()
    if problem is not None:
        return problem
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error(400, "invalid_json", "Тіло запиту має бути JSON-об'єктом")

    key = request.headers.get("Idempotency-Key")
    with lock:
        # Повтор запиту з тим самим ключем повертає вже створене замовлення
        if key is not None and (user["username"], key) in idempotency:
            order = orders[idempotency[(user["username"], key)]]
            return jsonify(order_json(order)), 200

        problem = validate_items(data.get("items"))
        if problem is not None:
            return problem
        items = []
        total = 0
        for item in data["items"]:
            product = find_product(item["product_id"])
            line_total = product["price"] * item["quantity"]
            total = total + line_total
            items.append(
                {
                    "product_id": product["id"],
                    "name": product["name"],
                    "price": product["price"],
                    "quantity": item["quantity"],
                    "line_total": line_total,
                }
            )
        order = {
            "id": next_order_id,
            "user_id": user["id"],
            "owner": user["username"],
            "items": items,
            "total": total,
            "status": "created",
        }
        orders[next_order_id] = order
        if key is not None:
            idempotency[(user["username"], key)] = next_order_id
        next_order_id = next_order_id + 1
    return jsonify(order_json(order)), 201


@app.route("/api/orders")
def api_my_orders():
    user, problem = current_user()
    if problem is not None:
        return problem
    result = []
    for order in orders.values():
        if order["owner"] == user["username"]:
            result.append(order_json(order))
    return jsonify(result)


@app.route("/api/orders/<int:order_id>", methods=["GET", "PATCH"])
def api_order(order_id):
    user, problem = current_user()
    if problem is not None:
        return problem
    order = orders.get(order_id)
    # Чуже замовлення відповідає так само, як неіснуюче: 404 без подробиць
    if order is None or order["owner"] != user["username"]:
        return error(404, "order_not_found", "Замовлення не знайдено")
    if request.method == "PATCH":
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or data.get("status") != "cancelled":
            return error(
                422,
                "validation_error",
                "Дозволено лише status = cancelled",
                field="status",
            )
        order["status"] = "cancelled"
    return jsonify(order_json(order))


@app.route("/api/admin/orders")
def api_admin_orders():
    user, problem = current_user()
    if problem is not None:
        return problem
    if user["role"] != "admin":
        return error(403, "forbidden", "Недостатньо прав")
    result = []
    for order in orders.values():
        result.append(order_json(order))
    return jsonify(result)


# ------------------------------------ endpoint для перевірки мережевих помилок


@app.route("/api/slow")
def api_slow():
    # Контрольована затримка відповіді (0-10 с) для перевірки тайм-аутів
    delay = request.args.get("delay", "0")
    try:
        delay = float(delay)
    except ValueError:
        return error(400, "invalid_delay", "Параметр delay має бути числом")
    delay = max(0, min(delay, 10))
    time.sleep(delay)
    return jsonify({"status": "ok", "delay": delay})


@app.route("/api/unstable")
def api_unstable():
    # Перші fail звернень з однаковим key отримують 503, наступні - 200
    key = request.args.get("key", "default")
    fail = int(request.args.get("fail", "2"))
    with lock:
        unstable_calls[key] = unstable_calls.get(key, 0) + 1
        call_number = unstable_calls[key]
    if call_number <= fail:
        response = error(
            503, "service_unavailable", "Сервіс тимчасово недоступний"
        )
        response[0].headers["Retry-After"] = "1"
        return response
    return jsonify({"status": "ok", "attempt": call_number})


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("SHOP_PORT", "8000"))
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
