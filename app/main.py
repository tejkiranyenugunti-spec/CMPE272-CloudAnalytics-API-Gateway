from typing import Union
from fastapi import FastAPI

app = FastAPI(title="Cloud Analytics", version="1.0.0")

@app.get("/")
async def root():
    return {"message": "Welcome to FastAPI Authentication Demo"}


@app.get("/items/{item_id}")
async def read_item(item_id: int, q: Union[str, None] = None):
    return {"item_id": item_id, "q": q}