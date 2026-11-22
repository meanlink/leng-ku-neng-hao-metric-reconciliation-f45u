from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .db import init_db
from .middlewares import request_context, rate_limit
from .routes import auth, sources, contracts, reconcile, reports, dashboard, energy_close, billing

app = FastAPI(title="冷库能耗指标对账")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
app.middleware("http")(request_context)
app.middleware("http")(rate_limit)
app.include_router(auth.router)
app.include_router(sources.router)
app.include_router(contracts.router)
app.include_router(reconcile.router)
app.include_router(reports.router)
app.include_router(dashboard.router)
app.include_router(energy_close.router)
app.include_router(billing.router)

@app.on_event("startup")
def startup():
    init_db()

@app.get("/health")
def health():
    return {"status": "ok", "service": "coldstore-energy-reconcile"}
