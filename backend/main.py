import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Generator, List, Optional

import jwt
import pymysql
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, EmailStr, Field


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _env(name: str, default: Optional[str] = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value or ""


class Settings:
    app_name: str = _env("APP_NAME", "BNR Approval System API")
    environment: str = _env("ENVIRONMENT", "development")
    debug: bool = _env("DEBUG", "false").lower() == "true"

    db_host: str = _env("DB_HOST", required=True)
    db_port: int = int(_env("DB_PORT", "3306"))
    db_user: str = _env("DB_USER", required=True)
    db_password: str = _env("DB_PASSWORD", required=True)
    db_name: str = _env("DB_NAME", required=True)

    jwt_secret: str = _env("JWT_SECRET", required=True)
    jwt_algorithm: str = _env("JWT_ALGORITHM", "HS256")
    jwt_expires_minutes: int = int(_env("JWT_EXPIRES_MINUTES", "1440"))

    cors_origins: List[str] = [
        origin.strip()
        for origin in _env("CORS_ORIGINS", "*").split(",")
        if origin.strip()
    ]


settings = Settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@contextmanager
def db_connection() -> Generator[pymysql.connections.Connection, None, None]:
    conn = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RequestCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=5, max_length=2000)


class DecisionRequest(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    comment: Optional[str] = Field(default=None, max_length=600)


class ApiResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    success: bool
    message: str


def json_success(message: str, **kwargs: Any) -> Dict[str, Any]:
    return {"success": True, "message": message, **kwargs}


def json_error(message: str, **kwargs: Any) -> Dict[str, Any]:
    return {"success": False, "message": message, **kwargs}


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_access_token(payload: dict) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expires_minutes)
    to_encode = {**payload, "exp": expires}
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def get_current_user(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization token required")

    token = authorization.replace("Bearer ", "", 1).strip()
    payload = decode_access_token(token)
    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, email, role FROM users WHERE id = %s", (user_id,))
            user = cur.fetchone()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(status_code=exc.status_code, content=json_error(detail))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=json_error("Validation failed", errors=exc.errors()),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    if settings.debug:
        return JSONResponse(status_code=500, content=json_error("Internal server error", error=str(exc)))
    return JSONResponse(status_code=500, content=json_error("Internal server error"))


@app.on_event("startup")
def startup() -> None:
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(120) NOT NULL,
                    email VARCHAR(255) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(20) NOT NULL DEFAULT 'employee',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_requests (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    requester_id INT NOT NULL,
                    title VARCHAR(160) NOT NULL,
                    description TEXT NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    decision_comment VARCHAR(600) NULL,
                    reviewed_by INT NULL,
                    reviewed_at TIMESTAMP NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (requester_id) REFERENCES users(id),
                    FOREIGN KEY (reviewed_by) REFERENCES users(id)
                )
                """
            )


@app.get("/", response_model=ApiResponse)
def health() -> Dict[str, Any]:
    return json_success("BNR Approval System API is running", environment=settings.environment)


@app.get("/db-test", response_model=ApiResponse)
def db_test() -> Dict[str, Any]:
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            result = cur.fetchone()
    return json_success("Database connection successful", result=result)


@app.post("/register", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest) -> Dict[str, Any]:
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (payload.email,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="Email is already registered")

            cur.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)",
                (payload.name, payload.email, hash_password(payload.password)),
            )
            user_id = cur.lastrowid

    return json_success("User registered successfully", user={"id": user_id, "name": payload.name, "email": payload.email})


@app.post("/login", response_model=ApiResponse)
def login(payload: LoginRequest) -> Dict[str, Any]:
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, email, role, password_hash FROM users WHERE email = %s", (payload.email,))
            user = cur.fetchone()

    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token({"sub": str(user["id"]), "email": user["email"], "role": user["role"]})

    return json_success(
        "Login successful",
        token=token,
        user={"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]},
    )


@app.post("/requests", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
def create_request(payload: RequestCreate, current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO approval_requests (requester_id, title, description) VALUES (%s, %s, %s)",
                (current_user["id"], payload.title, payload.description),
            )
            request_id = cur.lastrowid

    return json_success("Request created", request={"id": request_id, "title": payload.title, "description": payload.description, "status": "pending"})


@app.get("/requests", response_model=ApiResponse)
def get_requests(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    with db_connection() as conn:
        with conn.cursor() as cur:
            if current_user["role"] == "admin":
                cur.execute(
                    """
                    SELECT ar.id, ar.title, ar.description, ar.status, ar.decision_comment, ar.created_at,
                           ar.reviewed_at, u.name AS requester_name, u.email AS requester_email
                    FROM approval_requests ar
                    JOIN users u ON u.id = ar.requester_id
                    ORDER BY ar.created_at DESC
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT id, title, description, status, decision_comment, created_at, reviewed_at
                    FROM approval_requests
                    WHERE requester_id = %s
                    ORDER BY created_at DESC
                    """,
                    (current_user["id"],),
                )
            rows = cur.fetchall()

    return json_success("Requests fetched", requests=rows)


@app.patch("/requests/{request_id}/decision", response_model=ApiResponse)
def decide_request(
    request_id: int,
    payload: DecisionRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admins can approve or reject requests")

    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, status FROM approval_requests WHERE id = %s", (request_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Request not found")
            if row["status"] != "pending":
                raise HTTPException(status_code=409, detail="Request has already been reviewed")

            cur.execute(
                """
                UPDATE approval_requests
                SET status = %s,
                    decision_comment = %s,
                    reviewed_by = %s,
                    reviewed_at = NOW()
                WHERE id = %s
                """,
                (payload.action, payload.comment, current_user["id"], request_id),
            )

    return json_success(f"Request {payload.action}d successfully")
