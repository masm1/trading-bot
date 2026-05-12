import requests

from config import FINNHUB_API_KEY, looks_like_placeholder


def get_earnings_calendar():
    if looks_like_placeholder(FINNHUB_API_KEY):
        print("Finnhub key is missing or still a placeholder in .env")
        return []

    url = "https://finnhub.io/api/v1/calendar/earnings"
    response = requests.get(
        url,
        params={"token": FINNHUB_API_KEY},
        timeout=20,
    )

    if response.status_code != 200:
        print("Finnhub request failed.")
        print("Status code:", response.status_code)
        print("Message:", response.text)
        return []

    data = response.json()
    return data.get("earningsCalendar", [])

