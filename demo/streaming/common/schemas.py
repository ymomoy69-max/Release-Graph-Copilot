from pydantic import BaseModel, EmailStr


class BillingRequest(BaseModel):
    session_id: str
    amount: float
    currency: str = "USD"


class SessionRequest(BaseModel):
    title_id: str
    profile_id: str = "default"
    customer_email: EmailStr


class NotificationRequest(BaseModel):
    channel: str
    to: str
    body: str


class FailureMode(BaseModel):
    enabled: bool = False
    latency_ms: int = 0
