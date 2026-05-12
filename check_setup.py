import sys
from pathlib import Path

from config import ENV_FILE, IG_BASE_URL, get_env, looks_like_placeholder


def main():
    print("Python:", sys.version)
    print("Project folder:", Path(__file__).resolve().parent)
    print(".env found:", ENV_FILE.exists())
    print("IG_BASE_URL:", IG_BASE_URL)

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
                IG_BASE_URL,
                timeout=20,
            )
            print(f"IG website reachable: yes, status={response.status_code}")
            print("IG content type:", response.headers.get("Content-Type", ""))
        except requests.RequestException as error:
            print("IG website reachable: no")
            print("Connection error:", error)
    except ImportError:
        print("requests package: missing")


if __name__ == "__main__":
    main()
