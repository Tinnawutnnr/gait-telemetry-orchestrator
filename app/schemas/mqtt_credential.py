from pydantic import BaseModel

class MqttCredential(BaseModel):
    broker_url: str
    username: str
    password: str