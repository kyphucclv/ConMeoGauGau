"""Same-origin HTTP shell for the FastAPI + React migration."""

from __future__ import annotations

import os
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

from fastapi import Cookie, Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from auth import AppUser, authenticate
from db import create_pool, fetch_one
from session_store import AuthenticatedSession, SessionStore
from api.dashboard_reads import DashboardResponse, dashboard_for
from api.learner_reads import LearnerDetail, LearnerPage, LearnerReadService
from api.learner_start import LearnerStartBody, LearnerStartOptions, LearnerStartResult, learner_start_options, start_learner
from api.learner_transfer import LearnerTransferBody, LearnerTransferOptions, LearnerTransferResult, learner_transfer_options, transfer_learner
from api.profile_commands import ProfileOptions, ProfileUpdateBody, ProfileUpdateResult, profile_options, update_profile
from services.base import CommandError


@dataclass(frozen=True)
class Settings:
    database_url: str
    origin: str
    secure_cookie: bool = True
    cookie_name: str = "english_class_session"
    serve_static: bool = True

    @classmethod
    def from_env(cls):
        url = os.getenv("APP_DATABASE_URL") or os.getenv("DATABASE_URL")
        if not url:
            raise RuntimeError("APP_DATABASE_URL is required")
        return cls(url, os.getenv("APP_ORIGIN", "https://english-class.local"), os.getenv("APP_COOKIE_SECURE", "true").lower() == "true")


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)


class PublicUser(BaseModel):
    user_id: int
    username: str
    full_name: str
    role: Literal["admin", "editor", "viewer"]


class AuthResponse(BaseModel):
    user: PublicUser
    csrf_token: str


def _user(user: AppUser) -> PublicUser:
    return PublicUser(user_id=user.user_id, username=user.username, full_name=user.full_name, role=user.role)


def _error(request: Request, status: int, code: str, message: str, field_errors=None):
    return JSONResponse(status_code=status, content={"code": code, "message": message, "field_errors": field_errors or {}, "request_id": request.state.request_id})


def create_app(settings: Settings | None = None, *, pool=None) -> FastAPI:
    settings = settings or Settings.from_env()
    owns_pool = pool is None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pool = pool or create_pool(settings.database_url, application_name="english_class_fastapi")
        app.state.sessions = SessionStore(app.state.pool)
        app.state.login_failures = defaultdict(deque)
        yield
        if owns_pool:
            app.state.pool.closeall()

    app = FastAPI(title="English Class API", version="1.0.0", lifespan=lifespan)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        fields = {".".join(str(part) for part in err["loc"][1:]): err["msg"] for err in exc.errors()}
        return _error(request, 422, "invalid_input", "Request validation failed.", fields)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        return _error(request, 500, "internal_error", "An unexpected error occurred.")

    def current_session(request: Request, session_cookie: str | None = Cookie(default=None, alias=settings.cookie_name)):
        session = request.app.state.sessions.authenticate(session_cookie)
        if not session:
            return None
        return session

    def require_session(request: Request, session=Depends(current_session)):
        if not session:
            raise AuthFailure()
        return session

    def require_hr_session(session: AuthenticatedSession = Depends(require_session)):
        if session.user.role not in {"admin", "editor"}:
            raise ForbiddenFailure()
        return session

    def require_hr_csrf(
        request: Request,
        session: AuthenticatedSession = Depends(require_hr_session),
        csrf: str | None = Header(default=None, alias="X-CSRF-Token"),
    ):
        if not request.app.state.sessions.csrf_matches(session, csrf):
            raise CsrfFailure()
        return session

    @app.exception_handler(AuthFailure)
    async def auth_error(request: Request, exc: "AuthFailure"):
        return _error(request, 401, "unauthenticated", "Sign in is required.")

    @app.exception_handler(ForbiddenFailure)
    async def forbidden_error(request: Request, exc: "ForbiddenFailure"):
        return _error(request, 403, "forbidden", "You do not have access to this workspace.")

    @app.exception_handler(NotFoundFailure)
    async def not_found_error(request: Request, exc: "NotFoundFailure"):
        return _error(request, 404, "not_found", "Learner was not found.")

    @app.exception_handler(CsrfFailure)
    async def csrf_error(request: Request, exc: "CsrfFailure"):
        return _error(request, 403, "csrf_rejected", "CSRF token is invalid.")

    @app.exception_handler(CommandError)
    async def command_error(request: Request, exc: CommandError):
        status = {
            "unauthorized": 401,
            "forbidden": 403,
            "not_found": 404,
            "invalid_input": 422,
        }.get(exc.code, 409)
        return _error(request, status, exc.code, exc.message)

    @app.get("/api/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/api/health/ready")
    def ready(request: Request):
        try:
            row = fetch_one(
                request.app.state.pool,
                """SELECT to_regclass('app_sessions') AS sessions,
                          EXISTS (SELECT 1 FROM schema_migrations WHERE version = '020_app_sessions') AS migrated""",
            )
        except Exception:
            return _error(request, 503, "not_ready", "Database is not ready.")
        if not row or row["sessions"] is None or not row["migrated"]:
            return _error(request, 503, "not_ready", "Database schema is not ready.")
        return {"status": "ready"}

    @app.post("/api/auth/login", response_model=AuthResponse)
    def login(body: LoginBody, request: Request, response: Response):
        origin = request.headers.get("origin")
        referer = request.headers.get("referer", "")
        if origin != settings.origin and not referer.startswith(settings.origin + "/"):
            return _error(request, 403, "invalid_origin", "Request origin is not allowed.")
        key = (request.client.host if request.client else "unknown", body.username.strip().lower())
        failures = request.app.state.login_failures[key]
        cutoff = time.monotonic() - 300
        while failures and failures[0] < cutoff:
            failures.popleft()
        if len(failures) >= 5:
            return _error(request, 429, "rate_limited", "Too many sign-in attempts. Try again later.")
        user = authenticate(request.app.state.pool, body.username, body.password)
        if not user:
            failures.append(time.monotonic())
            return _error(request, 401, "invalid_credentials", "Username or password is incorrect.")
        failures.clear()
        issued = request.app.state.sessions.create(user.user_id)
        response.set_cookie(settings.cookie_name, issued.token, max_age=12 * 60 * 60, httponly=True, secure=settings.secure_cookie, samesite="lax", path="/")
        return {"user": _user(user), "csrf_token": issued.csrf_token}

    @app.get("/api/auth/me", response_model=AuthResponse)
    def me(session: AuthenticatedSession = Depends(require_session)):
        return {"user": _user(session.user), "csrf_token": session.csrf_token}

    @app.get("/api/dashboard", response_model=DashboardResponse)
    def dashboard(request: Request, session: AuthenticatedSession = Depends(require_session)):
        return dashboard_for(request.app.state.pool, session.user.role)

    @app.get("/api/learners", response_model=LearnerPage)
    def learners(
        request: Request,
        q: str = Query(default="", max_length=200),
        learning_status: Literal["all", "current", "not_current"] = "all",
        class_code: str | None = Query(default=None, max_length=100),
        course: str | None = Query(default=None, max_length=200),
        pic: str | None = Query(default=None, max_length=200),
        business_unit: str | None = Query(default=None, max_length=200),
        job_role: str | None = Query(default=None, max_length=200),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=100),
        session: AuthenticatedSession = Depends(require_hr_session),
    ):
        return LearnerReadService(request.app.state.pool).search(
            q=q,
            learning_status=learning_status,
            class_code=class_code,
            course=course,
            pic=pic,
            business_unit=business_unit,
            job_role=job_role,
            page=page,
            page_size=page_size,
        )

    @app.get("/api/learners/profile-options", response_model=ProfileOptions)
    def learner_profile_options(
        request: Request,
        session: AuthenticatedSession = Depends(require_hr_session),
    ):
        return profile_options(request.app.state.pool)

    @app.get("/api/learners/start-options", response_model=LearnerStartOptions)
    def learner_start_option_list(
        request: Request,
        session: AuthenticatedSession = Depends(require_hr_session),
    ):
        return learner_start_options(request.app.state.pool)

    @app.post("/api/learners/start", response_model=LearnerStartResult)
    def learner_start_confirm(
        body: LearnerStartBody,
        request: Request,
        session: AuthenticatedSession = Depends(require_hr_csrf),
    ):
        return start_learner(request.app.state.pool, session.user.user_id, body)

    @app.get("/api/learners/{employee_id}", response_model=LearnerDetail)
    def learner_detail(
        employee_id: int,
        request: Request,
        session: AuthenticatedSession = Depends(require_hr_session),
    ):
        detail = LearnerReadService(request.app.state.pool).detail(employee_id)
        if detail is None:
            raise NotFoundFailure()
        return detail

    @app.patch("/api/learners/{employee_id}/profile", response_model=ProfileUpdateResult)
    def learner_profile_update(
        employee_id: int,
        body: ProfileUpdateBody,
        request: Request,
        session: AuthenticatedSession = Depends(require_hr_csrf),
    ):
        return update_profile(request.app.state.pool, session.user.user_id, employee_id, body)

    @app.get("/api/run-enrollments/{run_enrollment_id}/transfer-options", response_model=LearnerTransferOptions)
    def learner_transfer_option_list(
        run_enrollment_id: int,
        request: Request,
        session: AuthenticatedSession = Depends(require_hr_session),
    ):
        return learner_transfer_options(request.app.state.pool, run_enrollment_id)

    @app.post("/api/run-enrollments/{run_enrollment_id}/transfer", response_model=LearnerTransferResult)
    def learner_transfer_confirm(
        run_enrollment_id: int,
        body: LearnerTransferBody,
        request: Request,
        session: AuthenticatedSession = Depends(require_hr_csrf),
    ):
        return transfer_learner(request.app.state.pool, session.user.user_id, run_enrollment_id, body)

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request, response: Response, session: AuthenticatedSession = Depends(require_session), csrf: str | None = Header(default=None, alias="X-CSRF-Token"), session_cookie: str | None = Cookie(default=None, alias=settings.cookie_name)):
        if not request.app.state.sessions.csrf_matches(session, csrf):
            return _error(request, 403, "csrf_rejected", "CSRF token is invalid.")
        request.app.state.sessions.revoke(session_cookie)
        response.status_code = 204
        response.delete_cookie(settings.cookie_name, path="/", secure=settings.secure_cookie, httponly=True, samesite="lax")
        return response

    static_dir = Path(__file__).resolve().parents[1] / "web" / "dist"
    if settings.serve_static and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    return app


class AuthFailure(Exception):
    pass


class ForbiddenFailure(Exception):
    pass


class NotFoundFailure(Exception):
    pass


class CsrfFailure(Exception):
    pass
