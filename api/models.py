"""
API models for LinkedIn outreach campaign
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any


class CampaignRequest(BaseModel):
    """Request model for starting a campaign"""
    username: Optional[str] = Field(None, description="LinkedIn username/email (deprecated, use cookies instead)")
    password: Optional[str] = Field(None, description="LinkedIn password (deprecated, use cookies instead)")
    cookies: Optional[List[Dict[str, Any]]] = Field(None, description="LinkedIn session cookies (preferred method)")
    urls: List[str] = Field(..., description="List of LinkedIn profile URLs to target")
    campaign_name: Optional[str] = Field(default="connect_follow_up", description="Campaign name")
    note: Optional[str] = Field(None, description="Optional note to include with connection requests (max 300 chars)")

    @field_validator('cookies', 'username', mode='before')
    @classmethod
    def validate_auth(cls, v, info):
        """Ensure either cookies OR username/password is provided"""
        return v

    def model_post_init(self, __context):
        """Validate that either cookies or credentials are provided"""
        if not self.cookies and not (self.username and self.password):
            raise ValueError("Either 'cookies' or both 'username' and 'password' must be provided")
        return self

    class Config:
        json_schema_extra = {
            "example": {
                "cookies": [
                    {
                        "name": "li_at",
                        "value": "your_session_cookie_value",
                        "domain": ".linkedin.com",
                        "path": "/",
                        "secure": True,
                        "httpOnly": True
                    }
                ],
                "urls": [
                    "https://www.linkedin.com/in/johndoe",
                    "https://www.linkedin.com/in/janedoe"
                ],
                "campaign_name": "connect_follow_up",
                "note": "Hi! I'd love to connect and discuss opportunities in the tech industry."
            }
        }


class CampaignResponse(BaseModel):
    """Response model for campaign operations"""
    success: bool
    message: str
    campaign_id: Optional[str] = None
    profiles_processed: Optional[int] = None


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    version: str


class StatusResponse(BaseModel):
    """Status response for a profile"""
    public_identifier: str
    url: str
    state: str
    full_name: Optional[str] = None
    headline: Optional[str] = None
    last_updated: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "public_identifier": "johndoe",
                "url": "https://www.linkedin.com/in/johndoe",
                "state": "CONNECTED",
                "full_name": "John Doe",
                "headline": "Software Engineer at Tech Co",
                "last_updated": "2025-12-29T12:00:00"
            }
        }


class MessageRequest(BaseModel):
    """Request model for sending messages"""
    cookies: Optional[List[Dict[str, Any]]] = Field(None, description="LinkedIn session cookies (preferred method)")
    username: Optional[str] = Field(None, description="LinkedIn username/email (deprecated, use cookies instead)")
    password: Optional[str] = Field(None, description="LinkedIn password (deprecated, use cookies instead)")
    url: str = Field(..., description="LinkedIn profile URL to send message to")
    message: str = Field(..., description="Message text to send (required)")

    class Config:
        json_schema_extra = {
            "example": {
                "cookies": [
                    {
                        "name": "li_at",
                        "value": "your_session_cookie_value",
                        "domain": ".linkedin.com",
                        "path": "/",
                        "secure": True,
                        "httpOnly": True
                    }
                ],
                "url": "https://www.linkedin.com/in/johndoe",
                "message": "Hi! I'd love to connect and discuss opportunities."
            }
        }


class MessageResponse(BaseModel):
    """Response model for message operations"""
    success: bool
    message: str
    url: Optional[str] = None
    public_identifier: Optional[str] = None
    status: Optional[str] = None