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


class CampaignService:
    """Service to handle campaign operations"""

    def __init__(self):
        self.temp_files: Dict[str, Path] = {}

    def check_real_time_connection_status(
        self,
        urls: List[str],
        cookies: list = None,
        username: str = None,
        password: str = None
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
                config_path, _ = self.create_temporary_account_config(handle=handle)
                cookie_file = self.create_temporary_cookies_file(cookies, handle)
            elif username:
                handle = username.split('@')[0].replace('.', '_').replace('-', '_')
                config_path, _ = self.create_temporary_account_config(username, password, handle)
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
            original_secrets_path = conf.SECRETS_PATH
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

    def create_temporary_account_config(self, username: str = None, password: str = None, handle: str = None) -> tuple[Path, str]:
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
                # Generate random handle for cookie-based auth
                import random
                import string
                handle = 'cookie_' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

        from linkedin.conf import COOKIES_DIR
        
        config = {
            'accounts': {
                handle: {
                    'username': username or f'{handle}@example.com',  # Dummy email if using cookies
                    'password': password or 'cookie_auth',  # Dummy password if using cookies
                    'active': True,
                    'daily_connections': 35,
                    'daily_messages': 40,
                    'proxy': None,
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
        message: str = None
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

        Returns:
            Dict with campaign results
        """
        config_path = None
        csv_path = None
        cookie_file = None

        try:
            # Create temporary account config
            config_path, handle = self.create_temporary_account_config(username, password)

            # If cookies provided, create cookie file
            if cookies:
                cookie_file = self.create_temporary_cookies_file(cookies, handle)
                logger.info(f"Using cookie-based authentication for {handle}")

            csv_path = self.create_temporary_urls_csv(urls)

            logger.info(f"Using handle: {handle} for username: {username}")

            # We need to reload the conf module to pick up the new config
            import linkedin.conf as conf

            # Temporarily replace the secrets path
            original_secrets_path = conf.SECRETS_PATH
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

                return {
                    "success": True,
                    "message": f"Campaign '{campaign_name}' completed successfully",
                    "campaign_id": campaign_name,
                    "profiles_processed": len(urls)
                }

            finally:
                # Restore original config
                conf.SECRETS_PATH = original_secrets_path
                with open(original_secrets_path, "r", encoding="utf-8") as f:
                    conf._raw_config = yaml.safe_load(f) or {}
                conf._accounts_config = conf._raw_config.get("accounts", {})

                # Clean up temporary files
                if config_path:
                    self._cleanup_temp_file(config_path)
                if csv_path:
                    self._cleanup_temp_file(csv_path)
                if cookie_file:
                    self._cleanup_temp_file(cookie_file)

        except Exception as e:
            logger.error(f"Campaign failed: {str(e)}", exc_info=True)

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
            if cookie_file:
                self._cleanup_temp_file(cookie_file)

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

                config_path, _ = self.create_temporary_account_config(handle=handle)

                # Temporarily replace the secrets path
                original_secrets_path = conf.SECRETS_PATH
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
                    conf.SECRETS_PATH = original_secrets_path
                    with open(original_secrets_path, "r", encoding="utf-8") as f:
                        conf._raw_config = yaml.safe_load(f) or {}
                    conf._accounts_config = conf._raw_config.get("accounts", {})
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

                config_path, handle = self.create_temporary_account_config(username, password, handle)

                # Temporarily replace the secrets path
                original_secrets_path = conf.SECRETS_PATH
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
                    conf.SECRETS_PATH = original_secrets_path
                    with open(original_secrets_path, "r", encoding="utf-8") as f:
                        conf._raw_config = yaml.safe_load(f) or {}
                    conf._accounts_config = conf._raw_config.get("accounts", {})
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
        password: str = None
    ) -> Dict:
        """
        Send a message to a LinkedIn profile
        
        Args:
            url: LinkedIn profile URL to send message to
            message: Message text to send
            cookies: LinkedIn session cookies (preferred method)
            username: LinkedIn username/email (optional if cookies provided)
            password: LinkedIn password (optional if cookies provided)
            
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
                config_path, _ = self.create_temporary_account_config(handle=handle)
                cookie_file = self.create_temporary_cookies_file(cookies, handle)
            elif username:
                handle = username.split('@')[0].replace('.', '_').replace('-', '_')
                config_path, _ = self.create_temporary_account_config(username, password, handle)
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
            original_secrets_path = conf.SECRETS_PATH
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
                    else:
                        result = {
                            "success": False,
                            "message": "Profile not connected or message could not be sent",
                            "url": url,
                            "public_identifier": public_identifier,
                            "status": "SKIPPED"
                        }
                    
                    # Close browser session before restoring config
                    if session:
                        try:
                            session.close()
                            AccountSessionRegistry.clear_all()
                        except Exception as e:
                            logger.warning(f"Error closing session: {e}")
                    
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
            raise
        finally:
            # Clean up temporary files
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