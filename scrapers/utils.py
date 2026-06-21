import requests
import json
import time


def load_config(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def request(api, timeout=30):
    retries = 5
    backoff = 2
    attempt = 0
    while attempt < retries:
        try:
            response = requests.get(api, timeout=timeout)
        except requests.RequestException as e:
            print(f"Network error for {api}: {e}")
            return None

        if response.status_code == 200:
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
    return None
