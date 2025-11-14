from typing import Union, Annotated
from datetime import timedelta

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from slowapi.errors import RateLimitExceeded
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

import auth
import constants
from constants import Token, TokenData


limiter = Limiter(key_func=get_remote_address, default_limits=["10/minute"])
app = FastAPI(title="Cloud Analytics", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.get("/")
async def root():
    return {"message": "Welcome to FastAPI Authentication Demo"}

@app.get("/token")
async def validate_login(request: Request, token: str = Depends(auth.oauth2_scheme)):
    try:
        if auth.validate_jwt(token):
            return {"message": "Token is valid"}
    except Exception as e:
        raise Exception("Unable to connect to the server due to the following error: " + str(e))

@app.post("/user/create")
async def create_user(request: Request, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    try:
        username, password = auth.sanitize_login_input(form_data.username, form_data.password)
        auth.client.get_database("CloudAnalytics").get_collection("users").insert_one({
            "username": username,
            "password": auth.hash_password(password)
        })
        return {"message": "User created successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create user due to the following error: " + str(e)
        )

@app.post("/token")
async def login_for_access_token(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
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
        raise Exception("Unable to login due to the following error: " + str(e))