"""
Example client for OpenOutreach API

This script demonstrates how to use the API to run campaigns.
"""
import requests
import sys


def run_campaign_example():
    """Example: Run a campaign synchronously"""

    api_url = "http://localhost:8000/campaign/run"

    # Campaign payload
    payload = {
        "username": "your-email@example.com",  # Replace with your LinkedIn email
        "password": "your-password",            # Replace with your LinkedIn password
        "urls": [
            "https://www.linkedin.com/in/johndoe",
            "https://www.linkedin.com/in/janedoe",
        ],
        "campaign_name": "connect_follow_up"
    }

    print("Starting campaign...")
    print(f"Target profiles: {len(payload['urls'])}")

    try:
        response = requests.post(api_url, json=payload, timeout=300)
        response.raise_for_status()

        result = response.json()

        if result.get("success"):
            print(f"\n✓ Success!")
            print(f"  Message: {result.get('message')}")
            print(f"  Campaign ID: {result.get('campaign_id')}")
            print(f"  Profiles processed: {result.get('profiles_processed')}")
        else:
            print(f"\n✗ Failed!")
            print(f"  Message: {result.get('message')}")

    except requests.exceptions.RequestException as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)


def run_campaign_async_example():
    """Example: Run a campaign asynchronously"""

    api_url = "http://localhost:8000/campaign/run-async"

    payload = {
        "username": "your-email@example.com",
        "password": "your-password",
        "urls": [
            "https://www.linkedin.com/in/johndoe",
        ],
        "campaign_name": "connect_follow_up"
    }

    print("Starting campaign in background...")

    try:
        response = requests.post(api_url, json=payload)
        response.raise_for_status()

        result = response.json()
        print(f"\n✓ Campaign started!")
        print(f"  Message: {result.get('message')}")
        print(f"  Campaign ID: {result.get('campaign_id')}")
        print(f"\nCampaign is running in the background.")

    except requests.exceptions.RequestException as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)


def health_check():
    """Check API health"""

    try:
        response = requests.get("http://localhost:8000/health")
        response.raise_for_status()

        result = response.json()
        print(f"API Status: {result.get('status')}")
        print(f"Version: {result.get('version')}")

    except requests.exceptions.RequestException as e:
        print(f"API is not running or not accessible: {e}")
        sys.exit(1)


if __name__ == "__main__":
    print("OpenOutreach API Client Example\n")

    # Check if API is running
    print("1. Checking API health...")
    health_check()

    print("\n" + "="*50)
    print("Choose an option:")
    print("1. Run campaign (synchronous)")
    print("2. Run campaign (asynchronous)")
    print("="*50)

    choice = input("\nEnter choice (1 or 2): ").strip()

    if choice == "1":
        run_campaign_example()
    elif choice == "2":
        run_campaign_async_example()
    else:
        print("Invalid choice!")
        sys.exit(1)