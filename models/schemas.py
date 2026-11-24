from pydantic import BaseModel

class TokenModel(BaseModel):
    token: str

class SkuMatchModel(BaseModel):
    sku: str

class SaveImageData(BaseModel):
    pb_id: str
    name: str
    image_base64: str# Pydantic 传输模型定义
from pydantic import BaseModel

class TokenModel(BaseModel):
    token: str

class SkuMatchModel(BaseModel):
    sku: str

class SaveImageData(BaseModel):
    pb_id: str
    name: str
    image_base64: str

class UserData(BaseModel):
    name: str