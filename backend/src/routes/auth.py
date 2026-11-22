from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..db import db_cursor
from ..security import hash_password, make_token

router = APIRouter(prefix="/auth", tags=["auth"])
class LoginIn(BaseModel):
    email: str
    password: str

@router.post("/login")
def login(payload: LoginIn):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email=%s", (payload.email,))
        user = cur.fetchone()
    if not user or user["password_hash"] != hash_password(payload.password):
        raise HTTPException(401, detail="邮箱或密码错误")
    return {"access_token": make_token(user), "user": {"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"]}}
