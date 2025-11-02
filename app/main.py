from typing import Union, Annotated
from datetime import timedelta

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

import auth
import constants
from constants import Token, TokenData



app = FastAPI(title="Cloud Analytics", version="1.0.0")

@app.get("/")
async def root():
    return {"message": "Welcome to FastAPI Authentication Demo"}

@app.get("/server")
async def ping_server():
    try:
        auth.client.admin.command('ping')
        print("Pinged your deployment. You successfully connected to MongoDB!")
    except Exception as e:
        print(e)

@app.post("/user/create")
async def create_user(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    try:
        auth.client.get_database("CloudAnalytics").get_collection("users").insert_one({
            "username": form_data.username,
            "password": auth.hash_password(form_data.password)
        })
        return {"message": "User created successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create user due to the following error: " + str(e)
        )

@app.post("/token")
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    if not auth.authenticate_user(form_data.username, form_data.password):
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


@app.get("/items/{item_id}")
async def read_item(item_id: int, q: Union[str, None] = None):
    return {"item_id": item_id, "q": q}