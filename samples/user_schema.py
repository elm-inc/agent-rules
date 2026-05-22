"""Pydantic schema for /test-data evaluation."""
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class User(BaseModel):
    """ユーザーエンティティ。

    関係制約 (LLM に推論してほしい):
    - hire_date <= termination_date (退職日があれば入社日より後)
    - status == DELETED の場合は termination_date 必須
    - balance >= 0
    - created_at <= updated_at
    """
    id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=64)
    email: EmailStr
    status: UserStatus
    hire_date: date
    termination_date: Optional[date] = None
    balance: Decimal = Field(ge=0)
    created_at: datetime
    updated_at: datetime
