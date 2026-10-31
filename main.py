import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google import genai
from google.genai import types

app = FastAPI(title="World Presets API")

# Buscamos la clave que guardamos en Render
API_KEY = os.getenv("GEMINI_API_KEY")
client = None
if API_KEY:
    client = genai.Client(api_key=API_KEY)

@app.get("/")
def read_root():
    return {"status": "Portero listo y conectado a la IA"}

class PresetRequest(BaseModel):
    prompt: str
    consola: str
    licencia: str = None

@app.post("/generar")
def generar_preset(req: PresetRequest):
    if not client:
        raise HTTPException(status_code=500, detail="API Key no configurada en el servidor")
    
    # Por ahora solo probamos que reciba los datos
    return {"status": "ok", "mensaje": "Recibido", "prompt": req.prompt, "consola": req.consola}
