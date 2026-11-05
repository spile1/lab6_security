# Чек-лист безпеки навчального інтернет-магазину TestShop

Середовище: локальний навчальний API `http://localhost:8000`, тестові облікові записи створюються під час запуску тестів.

| № | Перевірка | Очікуваний результат | Автотест |
|---|-----------|----------------------|----------|
| 1 | Запит до захищеного ресурсу без токена | Доступ відхилено, 401 | test_protected_endpoint_without_token |
| 2 | Запит із неправильним токеном | Доступ відхилено, 401 | test_protected_endpoint_with_wrong_token |
| 3 | Запит із простроченим токеном | Доступ відхилено, 401 `token_expired` | test_expired_token |
| 4 | Запит із коректним токеном | 200, дані власного профілю | test_protected_endpoint_with_correct_token |
| 5 | Покупець звертається до адміністративного ресурсу | Доступ заборонено, 403 | test_token_without_required_rights |
| 6 | Користувач А читає замовлення користувача Б | 404, дані замовлення не повертаються | test_user_cannot_access_another_users_order |
| 7 | Користувач Б змінює замовлення користувача А | 404, замовлення не змінилося | test_user_cannot_change_another_users_order |
| 8 | Список замовлень користувача | Лише власні замовлення | test_order_list_contains_only_own_orders |
| 9 | Відповідь профілю | Немає password, password_hash, token | test_profile_response_does_not_expose_password |
| 10 | Відповідь із замовленням | Лише поля id, user_id, items, total, status | test_order_response_does_not_expose_owner_data |
| 11 | Вхід з неправильним паролем і з неіснуючим логіном | Однакова відповідь 401 | test_login_error_does_not_reveal_user_existence |
| 12 | Відповіді з помилками 400, 404, 405 | JSON без трасування стека і шляхів сервера | test_error_responses_have_no_internal_details |
| 13 | Заголовки відповіді | X-Content-Type-Options: nosniff, X-Frame-Options: DENY | test_security_headers |
| 14 | Шоста невдала спроба входу за хвилину | 429 і заголовок Retry-After | test_login_attempts_are_limited |
