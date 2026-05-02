class AuthenticationError(Exception):
    """Custom exception for 401 Unauthorized errors."""
    pass


class SessionExpiredError(AuthenticationError):
    """Session cookie (li_at) was revoked — caller must supply fresh cookies and retry."""
    pass


class TerminalStateError(Exception):
    """Profile is already done or dead — caller must skip it"""
    pass


class SkipProfile(Exception):
    """Profile must be skipped."""
    pass


class ReachedConnectionLimit(Exception):
    """ Weekly connection limit reached. """
    pass
