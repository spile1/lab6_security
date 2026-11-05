# Клієнт із тайм-аутом і повторними спробами для безпечних (GET) запитів
import time
import requests

RETRY_STATUSES = (502, 503, 504)


def get_with_retry(url, retries=3, timeout=2, pause=0.2):
    """Повертає (відповідь або None, кількість спроб).
    Повторює запит після тайм-ауту, обриву з'єднання
    або тимчасової помилки сервера.
    """
    attempt = 0
    response = None
    while attempt < retries:
        attempt = attempt + 1
        try:
            response = requests.get(url, timeout=timeout)
            if response.status_code not in RETRY_STATUSES:
                return response, attempt
        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ):
            response = None
        time.sleep(pause)
    return response, attempt
