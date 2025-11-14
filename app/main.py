from datetime import timedelta
from typing import Annotated

from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from slowapi.errors import RateLimitExceeded
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from prometheus_fastapi_instrumentator import Instrumentator

# --- Import your internal modules ---
from app import auth, constants
from app.constants import Token
from app.aws import router as aws_router
from app.azure import router as azure_router
from app.compare import router as compare_router

# ---- App setup ----
limiter = Limiter(key_func=get_remote_address, default_limits=["10/minute"])
app = FastAPI(title="Cloud Analytics API Gateway", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---- Prometheus metrics setup ----
Instrumentator().instrument(app).expose(app)

# ---- Mount Routers ----
# Public endpoints:
app.include_router(aws_router)
app.include_router(azure_router)

# Protected endpoints: all /compare/* require Bearer token
app.include_router(compare_router, dependencies=[Depends(auth.require_auth)])

# ---- Root ----
@app.get("/")
async def root():
    return {"message": "Welcome to Cloud Analytics API Gateway"}

# ---- Authentication Endpoints ----
@app.post("/user/create")
async def create_user(request: Request, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    """
    Create a new user in MongoDB.
    """
    try:
        username, password = auth.sanitize_login_input(form_data.username, form_data.password)
        db = auth.client.get_database("CloudAnalytics")
        users = db.get_collection("users")

        if users.find_one({"username": username}):
            raise HTTPException(status_code=400, detail="Username already exists")

        users.insert_one({
            "username": username,
            "password": auth.hash_password(password)
        })
        return {"message": "User created successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to create user: {str(e)}"
        )

@app.post("/token")
async def login_for_access_token(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """
    Authenticate user and return JWT access token.
    """
    try:
        username, password = auth.sanitize_login_input(form_data.username, form_data.password)
        if not auth.authenticate_user(username, password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        access_token_expires = timedelta(minutes=constants.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = auth.generate_jwt_token(
            data={"user": form_data.username}, expires_delta=access_token_expires
        )
        return Token(access_token=access_token, token_type="bearer")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to login: {str(e)}"
        )

@app.get("/token")
async def validate_login(request: Request, token: str = Depends(auth.oauth2_scheme)):
    """
    Validate a JWT token.
    """
    try:
        if auth.validate_jwt(token):
            return {"message": "Token is valid"}
    except HTTPException as e:
        # pass through structured 401s from validate_jwt
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}"
        )

# ---- MongoDB health check ----
@app.get("/server")
async def ping_server():
    """
    Ping MongoDB connection to verify connectivity.
    """
    try:
        auth.client.admin.command("ping")
        return {"status": "OK", "message": "MongoDB connection successful"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
