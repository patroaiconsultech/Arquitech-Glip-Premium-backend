import uuid
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .routes import router
from .auth_routes import router as auth_router
from .artifact_routes import router as artifact_router
from .pricing.routes import router as pricing_router
from .capabilities import CAPABILITIES
from .database import engine
from .readiness import database_readiness

app=FastAPI(
    title="GLIP Platform Backend",
    version="1.0.0rc8",
    docs_url="/docs" if settings.environment!="production" else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["GET","POST","PATCH","DELETE","OPTIONS"],
    allow_headers=[
        "Authorization","Content-Type","X-Request-ID","X-Correlation-ID",
        "X-GLIP-User-ID","X-GLIP-Tenant-ID"
    ],
    expose_headers=["X-Request-ID","X-Correlation-ID"],
)

@app.middleware("http")
async def request_context(request:Request,call_next):
    request_id=request.headers.get("X-Request-ID") or str(uuid.uuid4())
    correlation_id=request.headers.get("X-Correlation-ID") or request_id
    request.state.request_id=request_id
    request.state.correlation_id=correlation_id

    if (
        settings.auth_mode=="native_session"
        and request.method in {"POST","PUT","PATCH","DELETE"}
        and request.cookies.get(settings.auth_session_cookie_name)
    ):
        origin=request.headers.get("origin")
        if settings.environment in {"staging","production"} and origin not in settings.cors_list:
            from fastapi.responses import JSONResponse
            blocked=JSONResponse({"detail":"csrf_origin_rejected"},status_code=403)
            blocked.headers["X-Request-ID"]=request_id
            blocked.headers["X-Correlation-ID"]=correlation_id
            return blocked

    response=await call_next(request)
    response.headers["X-Request-ID"]=request_id
    response.headers["X-Correlation-ID"]=correlation_id
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Referrer-Policy"]="no-referrer"
    response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=()"
    if settings.environment=="production":
        response.headers["Strict-Transport-Security"]="max-age=31536000; includeSubDomains"
    return response

@app.get("/health/live")
def live():
    return {
        "status":"ok","service":"glip-backend","version":app.version,
        "release_id":settings.release_id
    }

@app.get("/health/ready")
def ready(response:Response):
    db_checks=database_readiness(
        engine,
        require_migration_head=settings.require_migration_head,
    )
    auth_ready=(
        settings.auth_mode=="dev_headers"
        or (
            settings.auth_mode=="native_session"
            and len(settings.auth_session_secret)>=32
            and len(settings.auth_password_pepper)>=32
        )
    )
    migration_ready=(
        db_checks["migration_current"] is True
        if settings.require_migration_head
        else True
    )
    core_ready=db_checks["database_connect"] and auth_ready and migration_ready
    response.status_code=200 if core_ready else 503
    return {
        "status":"ready" if core_ready else "not_ready",
        "core":{
            **db_checks,
            "auth_ready":auth_ready,
        },
        "optional":{
            "orkio_mode":settings.orkio_mode,
            "realtime":settings.realtime_mode,
            "voice":settings.voice_mode,
            "avatar":settings.avatar_mode,
        }
    }

@app.get("/api/v1/capabilities")
def capabilities():
    return {"schema_version":"glip.capability-registry.v1","items":CAPABILITIES}

app.include_router(auth_router)
app.include_router(router)
app.include_router(artifact_router)
app.include_router(pricing_router)
