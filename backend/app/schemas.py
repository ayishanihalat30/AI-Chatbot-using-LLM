from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

LangCode = Literal["en", "ml", "hi", "ta", "kn", "te", "ar", "fr"]
Length = Literal["short", "medium", "detailed"]
Style = Literal["balanced", "friendly", "professional", "technical", "simple"]
Mode = Literal["general", "programming", "career", "education"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class PreferenceOut(ORM):
    language: LangCode
    answer_length: Length
    answer_style: Style
    memory_enabled: bool


class PreferenceIn(BaseModel):
    language: LangCode | None = None
    answer_length: Length | None = None
    answer_style: Style | None = None
    memory_enabled: bool | None = None


class UserOut(BaseModel):
    id: str
    email: str
    preferences: PreferenceOut


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=500)


class MemoryOut(ORM):
    id: str
    content: str
    created_at: datetime


class ChatCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ChatPatch(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChatOut(ORM):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(ORM):
    id: str
    role: str
    content: str
    citations: list | None = None
    created_at: datetime


class ChatDetail(ChatOut):
    messages: list[MessageOut]


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    document_ids: list[str] | None = Field(default=None, max_length=50)
    mode: Mode = "general"


class DocumentOut(ORM):
    id: str
    filename: str
    mime: str
    size: int
    status: str
    error: str | None = None
    summary: str | None = None
    chunk_count: int
    created_at: datetime
