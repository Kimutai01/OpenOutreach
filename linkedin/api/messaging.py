# linkedin/api/messaging.py
"""Voyager messaging API calls."""
import logging
from urllib.parse import quote

from linkedin.api.client import PlaywrightLinkedinAPI
from linkedin.navigation.exceptions import AuthenticationError

logger = logging.getLogger(__name__)


def encode_urn(urn: str) -> str:
    """Percent-encode a URN for use inside Voyager API URLs."""
    return quote(urn, safe="")


def get_self_urn(api: PlaywrightLinkedinAPI) -> str:
    """Return the authenticated user's fsd_profile URN."""
    profile, _ = api.get_profile(public_identifier="me")
    if not profile:
        raise AuthenticationError("Cannot fetch own profile via Voyager API")
    return profile["urn"]


def fetch_conversations(api: PlaywrightLinkedinAPI) -> dict:
    """Fetch the first page of messenger conversations."""
    variables = encode_urn('{"mailboxUrn":"urn:li:fsd_profile:me","count":20}')
    url = (
        "https://www.linkedin.com/voyager/api/graphql"
        "?variables=(mailboxUrn:urn%3Ali%3Afsd_profile%3Ame,count:20)"
        "&queryId=messengerConversations.6e9fc33c0d47e18f5a56d60bcaf3c4a0"
    )
    res = api.context.request.get(url, headers=api.headers)
    _check_response(res, "fetch_conversations")
    return res.json()


def fetch_messages(api: PlaywrightLinkedinAPI, conversation_urn: str) -> dict:
    """Fetch messages for a given conversation URN."""
    encoded = encode_urn(conversation_urn)
    url = (
        "https://www.linkedin.com/voyager/api/graphql"
        f"?variables=(conversationUrn:{encoded},count:20)"
        "&queryId=messengerMessages.4b1d0af1e36f3dc9a5b0c1f2e3a4d5b6"
    )
    res = api.context.request.get(url, headers=api.headers)
    _check_response(res, "fetch_messages")
    return res.json()


def _check_response(res, context: str) -> None:
    match res.status:
        case 401:
            raise AuthenticationError(f"Messaging API 401 ({context})")
        case 403 | 404:
            raise IOError(f"Messaging API {res.status} ({context})")
    if not res.ok:
        raise IOError(f"Messaging API {res.status} ({context}): {res.text()[:500]}")
