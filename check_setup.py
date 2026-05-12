import sys
from pathlib import Path

from config import ENV_FILE, get_env, looks_like_placeholder


def main():
    print("Python:", sys.version)
    print("Project folder:", Path(__file__).resolve().parent)
    print(".env found:", ENV_FILE.exists())

    for name in [
        "IG_API_KEY",
        "IG_USERNAME",
        "IG_PASSWORD",
        "FINNHUB_API_KEY",
        "PAPER_TRADING",
    ]:
        value = get_env(name)
        if value is None:
            print(f"{name}: missing")
        elif looks_like_placeholder(value):
            print(f"{name}: still placeholder")
        else:
            print(f"{name}: present, length={len(value)}")

    try:
        import requests

        print("requests package: installed")
        try:
            response = requests.get(
                "https://demo-api.ig.com/gateway/deal",
                timeout=20,
            )
            print(f"IG website reachable: yes, status={response.status_code}")
        except requests.RequestException as error:
            print("IG website reachable: no")
            print("Connection error:", error)
    except ImportError:
        print("requests package: missing")


if __name__ == "__main__":
    main()
