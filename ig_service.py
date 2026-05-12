# ig_service.py

import time

try:
    import requests
except ImportError:
    requests = None

from config import (
    FINNHUB_API_KEY,
    IG_API_KEY,
    IG_PASSWORD,
    IG_USERNAME,
    looks_like_placeholder,
)
from mapping import PRICE_SYMBOL_MAP

BASE_URL = "https://demo-api.ig.com/gateway/deal"
TIMEOUT = (5, 20)
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


class IGService:
    def __init__(self):
        self.session_headers = None
        self.http = requests.Session() if requests else None
        self.logged_in = False

    def _request_with_retry(self, method, url, **kwargs):
        last_exception = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.http.request(method, url, timeout=TIMEOUT, **kwargs)
                return response
            except requests.RequestException as exc:
                last_exception = exc
                if attempt < MAX_RETRIES:
                    backoff = RETRY_BACKOFF_SECONDS * attempt
                    print(f"⚠ IG request failed (attempt {attempt}/{MAX_RETRIES}): {exc}. Retrying in {backoff}s...")
                    time.sleep(backoff)
                    continue
                print(f"⚠ IG request failed after {MAX_RETRIES} attempts: {exc}")
                raise

    # ---------------- LOGIN ---------------- #
    def login(self):
        if requests is None:
            print("⚠ requests not installed → IG disabled")
            return False

        if looks_like_placeholder(IG_API_KEY):
            print("⚠ IG_API_KEY missing → IG disabled")
            return False

        try:
            print("🔐 Logging into IG...")

            response = self._request_with_retry(
                "POST",
                BASE_URL + "/session",
                json={
                    "identifier": IG_USERNAME,
                    "password": IG_PASSWORD,
                },
                headers={
                    "X-IG-API-KEY": IG_API_KEY,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Version": "2",
                },
            )

            if "text/html" in response.headers.get("Content-Type", ""):
                print("⚠ IG HTML response → skipping IG")
                return False

            if response.status_code != 200:
                print("⚠ IG login failed:", response.text)
                return False

            self.session_headers = {
                "X-IG-API-KEY": IG_API_KEY,
                "CST": response.headers.get("CST"),
                "X-SECURITY-TOKEN": response.headers.get("X-SECURITY-TOKEN"),
                "Accept": "application/json",
            }

            self.logged_in = True
            print("✅ IG login successful")
            return True

        except requests.RequestException as e:
            print("⚠ IG connection error:", e)
            return False

    # ---------------- PRICE ---------------- #
    def get_price(self, epic):
        if not self.logged_in or not epic:
            return None

        try:
            response = self._request_with_retry(
                "GET",
                BASE_URL + f"/markets/{epic}",
                headers=self._headers("3"),
            )

            if response.status_code != 200:
                return None

            snapshot = response.json().get("snapshot", {})

            bid = snapshot.get("bid")
            offer = snapshot.get("offer")
            last = snapshot.get("lastTraded")

            if bid and offer:
                return (bid + offer) / 2

            return last

        except requests.RequestException:
            return None

    def get_price_for_symbol(self, symbol, epic=None):
        if epic:
            price = self.get_price(epic)
            if price is not None:
                return price

        return self._get_finnhub_price(symbol)

    # ---------------- MARKET SEARCH ---------------- #
    def search_market(self, search_term):
        if not self.logged_in or not search_term:
            return None

        try:
            response = self._request_with_retry(
                "GET",
                BASE_URL + "/markets",
                params={"searchTerm": search_term},
                headers=self._headers("3"),
            )

            if response.status_code != 200:
                return None

            data = response.json()
            markets = data.get("markets") or []
            if not markets:
                return None

            first_market = markets[0]
            return first_market.get("epic")

        except requests.RequestException:
            return None

    # ---------------- FINNHUB ---------------- #
    def _get_finnhub_price(self, symbol):
        if looks_like_placeholder(FINNHUB_API_KEY):
            return None

        try:
            response = self._request_with_retry(
                "GET",
                "https://finnhub.io/api/v1/quote",
                params={
                    "symbol": PRICE_SYMBOL_MAP.get(symbol.upper(), symbol.upper()),
                    "token": FINNHUB_API_KEY,
                },
            )

            if response.status_code != 200:
                return None

            data = response.json()
            return data.get("c") or data.get("pc")

        except requests.RequestException:
            return None

    # ---------------- OPEN POSITIONS ---------------- #
    def get_open_positions(self):
        if not self.logged_in:
            return []

        try:
            response = self._request_with_retry(
                "GET",
                BASE_URL + "/positions",
                headers=self._headers("2"),
            )

            if response.status_code != 200:
                return []

            return response.json().get("positions", [])

        except requests.RequestException:
            return None

    # ---------------- PLACE ORDER ---------------- #
    def place_demo_market_order(self, epic, direction, size):
        if not self.logged_in:
            return {"success": False, "message": "Not logged in"}

        payload = {
            "currencyCode": "USD",
            "direction": direction.upper(),
            "epic": epic,
            "expiry": "-",
            "forceOpen": True,
            "orderType": "MARKET",
            "size": float(size),
        }

        try:
            response = self._request_with_retry(
                "POST",
                BASE_URL + "/positions/otc",
                json=payload,
                headers=self._headers("2"),
            )

            if response.status_code not in [200, 201]:
                return {"success": False, "message": response.text}

            payload = response.json()
            return {
                "success": True,
                "message": payload.get("reason", "") or payload.get("message", ""),
                "deal_reference": payload.get("dealReference", ""),
                "deal_id": payload.get("dealId", ""),
            }

        except requests.RequestException as e:
            return {"success": False, "message": str(e)}

    # ---------------- CLOSE POSITION ---------------- #
    def close_demo_position(self, deal_id, direction, size):
        if not self.logged_in:
            return {"success": False}

        close_direction = "SELL" if direction == "BUY" else "BUY"

        payload = {
            "dealId": deal_id,
            "direction": close_direction,
            "orderType": "MARKET",
            "size": float(size),
        }

        headers = self._headers("1")
        headers["_method"] = "DELETE"

        try:
            response = self._request_with_retry(
                "POST",
                BASE_URL + "/positions/otc",
                json=payload,
                headers=headers,
            )

            if response.status_code not in [200, 201]:
                return {
                    "success": False,
                    "message": response.text,
                    "deal_reference": "",
                }

            payload = response.json()
            return {
                "success": True,
                "message": payload.get("reason", "") or payload.get("message", ""),
                "deal_reference": payload.get("dealReference", ""),
            }

        except requests.RequestException as e:
            return {"success": False, "message": str(e), "deal_reference": ""}

    # ---------------- HEADERS ---------------- #
    def _headers(self, version):
        headers = dict(self.session_headers)
        headers["Version"] = version
        return headers