from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: EmailStr
    role: str

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    """Every field optional so the frontend can PATCH one thing at a time without
    re-sending the whole profile."""

    full_name: str | None = None
    headline: str | None = None
    skills: str | None = None
    target_roles: str | None = None
    countries: str | None = None
    preferred_locations: str | None = None
    remote_only: bool | None = None
    min_salary: int | None = Field(default=None, ge=0)
    seniority: str | None = None
    resume_text: str | None = None
    resume_latex: str | None = None


class ProfileOut(BaseModel):
    user_id: str
    full_name: str | None = None
    headline: str | None = None
    skills: str | None = None
    target_roles: str | None = None
    countries: str = "in,us"
    preferred_locations: str | None = None
    remote_only: bool = False
    min_salary: int | None = None
    seniority: str | None = None
    resume_text: str | None = None
    resume_latex: str | None = None

    class Config:
        from_attributes = True
