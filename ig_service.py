import re
import time

try:
    import requests
except ImportError:
    requests = None

from config import (
    FINNHUB_API_KEY,
    IG_API_KEY,
    IG_BASE_URL,
    IG_PASSWORD,
    IG_USERNAME,
    looks_like_placeholder,
)
from mapping import PRICE_SYMBOL_MAP

BASE_URL = IG_BASE_URL
TIMEOUT = (5, 20)
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
CONFIRM_ATTEMPTS = 5
CONFIRM_DELAY_SECONDS = 1
BASE_HEADERS = {
    "Accept": "application/json; charset=UTF-8",
    "Content-Type": "application/json; charset=UTF-8",
    "User-Agent": "TradingBotDashboard/1.0",
}


class IGService:
    def __init__(self):
        self.session_headers = None
        self.http = requests.Session() if requests else None
        self.logged_in = False

    def _request_with_retry(self, method, url, **kwargs):
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return self.http.request(method, url, timeout=TIMEOUT, **kwargs)
            except requests.RequestException as exc:
                if attempt < MAX_RETRIES:
                    backoff = RETRY_BACKOFF_SECONDS * attempt
                    print(
                        f"IG request failed (attempt {attempt}/{MAX_RETRIES}): "
                        f"{exc}. Retrying in {backoff}s..."
                    )
                    time.sleep(backoff)
                    continue
                print(f"IG request failed after {MAX_RETRIES} attempts: {exc}")
                raise

    def login(self):
        if requests is None:
            print("requests not installed -> IG disabled")
            return False

        if looks_like_placeholder(IG_API_KEY):
            print("IG_API_KEY missing -> IG disabled")
            return False

        if looks_like_placeholder(IG_USERNAME) or looks_like_placeholder(IG_PASSWORD):
            print("IG username/password missing -> IG disabled")
            return False

        try:
            print(f"Logging into IG via {BASE_URL}...")

            response = self._request_with_retry(
                "POST",
                BASE_URL + "/session",
                json={
                    "identifier": IG_USERNAME,
                    "password": IG_PASSWORD,
                },
                headers=self._base_headers(
                    {
                        "X-IG-API-KEY": IG_API_KEY,
                        "Version": "2",
                    }
                ),
            )

            if "text/html" in response.headers.get("Content-Type", ""):
                self._print_html_diagnostic(response)
                return False

            if response.status_code != 200:
                print(f"IG login failed: status={response.status_code}")
                print("Message:", self._safe_response_text(response))
                return False

            cst = response.headers.get("CST")
            security_token = response.headers.get("X-SECURITY-TOKEN")
            if not cst or not security_token:
                print("IG login response missing security tokens")
                print("Message:", self._safe_response_text(response))
                return False

            self.session_headers = {
                "X-IG-API-KEY": IG_API_KEY,
                "CST": cst,
                "X-SECURITY-TOKEN": security_token,
                "Accept": BASE_HEADERS["Accept"],
                "User-Agent": BASE_HEADERS["User-Agent"],
            }

            self.logged_in = True
            print("IG login successful")
            return True

        except requests.RequestException as exc:
            print("IG connection error:", exc)
            return False

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

    def search_market(self, search_term):
        if not self.logged_in or not search_term:
            return None

        try:
            response = self._request_with_retry(
                "GET",
                BASE_URL + "/markets",
                params={"searchTerm": search_term},
                headers=self._headers("1"),
            )

            if response.status_code != 200:
                return None

            markets = response.json().get("markets") or []
            if not markets:
                return None

            for market in markets:
                if market.get("marketStatus") == "TRADEABLE" and market.get("epic"):
                    return market.get("epic")

            return None

        except requests.RequestException:
            return None

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
                print(f"IG open positions failed: status={response.status_code}")
                return []

            return response.json().get("positions", [])

        except requests.RequestException:
            return None

    def place_demo_market_order(self, epic, direction, size):
        if not self.logged_in:
            return {"success": False, "message": "Not logged in"}
        if not epic:
            return {"success": False, "message": "Missing IG epic. Search mapping did not return a tradable market."}

        payload = {
            "currencyCode": "USD",
            "direction": direction.upper(),
            "epic": epic,
            "expiry": "-",
            "forceOpen": True,
            "guaranteedStop": False,
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
                return {"success": False, "message": self._safe_response_text(response)}

            data = response.json()
            deal_reference = data.get("dealReference", "")
            if not deal_reference:
                return {
                    "success": False,
                    "message": data.get("reason", "") or data.get("message", "") or "IG did not return a deal reference.",
                    "deal_reference": "",
                    "deal_id": data.get("dealId", ""),
                }

            confirmation = self.confirm_deal(deal_reference)
            confirmation["deal_reference"] = deal_reference
            return {
                "success": confirmation.get("success", False),
                "confirmed": confirmation.get("confirmed", False),
                "pending_confirmation": confirmation.get("pending_confirmation", False),
                "message": confirmation.get("message", "") or data.get("reason", "") or data.get("message", ""),
                "deal_reference": deal_reference,
                "deal_id": confirmation.get("deal_id", "") or data.get("dealId", ""),
                "deal_status": confirmation.get("deal_status", ""),
            }

        except requests.RequestException as exc:
            return {"success": False, "message": str(exc)}

    def confirm_deal(self, deal_reference):
        if not self.logged_in:
            return {"success": False, "confirmed": False, "message": "Not logged in"}
        if not deal_reference:
            return {"success": False, "confirmed": False, "message": "Missing deal reference."}

        last_message = ""
        for attempt in range(1, CONFIRM_ATTEMPTS + 1):
            try:
                response = self._request_with_retry(
                    "GET",
                    BASE_URL + f"/confirms/{deal_reference}",
                    headers=self._headers("1"),
                )

                if response.status_code == 200:
                    data = response.json()
                    deal_status = (data.get("dealStatus") or "").upper()
                    reason = data.get("reason", "") or data.get("status", "")
                    deal_id = data.get("dealId", "") or self._deal_id_from_affected_deals(data)
                    success = deal_status == "ACCEPTED"
                    return {
                        "success": success,
                        "confirmed": True,
                        "message": reason,
                        "deal_reference": deal_reference,
                        "deal_id": deal_id,
                        "deal_status": deal_status,
                    }

                last_message = self._safe_response_text(response)
                if response.status_code != 404:
                    break
            except requests.RequestException as exc:
                last_message = str(exc)

            if attempt < CONFIRM_ATTEMPTS:
                time.sleep(CONFIRM_DELAY_SECONDS)

        return {
            "success": False,
            "confirmed": False,
            "pending_confirmation": True,
            "message": f"Order submitted but IG confirmation is unavailable. Deal reference: {deal_reference}. {last_message}".strip(),
            "deal_reference": deal_reference,
            "deal_id": "",
            "deal_status": "",
        }

    def close_demo_position(self, deal_id, direction, size):
        if not self.logged_in:
            return {"success": False}

        close_direction = "SELL" if direction == "BUY" else "BUY"
        payload = {
            "dealId": deal_id,
            "direction": close_direction,
            "guaranteedStop": False,
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
                    "message": self._safe_response_text(response),
                    "deal_reference": "",
                }

            data = response.json()
            deal_reference = data.get("dealReference", "")
            if not deal_reference:
                return {
                    "success": False,
                    "confirmed": False,
                    "message": data.get("reason", "") or data.get("message", "") or "IG did not return a close deal reference.",
                    "deal_reference": "",
                }

            confirmation = self.confirm_deal(deal_reference)
            return {
                "success": confirmation.get("success", False),
                "confirmed": confirmation.get("confirmed", False),
                "pending_confirmation": confirmation.get("pending_confirmation", False),
                "message": confirmation.get("message", "") or data.get("reason", "") or data.get("message", ""),
                "deal_reference": deal_reference,
                "deal_id": confirmation.get("deal_id", ""),
                "deal_status": confirmation.get("deal_status", ""),
            }

        except requests.RequestException as exc:
            return {"success": False, "message": str(exc), "deal_reference": ""}

    def _deal_id_from_affected_deals(self, data):
        affected_deals = data.get("affectedDeals") or []
        for deal in affected_deals:
            deal_id = deal.get("dealId")
            if deal_id:
                return deal_id
        return ""

    def _headers(self, version):
        headers = dict(self.session_headers)
        headers["Version"] = version
        return headers

    def _base_headers(self, extra=None):
        headers = dict(BASE_HEADERS)
        if extra:
            headers.update(extra)
        return headers

    def _print_html_diagnostic(self, response):
        print(
            "IG returned HTML instead of JSON "
            f"(status={response.status_code}, content-type={response.headers.get('Content-Type', '')})"
        )
        text = self._safe_response_text(response)
        title = self._html_title(text)
        if title:
            print("HTML title:", title)
        if text:
            print("HTML preview:", text[:300])
        print(
            "Likely causes: wrong demo/live endpoint, API access disabled, "
            "invalid credentials/API key, or IG blocking/challenging this server IP."
        )

    def _safe_response_text(self, response):
        text = response.text or ""
        for secret in [IG_API_KEY, IG_USERNAME, IG_PASSWORD, FINNHUB_API_KEY]:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return re.sub(r"\s+", " ", text).strip()

    def _html_title(self, text):
        match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        return re.sub(r"\s+", " ", match.group(1)).strip()
