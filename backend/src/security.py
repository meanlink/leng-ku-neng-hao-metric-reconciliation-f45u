import base64, hashlib, hmac, json, time
from fastapi import Header, HTTPException
from .config import JWT_SECRET

def hash_password(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()

def make_token(user: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": user["id"], "email": user["email"], "name": user["name"], "role": user["role"], "exp": int(time.time()) + 86400}
    def enc(obj):
        return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).rstrip(b"=").decode()
    body = enc(header) + "." + enc(payload)
    sig = hmac.new(JWT_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    return body + "." + base64.urlsafe_b64encode(sig).rstrip(b"=").decode()

def decode_token(token: str) -> dict:
    try:
        head, body, sig = token.split(".")
        expected = base64.urlsafe_b64encode(hmac.new(JWT_SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("signature")
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if payload["exp"] < time.time():
            raise ValueError("expired")
        return payload
    except Exception as exc:
        raise HTTPException(401, detail="登录已过期，请重新登录") from exc

def current_user(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, detail="需要登录")
    return decode_token(authorization[7:])

def require_roles(*roles):
    def checker(user=__import__("fastapi").Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, detail="当前角色无权执行该操作")
        return user
    return checker
