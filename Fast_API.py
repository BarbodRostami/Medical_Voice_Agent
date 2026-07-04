from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Input(BaseModel):
    x : float

def model_predict(x):
    return x * 2

@app.post("/predict")
def predict(data: Input):
    result = model_predict(data.x)
    return {"prediction": result}    
    