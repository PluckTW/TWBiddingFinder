import requests
import json
import time


def load_config(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


class CircuitBreaker:
    """Stops calling a host after `threshold` consecutive failures.

    A failure is a network error (connect/read timeout, DNS, reset) or a
    429/5xx that is still failing after all retries. Any 200 resets the count.
    Lets a scraper give up on an unreachable site after a few tries instead of
    waiting out the timeout for every remaining keyword.
    """

    def __init__(self, name, threshold=3):
        self.name = name
        self.threshold = threshold
        self.failures = 0
        self.last_error = None

    @property
    def is_open(self):
        return self.failures >= self.threshold

    def record_success(self):
        self.failures = 0

    def record_failure(self, error):
        self.failures += 1
        self.last_error = error


# (connect, read) seconds: an unreachable host fails fast on connect,
# while a slow-but-alive API still gets time to answer.
DEFAULT_TIMEOUT = (10, 30)


def request(api, timeout=DEFAULT_TIMEOUT, breaker=None, headers=None,
            retries=5, http_errors_trip_breaker=True):
    """GET with retry on 429/5xx. Returns the response on 200, else None.

    http_errors_trip_breaker=False: a 429/5xx that outlasts the retries
    doesn't count toward the breaker (only network errors do) — for calls
    where one request failing says nothing about the host, e.g. one day's
    listing.
    """
    if breaker is not None and breaker.is_open:
        return None

    backoff = 2
    attempt = 0
    while attempt < retries:
        try:
            response = requests.get(api, timeout=timeout, headers=headers)
        except requests.RequestException as e:
            print(f"Network error for {api}: {e}")
            if breaker is not None:
                breaker.record_failure(f"{type(e).__name__}")
            return None

        if response.status_code == 200:
            if breaker is not None:
                breaker.record_success()
            return response
        elif response.status_code == 429 or response.status_code >= 500:
            wait_time = backoff * (2 ** attempt)
            print(f"Retry {attempt + 1}: Status {response.status_code}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
            attempt += 1
        else:
            print(f"Failed to fetch {api}. Status: {response.status_code}")
            return None

    print(f"Max retries reached for {api}. Returning None.")
    if breaker is not None and http_errors_trip_breaker:
        breaker.record_failure(f"HTTP {response.status_code}")
    return None
