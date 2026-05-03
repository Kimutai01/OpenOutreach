"""
Service layer for LinkedIn campaign operations
"""
import logging
import tempfile
from pathlib import Path
from typing import List, Dict
import pandas as pd
import yaml

from linkedin.csv_launcher import launch_from_csv
from linkedin.db.profiles import url_to_public_id

logger = logging.getLogger(__name__)


def _read_profile_states(handle: str, urls: List[str]) -> List[Dict]:
    """Read final per-profile states from the campaign SQLite DB."""
    from linkedin.conf import DATA_DIR
    from linkedin.db.models import Profile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_path = DATA_DIR / f"{handle}.db"
    if not db_path.exists():
        return []

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    db_session = Session()
    try:
        public_ids = [url_to_public_id(u) for u in urls]
        rows = db_session.query(Profile).filter(Profile.public_identifier.in_(public_ids)).all()
        id_to_state = {r.public_identifier: r.state for r in rows}
        return [
            {
                "url": u,
                "public_identifier": url_to_public_id(u),
                "state": id_to_state.get(url_to_public_id(u), "UNKNOWN"),
            }
            for u in urls
        ]
    finally:
        db_session.close()
        engine.dispose()


class CampaignService:
    """Service to handle campaign operations"""

    def __init__(self):
        self.temp_files: Dict[str, Path] = {}

    def check_real_time_connection_status(
        self,
        urls: List[str],
        cookies: list = None,
        username: str = None,
        password: str = None,
        proxy: dict = None,
    ) -> List[Dict]:
        """
        Check real-time connection status by navigating to LinkedIn profiles
        
        Args:
            urls: List of LinkedIn profile URLs to check
            cookies: LinkedIn session cookies (preferred method)
            username: LinkedIn username/email (optional if cookies provided)
            password: LinkedIn password (optional if cookies provided)
            
        Returns:
            List of dicts with connection status for each profile
        """
        from linkedin.actions.connection_status import get_connection_status
        from linkedin.db.profiles import url_to_public_id
        from linkedin.sessions.registry import AccountSessionRegistry, SessionKey
        from linkedin.campaigns.connect_follow_up import INPUT_CSV_PATH
        import linkedin.conf as conf
        
        config_path = None
        cookie_file = None
        session = None

        try:
            # Create temporary account config
            if cookies:
                # Generate handle for cookie-based auth
                import random
                import string
                handle = 'cookie_' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
                config_path, _ = self.create_temporary_account_config(handle=handle, proxy=proxy)
                cookie_file = self.create_temporary_cookies_file(cookies, handle)
            elif username:
                handle = username.split('@')[0].replace('.', '_').replace('-', '_')
                config_path, _ = self.create_temporary_account_config(username, password, handle, proxy=proxy)
            else:
                raise ValueError("Either 'cookies' or 'username' must be provided")

            # Update config to include cookie_file path
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f) or {}

            if cookie_file:
                config_data['accounts'][handle]['cookie_file'] = str(cookie_file)

            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(config_data, f, default_flow_style=False)

            # Temporarily replace the secrets path
            conf.SECRETS_PATH = config_path

            # Reload the config
            with open(config_path, "r", encoding="utf-8") as f:
                conf._raw_config = yaml.safe_load(f) or {}
            conf._accounts_config = conf._raw_config.get("accounts", {})

            try:
                # Create session key and get session
                key = SessionKey.make(handle, "status_check", INPUT_CSV_PATH)
                session = AccountSessionRegistry.get_or_create(
                    handle=key.handle,
                    campaign_name=key.campaign_name,
                    csv_hash=key.csv_hash,
                )
                
                # Ensure browser is ready
                session.ensure_browser()
                
                # Check status for each URL
                results = []
                for url in urls:
                    try:
                        public_identifier = url_to_public_id(url)
                        profile = {
                            "url": url,
                            "public_identifier": public_identifier,
                        }
                        
                        # Navigate to profile and check status
                        status = get_connection_status(session, profile)
                        
                        results.append({
                            "url": url,
                            "public_identifier": public_identifier,
                            "state": status.value,
                            "status": status.value,  # Alias for compatibility
                        })
                    except Exception as e:
                        logger.error(f"Error checking status for {url}: {str(e)}", exc_info=True)
                        results.append({
                            "url": url,
                            "public_identifier": None,
                            "state": "ERROR",
                            "status": "ERROR",
                            "error": str(e)
                        })
                
                return results
                
            finally:
                # Close browser session
                if session:
                    try:
                        session.close()
                        AccountSessionRegistry.clear_all()
                    except Exception as e:
                        logger.warning(f"Error closing session: {e}")
                
                # Restore original config - always use the actual secrets path, not a potentially deleted temp file
                from linkedin.conf import SECRETS_PATH as ACTUAL_SECRETS_PATH
                conf.SECRETS_PATH = ACTUAL_SECRETS_PATH
                if ACTUAL_SECRETS_PATH.exists():
                    with open(ACTUAL_SECRETS_PATH, "r", encoding="utf-8") as f:
                        conf._raw_config = yaml.safe_load(f) or {}
                    conf._accounts_config = conf._raw_config.get("accounts", {})
                else:
                    # If the actual secrets file doesn't exist, just reset to empty
                    conf._raw_config = {}
                    conf._accounts_config = {}
                
        except Exception as e:
            logger.error(f"Error in check_real_time_connection_status: {str(e)}", exc_info=True)
            raise
        finally:
            # Clean up temporary files
            if config_path:
                self._cleanup_temp_file(config_path)
            if cookie_file:
                self._cleanup_temp_file(cookie_file)

    @staticmethod
    def _stable_handle_from_cookies(cookies) -> str:
        """Derive a stable, repeatable handle from the li_at cookie value."""
        import hashlib
        cookie_list = cookies if isinstance(cookies, list) else (cookies or {}).get("cookies", [])
        for c in cookie_list:
            if c.get("name") == "li_at":
                return "li_" + hashlib.md5(c["value"].encode()).hexdigest()[:12]
        import random, string
        return "cookie_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

    def create_temporary_account_config(self, username: str = None, password: str = None, handle: str = None, proxy: dict = None) -> tuple[Path, str]:
        """
        Create a temporary account configuration file

        Args:
            username: LinkedIn username/email (optional if using cookies)
            password: LinkedIn password (optional if using cookies)
            handle: Account handle (defaults to username or random)

        Returns:
            Tuple of (Path to the temporary config file, handle)
        """
        if handle is None:
            if username:
                # Use a sanitized version of username as handle
                handle = username.split('@')[0].replace('.', '_').replace('-', '_')
            else:
                # Stable handle derived from li_at — same account always gets the same file
                handle = "cookie_pending"  # placeholder; callers that have cookies override below

        from linkedin.conf import COOKIES_DIR
        
        config = {
            'accounts': {
                handle: {
                    'username': username or f'{handle}@example.com',  # Dummy email if using cookies
                    'password': password or 'cookie_auth',  # Dummy password if using cookies
                    'active': True,
                    'daily_connections': 35,
                    'daily_messages': 40,
                    'proxy': proxy,
                    'booking_link': None,
                    'cookie_file': str(COOKIES_DIR / f"{handle}.json")  # Will be updated if cookies provided
                }
            }
        }

        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
        yaml.dump(config, temp_file, default_flow_style=False)
        temp_file.close()

        temp_path = Path(temp_file.name)
        self.temp_files[handle] = temp_path

        logger.info(f"Created temporary config for {handle} at {temp_path}")
        return temp_path, handle

    def create_temporary_cookies_file(self, cookies: list, handle: str) -> Path:
        """
        Create a temporary cookie storage state file for Playwright

        Args:
            cookies: List of cookie dictionaries (or full storage state with origins)
            handle: Account handle

        Returns:
            Path to the temporary cookie file
        """
        import json
        from linkedin.conf import COOKIES_DIR

        # Ensure cookies directory exists
        COOKIES_DIR.mkdir(exist_ok=True)

        # Create cookie file in the standard location
        cookie_file = COOKIES_DIR / f"{handle}.json"

        # Check if cookies is already in Playwright storage state format
        # (has both "cookies" and "origins" keys)
        if isinstance(cookies, dict) and "cookies" in cookies:
            # Already in storage state format
            storage_state = cookies
        else:
            # Just a list of cookies, wrap it in storage state format
            storage_state = {
                "cookies": cookies,
                "origins": []
            }

        # Normalize cookie sameSite values for Playwright compatibility
        # Playwright expects "None", "Lax", or "Strict", not "no_restriction" or "unspecified"
        for cookie in storage_state.get("cookies", []):
            if "sameSite" in cookie:
                same_site = cookie["sameSite"]
                if same_site == "no_restriction":
                    cookie["sameSite"] = "None"
                elif same_site == "unspecified":
                    cookie["sameSite"] = "Lax"

        with open(cookie_file, 'w') as f:
            json.dump(storage_state, f, indent=2)

        logger.info(f"Created temporary cookies file for {handle} at {cookie_file}")
        logger.debug(f"Saved {len(storage_state.get('cookies', []))} cookies")
        return cookie_file

    def create_temporary_urls_csv(self, urls: List[str]) -> Path:
        """
        Create a temporary CSV file with profile URLs

        Args:
            urls: List of LinkedIn profile URLs

        Returns:
            Path to the temporary CSV file
        """
        # Create DataFrame
        df = pd.DataFrame({'url': urls})

        # Add public identifiers
        df['public_identifier'] = df['url'].apply(url_to_public_id)

        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
        df.to_csv(temp_file.name, index=False)
        temp_file.close()

        temp_path = Path(temp_file.name)
        logger.info(f"Created temporary CSV with {len(urls)} URLs at {temp_path}")

        return temp_path

    def run_campaign(
        self,
        urls: List[str],
        campaign_name: str = "connect_follow_up",
        username: str = None,
        password: str = None,
        cookies: list = None,
        message: str = None,
        proxy: dict = None,
    ) -> Dict:
        """
        Run a LinkedIn outreach campaign

        Args:
            urls: List of LinkedIn profile URLs
            campaign_name: Name of the campaign
            username: LinkedIn username/email (optional if cookies provided)
            password: LinkedIn password (optional if cookies provided)
            cookies: LinkedIn session cookies (preferred method)
            message: Optional note to include with connection requests
            proxy: Proxy dict with server/username/password (assigned by Phoenix backend)

        Returns:
            Dict with campaign results
        """
        config_path = None
        csv_path = None
        handle = None

        try:
            # Derive a stable handle so the cookie file is reused across campaigns
            if cookies and not username:
                stable_handle = self._stable_handle_from_cookies(cookies)
            else:
                stable_handle = None  # create_temporary_account_config will derive from username

            config_path, handle = self.create_temporary_account_config(username, password, handle=stable_handle, proxy=proxy)

            if cookies:
                self.create_temporary_cookies_file(cookies, handle)
                logger.info(f"Writing caller-provided cookies for {handle}")

            csv_path = self.create_temporary_urls_csv(urls)

            logger.info(f"Using handle: {handle} for username: {username}")

            # We need to reload the conf module to pick up the new config
            import linkedin.conf as conf
            from linkedin.conf import SECRETS_PATH as ACTUAL_SECRETS_PATH

            # Temporarily replace the secrets path
            conf.SECRETS_PATH = config_path

            # Reload the config
            with open(config_path, "r", encoding="utf-8") as f:
                conf._raw_config = yaml.safe_load(f) or {}
            conf._accounts_config = conf._raw_config.get("accounts", {})

            try:
                # Launch campaign
                logger.info(f"Starting campaign '{campaign_name}' for @{handle}")
                launch_from_csv(
                    handle=handle,
                    csv_path=csv_path,
                    campaign_name=campaign_name,
                    message=message
                )

                # Close all browser sessions after campaign completes
                from linkedin.sessions.registry import AccountSessionRegistry
                AccountSessionRegistry.clear_all()
                logger.info("All browser sessions closed after campaign completion")

                # Query per-profile outcomes from the campaign DB
                profiles_detail = _read_profile_states(handle, urls)

                return {
                    "success": True,
                    "message": f"Campaign '{campaign_name}' completed successfully",
                    "campaign_id": campaign_name,
                    "profiles_processed": len(urls),
                    "profiles": profiles_detail,
                }

            finally:
                # Restore original config - always use the actual secrets path, not a potentially deleted temp file
                conf.SECRETS_PATH = ACTUAL_SECRETS_PATH
                if ACTUAL_SECRETS_PATH.exists():
                    with open(ACTUAL_SECRETS_PATH, "r", encoding="utf-8") as f:
                        conf._raw_config = yaml.safe_load(f) or {}
                    conf._accounts_config = conf._raw_config.get("accounts", {})
                else:
                    # If the actual secrets file doesn't exist, just reset to empty
                    conf._raw_config = {}
                    conf._accounts_config = {}

                # Clean up temporary files (cookie file is intentionally kept — it's a persistent proxy-bound session)
                if config_path:
                    self._cleanup_temp_file(config_path)
                if csv_path:
                    self._cleanup_temp_file(csv_path)

        except Exception as e:
            from linkedin.navigation.exceptions import SessionExpiredError

            is_session_expired = isinstance(e, SessionExpiredError) or "401 Unauthorized" in str(e)

            if is_session_expired:
                logger.warning(f"Session expired for {handle} — stale cookie file deleted, retry with fresh cookies")
            else:
                logger.error(f"Campaign failed: {str(e)}", exc_info=True)

            # Cookie file is already deleted inside scrape_profile (authwall path) or here for raw 401s.
            if handle and not isinstance(e, SessionExpiredError) and "401 Unauthorized" in str(e):
                from linkedin.conf import COOKIES_DIR
                stale = COOKIES_DIR / f"{handle}.json"
                if stale.exists():
                    stale.unlink()
                    logger.info(f"Deleted stale session for {handle} — next campaign will re-login via proxy")

            # Close browsers even on error to prevent resource leaks
            try:
                from linkedin.sessions.registry import AccountSessionRegistry
                AccountSessionRegistry.clear_all()
                logger.info("All browser sessions closed after campaign error")
            except Exception as cleanup_error:
                logger.warning(f"Failed to close browser sessions: {cleanup_error}")

            # Clean up on error
            if config_path:
                self._cleanup_temp_file(config_path)
            if csv_path:
                self._cleanup_temp_file(csv_path)

            if is_session_expired:
                return {
                    "success": False,
                    "error_code": "session_expired",
                    "message": "LinkedIn session expired. Proxy IP changed — retry with fresh cookies.",
                    "campaign_id": None,
                    "profiles_processed": 0
                }

            return {
                "success": False,
                "message": f"Campaign failed: {str(e)}",
                "campaign_id": None,
                "profiles_processed": 0
            }

    def get_profile_status_by_handle(self, handle: str, url: str, temp_config: bool = False) -> Dict:
        """
        Get the status of a profile using handle directly

        Args:
            handle: Account handle (derived from username or cookie session)
            url: LinkedIn profile URL to check
            temp_config: Whether a temporary config was created (for cookie-based auth)

        Returns:
            Dict with profile status information
        """
        config_path = None

        try:
            from linkedin.db.profiles import url_to_public_id
            from linkedin.db.engine import Database
            from linkedin.db.models import Profile

            # Get public identifier from URL
            public_identifier = url_to_public_id(url)

            # If this is a cookie-based handle, create temporary config
            if temp_config:
                import linkedin.conf as conf
                from linkedin.conf import SECRETS_PATH as ACTUAL_SECRETS_PATH

                config_path, _ = self.create_temporary_account_config(handle=handle)

                # Temporarily replace the secrets path
                conf.SECRETS_PATH = config_path

                # Reload the config
                with open(config_path, "r", encoding="utf-8") as f:
                    conf._raw_config = yaml.safe_load(f) or {}
                conf._accounts_config = conf._raw_config.get("accounts", {})

            try:
                # Open database for this handle
                db = Database.from_handle(handle)
                session = db.get_session()

                try:
                    # Query profile directly from database
                    profile_row = session.query(Profile).filter_by(
                        public_identifier=public_identifier
                    ).first()

                    if profile_row is None:
                        return {
                            "found": False,
                            "public_identifier": public_identifier,
                            "url": url,
                            "state": "NOT_FOUND",
                            "message": "Profile not found in database"
                        }

                    # Extract profile data
                    profile_data = profile_row.profile or {}

                    return {
                        "found": True,
                        "public_identifier": public_identifier,
                        "url": url,
                        "state": profile_row.state,
                        "full_name": profile_data.get("full_name"),
                        "headline": profile_data.get("headline"),
                        "last_updated": profile_row.updated_at.isoformat() if profile_row.updated_at else None
                    }

                finally:
                    session.close()
                    db.close()

            finally:
                # Restore original config if we created a temporary one
                if temp_config and config_path:
                    import linkedin.conf as conf
                    from linkedin.conf import SECRETS_PATH as ACTUAL_SECRETS_PATH
                    conf.SECRETS_PATH = ACTUAL_SECRETS_PATH
                    if ACTUAL_SECRETS_PATH.exists():
                        with open(ACTUAL_SECRETS_PATH, "r", encoding="utf-8") as f:
                            conf._raw_config = yaml.safe_load(f) or {}
                        conf._accounts_config = conf._raw_config.get("accounts", {})
                    else:
                        conf._raw_config = {}
                        conf._accounts_config = {}
                    self._cleanup_temp_file(config_path)

        except Exception as e:
            logger.error(f"Failed to get profile status: {str(e)}", exc_info=True)

            # Clean up on error
            if config_path:
                self._cleanup_temp_file(config_path)

            return {
                "found": False,
                "public_identifier": None,
                "url": url,
                "state": "ERROR",
                "message": f"Error: {str(e)}"
            }

    def get_profile_status(self, username: str, url: str, password: str = None) -> Dict:
        """
        Get the status of a profile

        Args:
            username: LinkedIn username/email (to identify the correct database)
            url: LinkedIn profile URL to check
            password: LinkedIn password (optional, used to create temp config if account not in YAML)

        Returns:
            Dict with profile status information
        """
        config_path = None

        try:
            from linkedin.db.profiles import url_to_public_id
            from linkedin.db.engine import Database

            # Get handle from username
            handle = username.split('@')[0].replace('.', '_').replace('-', '_')

            # Get public identifier from URL
            public_identifier = url_to_public_id(url)

            # If password provided, create temporary config (similar to run_campaign)
            if password:
                import yaml
                import linkedin.conf as conf
                from linkedin.conf import SECRETS_PATH as ACTUAL_SECRETS_PATH

                config_path, handle = self.create_temporary_account_config(username, password, handle)

                # Temporarily replace the secrets path
                conf.SECRETS_PATH = config_path

                # Reload the config
                with open(config_path, "r", encoding="utf-8") as f:
                    conf._raw_config = yaml.safe_load(f) or {}
                conf._accounts_config = conf._raw_config.get("accounts", {})

            try:
                # Open database for this handle
                db = Database.from_handle(handle)
                session = db.get_session()

                try:
                    # Query profile directly from database (don't use get_profile helper)
                    from linkedin.db.models import Profile

                    profile_row = session.query(Profile).filter_by(
                        public_identifier=public_identifier
                    ).first()

                    if profile_row is None:
                        return {
                            "found": False,
                            "public_identifier": public_identifier,
                            "url": url,
                            "state": "NOT_FOUND",
                            "message": "Profile not found in database"
                        }

                    # Extract profile data
                    profile_data = profile_row.profile or {}

                    return {
                        "found": True,
                        "public_identifier": public_identifier,
                        "url": url,
                        "state": profile_row.state,
                        "full_name": profile_data.get("full_name"),
                        "headline": profile_data.get("headline"),
                        "last_updated": profile_row.updated_at.isoformat() if profile_row.updated_at else None
                    }

                finally:
                    session.close()
                    db.close()

            finally:
                # Restore original config if we created a temporary one
                if password and config_path:
                    import linkedin.conf as conf
                    from linkedin.conf import SECRETS_PATH as ACTUAL_SECRETS_PATH
                    conf.SECRETS_PATH = ACTUAL_SECRETS_PATH
                    if ACTUAL_SECRETS_PATH.exists():
                        with open(ACTUAL_SECRETS_PATH, "r", encoding="utf-8") as f:
                            conf._raw_config = yaml.safe_load(f) or {}
                        conf._accounts_config = conf._raw_config.get("accounts", {})
                    else:
                        conf._raw_config = {}
                        conf._accounts_config = {}
                    self._cleanup_temp_file(config_path)

        except Exception as e:
            logger.error(f"Failed to get profile status: {str(e)}", exc_info=True)

            # Clean up on error
            if config_path:
                self._cleanup_temp_file(config_path)

            return {
                "found": False,
                "public_identifier": None,
                "url": url,
                "state": "ERROR",
                "message": f"Error: {str(e)}"
            }

    def send_message(
        self,
        url: str,
        message: str,
        cookies: list = None,
        username: str = None,
        password: str = None,
        proxy: dict = None,
    ) -> Dict:
        """
        Send a message to a LinkedIn profile

        Args:
            url: LinkedIn profile URL to send message to
            message: Message text to send
            cookies: LinkedIn session cookies (preferred method)
            username: LinkedIn username/email (optional if cookies provided)
            password: LinkedIn password (optional if cookies provided)
            proxy: Proxy dict with server/username/password (assigned by Phoenix backend)

        Returns:
            Dict with message sending result
        """
        from linkedin.actions.message import send_follow_up_message
        from linkedin.actions.profile import scrape_profile
        from linkedin.db.profiles import url_to_public_id
        from linkedin.sessions.registry import AccountSessionRegistry, SessionKey
        from linkedin.campaigns.connect_follow_up import INPUT_CSV_PATH
        from linkedin.navigation.enums import MessageStatus
        import linkedin.conf as conf

        config_path = None
        cookie_file = None
        session = None

        try:
            # Create temporary account config
            if cookies:
                # Generate handle for cookie-based auth
                import random
                import string
                handle = 'cookie_' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
                config_path, _ = self.create_temporary_account_config(handle=handle, proxy=proxy)
                cookie_file = self.create_temporary_cookies_file(cookies, handle)
            elif username:
                handle = username.split('@')[0].replace('.', '_').replace('-', '_')
                config_path, _ = self.create_temporary_account_config(username, password, handle, proxy=proxy)
            else:
                raise ValueError("Either 'cookies' or 'username' must be provided")

            # Update config to include cookie_file path
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f) or {}
            
            if cookie_file:
                config_data['accounts'][handle]['cookie_file'] = str(cookie_file)
            
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(config_data, f, default_flow_style=False)
            
            # Store the actual secrets path (not a temporary one)
            from linkedin.conf import SECRETS_PATH as ACTUAL_SECRETS_PATH
            
            # Temporarily replace the secrets path
            conf.SECRETS_PATH = config_path
            
            # Reload the config
            with open(config_path, "r", encoding="utf-8") as f:
                conf._raw_config = yaml.safe_load(f) or {}
            conf._accounts_config = conf._raw_config.get("accounts", {})
            
            try:
                # Create session key and get session
                key = SessionKey.make(handle, "send_messages", INPUT_CSV_PATH)
                session = AccountSessionRegistry.get_or_create(
                    handle=key.handle,
                    campaign_name=key.campaign_name,
                    csv_hash=key.csv_hash,
                )
                
                # Ensure browser is ready
                session.ensure_browser()
                
                # Process single URL
                try:
                    public_identifier = url_to_public_id(url)
                    profile = {
                        "url": url,
                        "public_identifier": public_identifier,
                    }
                    
                    # Try to scrape profile to get full_name (helps with messaging)
                    try:
                        enriched_profile, _ = scrape_profile(key, profile)
                        if enriched_profile:
                            profile = enriched_profile
                    except Exception as e:
                        logger.warning(f"Could not scrape profile {public_identifier}, using basic profile: {e}")
                        # Continue with basic profile - send_follow_up_message can work with just public_identifier
                    
                    # Send message
                    status = send_follow_up_message(
                        key=key,
                        profile=profile,
                        message=message
                    )
                    
                    if status == MessageStatus.SENT:
                        result = {
                            "success": True,
                            "message": "Message sent successfully",
                            "url": url,
                            "public_identifier": public_identifier,
                            "status": "SENT"
                        }
                        logger.info(f"Message sending completed successfully for {public_identifier}")
                    else:
                        result = {
                            "success": False,
                            "message": "Profile not connected or message could not be sent",
                            "url": url,
                            "public_identifier": public_identifier,
                            "status": "SKIPPED"
                        }
                        logger.info(f"Message sending skipped for {public_identifier} - status: {status}")
                    
                    # Close browser session before restoring config
                    if session:
                        try:
                            session.close()
                            AccountSessionRegistry.clear_all()
                            logger.debug("Browser session closed successfully")
                        except Exception as e:
                            logger.warning(f"Error closing session: {e}")
                    
                    # Log before returning to ensure we reach this point
                    logger.info(f"Returning result for {public_identifier}: success={result['success']}, status={result['status']}")
                    return result
                        
                except Exception as e:
                    logger.error(f"Error sending message to {url}: {str(e)}", exc_info=True)
                    result = {
                        "success": False,
                        "message": f"Error: {str(e)}",
                        "url": url,
                        "public_identifier": url_to_public_id(url) if url else None,
                        "status": "ERROR"
                    }
                    
                    # Close browser session before restoring config
                    if session:
                        try:
                            session.close()
                            AccountSessionRegistry.clear_all()
                        except Exception as e:
                            logger.warning(f"Error closing session: {e}")
                    
                    return result
                
            finally:
                # Restore original config - use the actual secrets path, not the stored one
                # (which might be a temporary file from a previous request)
                conf.SECRETS_PATH = ACTUAL_SECRETS_PATH
                if ACTUAL_SECRETS_PATH.exists():
                    with open(ACTUAL_SECRETS_PATH, "r", encoding="utf-8") as f:
                        conf._raw_config = yaml.safe_load(f) or {}
                    conf._accounts_config = conf._raw_config.get("accounts", {})
                else:
                    # If the actual secrets file doesn't exist, just reset to empty
                    conf._raw_config = {}
                    conf._accounts_config = {}
                
        except Exception as e:
            logger.error(f"Error in send_message: {str(e)}", exc_info=True)
            # Return error response instead of raising
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "url": url,
                "public_identifier": url_to_public_id(url) if url else None,
                "status": "ERROR"
            }
        finally:
            # Clean up temporary files
            if config_path:
                self._cleanup_temp_file(config_path)
            if cookie_file:
                self._cleanup_temp_file(cookie_file)

    def fetch_conversation(
        self,
        url: str,
        cookies: list = None,
        username: str = None,
        password: str = None,
        proxy: dict = None,
    ) -> Dict:
        """Fetch conversation history with a LinkedIn profile."""
        from linkedin.actions.conversations import get_conversation
        from linkedin.db.profiles import url_to_public_id
        from linkedin.sessions.registry import AccountSessionRegistry, SessionKey
        from linkedin.campaigns.connect_follow_up import INPUT_CSV_PATH
        import linkedin.conf as conf

        config_path = None
        cookie_file = None
        session = None

        try:
            if cookies:
                import random, string
                handle = 'cookie_' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
                config_path, _ = self.create_temporary_account_config(handle=handle, proxy=proxy)
                cookie_file = self.create_temporary_cookies_file(cookies, handle)
            elif username:
                handle = username.split('@')[0].replace('.', '_').replace('-', '_')
                config_path, _ = self.create_temporary_account_config(username, password, handle, proxy=proxy)
            else:
                raise ValueError("Either 'cookies' or 'username' must be provided")

            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f) or {}
            if cookie_file:
                config_data['accounts'][handle]['cookie_file'] = str(cookie_file)
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(config_data, f, default_flow_style=False)

            from linkedin.conf import SECRETS_PATH as ACTUAL_SECRETS_PATH
            conf.SECRETS_PATH = config_path
            with open(config_path, "r", encoding="utf-8") as f:
                conf._raw_config = yaml.safe_load(f) or {}
            conf._accounts_config = conf._raw_config.get("accounts", {})

            try:
                key = SessionKey.make(handle, "fetch_conversation", INPUT_CSV_PATH)
                session = AccountSessionRegistry.get_or_create(
                    handle=key.handle,
                    campaign_name=key.campaign_name,
                    csv_hash=key.csv_hash,
                )
                session.ensure_browser()

                public_identifier = url_to_public_id(url)
                messages = get_conversation(session, url)

                return {
                    "success": True,
                    "url": url,
                    "public_identifier": public_identifier,
                    "messages": messages or [],
                    "count": len(messages) if messages else 0,
                }

            finally:
                if session:
                    try:
                        session.close()
                        AccountSessionRegistry.clear_all()
                    except Exception as e:
                        logger.warning(f"Error closing session: {e}")

                conf.SECRETS_PATH = ACTUAL_SECRETS_PATH
                if ACTUAL_SECRETS_PATH.exists():
                    with open(ACTUAL_SECRETS_PATH, "r", encoding="utf-8") as f:
                        conf._raw_config = yaml.safe_load(f) or {}
                    conf._accounts_config = conf._raw_config.get("accounts", {})
                else:
                    conf._raw_config = {}
                    conf._accounts_config = {}

        except Exception as e:
            logger.error(f"fetch_conversation failed: {e}", exc_info=True)
            return {
                "success": False,
                "url": url,
                "public_identifier": None,
                "messages": [],
                "count": 0,
                "error": str(e),
            }
        finally:
            if config_path:
                self._cleanup_temp_file(config_path)
            if cookie_file:
                self._cleanup_temp_file(cookie_file)

    def _cleanup_temp_file(self, path: Path):
        """Clean up temporary file"""
        try:
            if path.exists():
                path.unlink()
                logger.debug(f"Cleaned up temp file: {path}")
        except Exception as e:
            logger.warning(f"Failed to clean up {path}: {e}")