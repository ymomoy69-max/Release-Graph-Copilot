from pydantic import BaseModel, EmailStr


class PaymentRequest(BaseModel):
    order_id: str
    amount: float
    currency: str = "USD"


class OrderRequest(BaseModel):
    product_id: str
    quantity: int = 1
    customer_email: EmailStr


class NotificationRequest(BaseModel):
    channel: str
    to: str
    body: str


class FailureMode(BaseModel):
    enabled: bool = False
    latency_ms: int = 0
