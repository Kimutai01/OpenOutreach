# linkedin/actions/connect.py
import logging
from typing import Dict, Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from linkedin.navigation.enums import ProfileState
from linkedin.navigation.exceptions import SkipProfile, ReachedConnectionLimit
from linkedin.navigation.utils import get_top_card
from linkedin.sessions.registry import AccountSessionRegistry, SessionKey

logger = logging.getLogger(__name__)


def send_connection_request(
        key: SessionKey,
        profile: Dict[str, Any],
        message: str = None,
) -> ProfileState:
    """
    Sends a LinkedIn connection request.
    If message is provided, sends with a note. Otherwise sends without a note (fastest).
    """
    from linkedin.actions.connection_status import get_connection_status

    session = AccountSessionRegistry.get_or_create(
        handle=key.handle,
        campaign_name=key.campaign_name,
        csv_hash=key.csv_hash,
    )

    public_identifier = profile.get('public_identifier')

    logger.debug("Checking current connection status...")
    connection_status = get_connection_status(session, profile)
    logger.info("Current status → %s", connection_status.value)

    skip_reasons = {
        ProfileState.CONNECTED: "Already connected",
        ProfileState.PENDING: "Invitation already pending",
    }

    if connection_status in skip_reasons:
        logger.info("Skipping %s – %s", public_identifier, skip_reasons[connection_status])
        return connection_status

    # Send invitation with or without note based on message parameter
    if message:
        logger.info("Sending connection request WITH note (%d chars)", len(message))
        profile_url = profile.get('url') or f"https://www.linkedin.com/in/{public_identifier}/"
        success = _perform_send_invitation_with_note(session, message, profile_url)
        success = success and _check_weekly_invitation_limit(session)
    else:
        logger.info("Sending connection request WITHOUT note")
        s1 = _connect_direct(session)
        s2 = s1 or _connect_via_more(session)
        s3 = s2 and _click_without_note(session)
        s4 = s3 and _check_weekly_invitation_limit(session)
        success = s4

    status = ProfileState.PENDING if success else ProfileState.ENRICHED
    logger.info(f"Connection request {status} → {public_identifier}")
    return status


def _check_weekly_invitation_limit(session):
    weekly_invitation_limit = session.page.locator('div[class*="ip-fuse-limit-alert__warning"]')
    if weekly_invitation_limit.count() != 0:
        raise ReachedConnectionLimit("Weekly connection limit pop up appeared")

    return True


def _connect_direct(session):
    session.wait()
    top_card = get_top_card(session)
    direct = top_card.locator('button[aria-label*="Invite"][aria-label*="to connect"]:visible')
    if direct.count() == 0:
        return False

    direct.first.click()
    logger.debug("Clicked direct 'Connect' button")

    error = session.page.locator('div[data-test-artdeco-toast-item-type="error"]')
    if error.count() != 0:
        raise SkipProfile(f"{error.inner_text().strip()}")

    return True


def _connect_via_more(session):
    session.wait()
    top_card = get_top_card(session)

    # Fallback: More → Connect
    more = top_card.locator(
        'button[id*="overflow"]:visible, '
        'button[aria-label*="More actions"]:visible'
    )
    if more.count() == 0:
        return False
    more.first.click()

    session.wait()

    connect_option = top_card.locator(
        'div[role="button"][aria-label^="Invite"][aria-label*=" to connect"]'
    )
    if connect_option.count() == 0:
        return False
    connect_option.first.click()
    logger.debug("Used 'More → Connect' flow")

    return True


def _click_without_note(session):
    """Click flow: sends connection request instantly without note."""
    session.wait()

    # Click "Send now" / "Send without a note"
    send_btn = session.page.locator(
        'button:has-text("Send now"), '
        'button[aria-label*="Send without"], '
        'button[aria-label*="Send invitation"]:not([aria-label*="note"])'
    )
    send_btn.first.click(force=True)
    session.wait()
    logger.debug("Connection request submitted (no note)")

    return True


# ===================================================================
# FUTURE: Send with personalized note (just uncomment when ready)
# ===================================================================
def _perform_send_invitation_with_note(session, message: str, profile_url: str):
    """
    Full flow with custom note.
    Falls back to sending without note if textarea cannot be located
    (e.g., when user has reached connection note limit).
    When fallback occurs, navigates back to profile and sends without note.
    """
    session.wait()
    top_card = get_top_card(session)

    direct = top_card.locator('button[aria-label*="Invite"][aria-label*="to connect"]:visible')
    if direct.count() > 0:
        direct.first.click()
    else:
        more = top_card.locator('button[id*="overflow"], button[aria-label*="More actions"]').first
        more.click()
        session.wait()
        session.page.locator('div[role="button"][aria-label^="Invite"][aria-label*=" to connect"]').first.click()

    session.wait()
    
    # Try to add a note - check if "Add a note" button exists
    add_note_btn = session.page.locator('button:has-text("Add a note")')
    try:
        # Wait for button to be visible before clicking
        add_note_btn.first.wait_for(state="visible", timeout=10000)
        add_note_btn.first.click()
        session.wait()

        # Wait for textarea to be visible and ready before filling
        # LinkedIn sometimes takes a moment to render the modal and textarea
        # If user has reached connection note limit, textarea won't appear
        textarea = session.page.locator('textarea#custom-message, textarea[name="message"]')
        textarea.first.wait_for(state="visible", timeout=15000)
        textarea.first.fill(message)
        session.wait()
        logger.debug("Filled note (%d chars)", len(message))

        send_btn = session.page.locator('button:has-text("Send"), button[aria-label*="Send invitation"]')
        send_btn.first.click(force=True)
        session.wait()
        logger.debug("Connection request with note sent")
        return True
        
    except PlaywrightTimeoutError:
        # Textarea not found - likely user has reached connection note limit
        # Navigate back to profile and send without note
        logger.warning("Could not locate textarea for note. User may have reached connection note limit. Navigating back to profile and sending without note.")
        
        # Try to close any open modal by pressing Escape
        try:
            session.page.keyboard.press("Escape")
            session.wait(to_scrape=False)
        except Exception:
            pass  # Modal might already be closed or navigation will close it
        
        # Navigate back to profile page
        from linkedin.navigation.utils import goto_page
        public_identifier = profile_url.split('/in/')[-1].rstrip('/')
        goto_page(
            session,
            action=lambda: session.page.goto(profile_url),
            expected_url_pattern=f"/in/{public_identifier}",
            error_message="Failed to navigate back to profile",
            to_scrape=False
        )
        
        # Now send without note using the standard flow
        s1 = _connect_direct(session)
        s2 = s1 or _connect_via_more(session)
        s3 = s2 and _click_without_note(session)
        return s3


if __name__ == "__main__":
    import sys
    from linkedin.sessions.registry import SessionKey
    from linkedin.campaigns.connect_follow_up import INPUT_CSV_PATH

    if len(sys.argv) != 2:
        print("Usage: python -m linkedin.actions.connect <handle>")
        sys.exit(1)

    handle = sys.argv[1]
    key = SessionKey.make(handle, "test_connect", INPUT_CSV_PATH)

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    public_identifier = "benjames01"
    test_profile = {
        "full_name": "Ben James",
        "url": f"https://www.linkedin.com/in/{public_identifier}/",
        "public_identifier": public_identifier,
    }

    print(f"Testing connection request as @{handle} (session: {key})")
    status = send_connection_request(
        key=key,
        profile=test_profile,
        template_file="./assets/templates/messages/followup.j2",
    )

    print(f"Finished → Status: {status.value}")
