# linkedin/actions/conversations.py
"""Retrieve LinkedIn conversation history for a given profile."""
import logging
from datetime import datetime

from linkedin.api.client import PlaywrightLinkedinAPI
from linkedin.api.messaging import fetch_conversations, fetch_messages, encode_urn
from linkedin.db.profiles import url_to_public_id

logger = logging.getLogger(__name__)


def _resolve_urn(public_identifier: str, session) -> str | None:
    """Resolve a public_identifier to a fsd_profile URN via the Voyager API."""
    api = PlaywrightLinkedinAPI(session=session)
    profile, _ = api.get_profile(public_identifier=public_identifier)
    if not profile:
        return None
    return profile.get("urn")


def find_conversation_urn(api: PlaywrightLinkedinAPI, target_urn: str) -> str | None:
    """Find conversation URN for a target profile URN by scanning recent conversations."""
    try:
        raw = fetch_conversations(api)
    except Exception as e:
        logger.warning("fetch_conversations failed: %s", e)
        return None

    elements = (
        raw.get("data", {})
        .get("messengerConversationsBySyncToken", {})
        .get("elements", [])
    )

    for conv in elements:
        for p in conv.get("conversationParticipants", []):
            if p.get("hostIdentityUrn") == target_urn:
                return conv.get("entityUrn")
    return None


def find_conversation_urn_via_navigation(session, target_urn: str) -> str | None:
    """
    Navigate to the messaging thread for a profile and capture the conversation URN
    by intercepting the Voyager response.
    """
    page = session.page
    captured_urn = [None]

    def on_response(response):
        if "messengerMessages" not in response.url:
            return
        try:
            data = response.json()
            elements = (
                data.get("data", {})
                .get("messengerMessagesBySyncToken", {})
                .get("elements", [])
            )
            if elements:
                captured_urn[0] = elements[0].get("conversation", {}).get("entityUrn")
        except Exception:
            pass

    session.context.on("response", on_response)
    try:
        url = f"https://www.linkedin.com/messaging/thread/new/?recipient={encode_urn(target_urn)}"
        logger.debug("Navigating to messaging thread -> %s", url)
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(8_000)
    except Exception as e:
        logger.warning("Navigation to messaging thread failed: %s", e)
    finally:
        session.context.remove_listener("response", on_response)

    return captured_urn[0]


def parse_messages(raw: dict) -> list[dict]:
    """Parse raw Voyager messages response into a list of {sender, text, timestamp} dicts."""
    elements = (
        raw.get("data", {})
        .get("messengerMessagesBySyncToken", {})
        .get("elements", [])
    )

    messages = []
    for msg in elements:
        body = msg.get("body", {})
        text = body.get("text", "") if isinstance(body, dict) else str(body)
        if not text:
            continue

        participant = msg.get("sender", {}).get("participantType", {}).get("member", {})
        first = (participant.get("firstName") or {}).get("text", "")
        last = (participant.get("lastName") or {}).get("text", "")
        sender_name = f"{first} {last}".strip()

        delivered_at = msg.get("deliveredAt")
        ts = (
            datetime.fromtimestamp(delivered_at / 1000).strftime("%Y-%m-%d %H:%M")
            if delivered_at
            else ""
        )

        messages.append({"sender": sender_name or "unknown", "text": text, "timestamp": ts})

    messages.sort(key=lambda m: m["timestamp"])
    return messages


def _scrape_messages_from_dom(page) -> list[dict]:
    """
    Scrape messages from the rendered LinkedIn messaging DOM.

    Handles the classic LinkedIn messaging UI (.msg-s-message-group / .msg-s-event-listitem)
    that is used on most thread pages.
    """
    messages = []

    try:
        page.wait_for_selector(".msg-s-event-listitem", timeout=6_000)
    except Exception:
        return messages

    groups = page.query_selector_all(".msg-s-message-group")
    for group in groups:
        name_el = group.query_selector(".msg-s-message-group__name")
        sender = name_el.inner_text().strip() if name_el else "unknown"

        ts_el = group.query_selector(".msg-s-message-group__timestamp")
        group_ts = ts_el.inner_text().strip() if ts_el else ""

        items = group.query_selector_all(".msg-s-event-listitem")
        for item in items:
            body_el = item.query_selector(".msg-s-event-listitem__body")
            if not body_el:
                continue
            text = body_el.inner_text().strip()
            if not text:
                continue

            # Per-message timestamp overrides the group timestamp when available
            time_el = item.query_selector("time[datetime]")
            ts = time_el.get_attribute("datetime") if time_el else group_ts

            messages.append({"sender": sender, "text": text, "timestamp": ts})

    return messages


def get_conversation(session, url: str) -> list[dict] | None:
    """
    Retrieve past messages with a profile URL.

    Navigates to the messaging thread for the profile, then:
    1. Scrapes messages directly from the rendered DOM (works for the classic
       LinkedIn messaging UI).
    2. Falls back to intercepting the Voyager API response if the DOM contains
       no messages (e.g. the thread was never opened / new UI variant).

    Returns a list of {sender, text, timestamp} dicts,
    or None if no conversation exists.
    """
    public_identifier = url_to_public_id(url)
    if not public_identifier:
        logger.warning("Could not extract public_identifier from URL: %s", url)
        return None

    session.ensure_browser()

    target_urn = _resolve_urn(public_identifier, session)
    if not target_urn:
        logger.warning("Could not resolve URN for %s", public_identifier)
        return None

    page = session.page
    captured: dict = {"messages_raw": None}

    def on_response(response):
        url_lower = response.url.lower()
        if "messengermessages" not in url_lower and "messenger-conversations" not in url_lower:
            return
        try:
            data = response.json()
            elements = (
                data.get("data", {})
                .get("messengerMessagesBySyncToken", {})
                .get("elements", [])
            )
            if elements:
                captured["messages_raw"] = data
                return
            if data.get("elements"):
                captured["messages_raw"] = data
        except Exception:
            pass

    session.context.on("response", on_response)
    try:
        thread_url = f"https://www.linkedin.com/messaging/thread/new/?recipient={encode_urn(target_urn)}"
        logger.debug("Navigating to messaging thread -> %s", public_identifier)
        page.goto(thread_url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(5_000)
    except Exception as e:
        logger.warning("Navigation to messaging thread failed: %s", e)
    finally:
        session.context.remove_listener("response", on_response)

    # --- Primary: scrape from DOM ---
    dom_messages = _scrape_messages_from_dom(page)
    if dom_messages:
        logger.info(
            "Scraped %d messages from DOM for %s", len(dom_messages), public_identifier
        )
        return dom_messages

    # --- Fallback: use intercepted Voyager API response ---
    if captured["messages_raw"]:
        logger.info("Using intercepted API response for %s", public_identifier)
        return parse_messages(captured["messages_raw"])

    logger.info("No messages found for %s — no conversation exists", public_identifier)
    return None
