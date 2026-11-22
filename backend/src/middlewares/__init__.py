import time, uuid
from fastapi import Request
from fastapi.responses import JSONResponse

async def request_context(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex[:12]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response

async def rate_limit(request: Request, call_next):
    bucket = getattr(request.app.state, "rate_bucket", {})
    now = time.time()
    key = request.client.host if request.client else "unknown"
    timestamps = [t for t in bucket.get(key, []) if now - t < 60]
    if len(timestamps) >= 120:
        return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"})
    timestamps.append(now)
    bucket[key] = timestamps
    request.app.state.rate_bucket = bucket
    return await call_next(request)
