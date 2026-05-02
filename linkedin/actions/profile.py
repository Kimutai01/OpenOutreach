# linkedin/actions/profile.py
import json
import logging
from pathlib import Path
from typing import Dict, Any

from linkedin.conf import FIXTURE_PROFILES_DIR
from linkedin.sessions.registry import AccountSessionRegistry, SessionKey
from ..api.client import PlaywrightLinkedinAPI

logger = logging.getLogger(__name__)


def scrape_profile(key: SessionKey, profile: dict):
    url = profile["url"]

    session = AccountSessionRegistry.get_or_create(
        handle=key.handle,
        campaign_name=key.campaign_name,
        csv_hash=key.csv_hash,
    )

    session.ensure_browser()
    session.wait()

    # Navigate to the profile page before calling the Voyager API.
    # This ensures LinkedIn has set JSESSIONID (needed as csrf-token) in the
    # browser context before we make the API request.
    from linkedin.navigation.utils import goto_page
    from linkedin.db.profiles import url_to_public_id
    public_identifier = url_to_public_id(url)
    def _navigate_to_profile():
        try:
            goto_page(
                session,
                action=lambda: session.page.goto(url, timeout=30_000),
                expected_url_pattern=f"/in/{public_identifier}",
                timeout=30_000,
                error_message=f"Failed to navigate to profile: {url}",
                to_scrape=False,
            )
        except Exception as nav_err:
            logger.debug("Profile navigation before API call failed: %s", nav_err)
            try:
                session.page.wait_for_load_state("domcontentloaded", timeout=5_000)
            except Exception:
                pass

    _navigate_to_profile()

    # If LinkedIn redirected to authwall, li_at was revoked (likely due to a proxy IP change).
    # Delete the stale cookie file, then re-login if credentials exist, or raise
    # SessionExpiredError so the caller can retry with fresh cookies.
    if "authwall" in session.page.url:
        from linkedin.navigation.exceptions import SessionExpiredError
        from linkedin.conf import get_account_config
        config = get_account_config(session.handle)
        cookie_file = Path(config["cookie_file"])
        if cookie_file.exists():
            cookie_file.unlink()
            logger.warning("Authwall hit — deleted stale cookie file → %s", cookie_file)

        has_real_credentials = (
            config.get("password") not in (None, "", "cookie_auth")
            and not config.get("username", "").endswith("@example.com")
        )

        if has_real_credentials:
            logger.info("Re-logging in with stored credentials for %s", session.handle)
            # Close only the browser (not the DB session) so the campaign can continue.
            try:
                if session.context:
                    session.context.close()
                if session.browser:
                    session.browser.close()
                if session.playwright:
                    session.playwright.stop()
            except Exception as e:
                logger.debug("Error closing browser during re-login: %s", e)
            finally:
                session.page = session.context = session.browser = session.playwright = None
            session.ensure_browser()
            _navigate_to_profile()
        else:
            raise SessionExpiredError(
                f"LinkedIn session expired (li_at revoked) for {session.handle}. "
                "Proxy IP likely changed. Retry with fresh cookies."
            )

    api = PlaywrightLinkedinAPI(session=session)

    logger.info("Enriching profile → %s", url)
    profile, data = api.get_profile(profile_url=url)

    logger.info("Profile enriched – %s", profile.get("public_identifier")) if profile else None

    return profile, data


def _save_profile_to_fixture(enriched_profile: Dict[str, Any], path: str | Path) -> None:
    """Utility to save enriched profile as test fixture."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(enriched_profile, f, indent=2, ensure_ascii=False, default=str)
    logger.info("Enriched profile saved to fixture → %s", path)


if __name__ == "__main__":
    import sys
    from linkedin.campaigns.connect_follow_up import INPUT_CSV_PATH

    FIXTURE_PATH = FIXTURE_PROFILES_DIR / "linkedin_profile.json"

    logging.getLogger().handlers.clear()
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s │ %(levelname)-8s │ %(message)s',
        datefmt="%H:%M:%S",
    )

    if len(sys.argv) != 2:
        print("Usage: python -m linkedin.actions.profile <handle>")
        sys.exit(1)

    handle = sys.argv[1]

    key = SessionKey.make(
        handle=handle,
        campaign_name="test_profile",
        csv_path=INPUT_CSV_PATH,
    )

    test_profile = {
        "url": "https://www.linkedin.com/in/lexfridman/",
    }

    profile, data = scrape_profile(key, test_profile)

    _save_profile_to_fixture(data, FIXTURE_PATH)
    print(f"Fixture saved → {FIXTURE_PATH}")
