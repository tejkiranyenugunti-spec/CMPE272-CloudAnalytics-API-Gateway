from pydantic import BaseModel

SECRET_KEY = "e9e1f7e2ec67ea20f33924d972677f268f006d1e0b70160cb56c25ee836bc1f6"
MONGO_SVR = "mongodb+srv://alexhuang_db_user:9Yq56XrrSk4xeVHe@cluster0.pxkwsh5.mongodb.net/?appName=Cluster0"

ACCESS_TOKEN_EXPIRE_MINUTES = 30
ALGORITHM = "HS256"

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None