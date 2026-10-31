import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google import genai
from google.genai import types

app = FastAPI(title="World Presets API")

API_KEY = os.getenv("GEMINI_API_KEY")
client = None
if API_KEY:
    client = genai.Client(api_key=API_KEY)

class PresetRequest(BaseModel):
    prompt: str
    consola: str
    licencia: str = None

@app.get("/")
def read_root():
    return {"status": "Portero listo y conectado a la IA"}

@app.post("/generar")
def generar_preset(req: PresetRequest):
    if not client:
        raise HTTPException(status_code=500, detail="API Key no configurada")
        
    prompt_sistema = f"""Eres ingeniero de sonido experto en consolas Behringer/Midas.
Usuario busca: "{req.prompt}" para {req.consola}.
Devuelve SOLO un array JSON con 3 objetos.
Cada objeto debe tener: nombre_variacion, eq1_f, eq1_g, eq1_q, eq2_f, eq2_g, eq2_q, eq3_f, eq3_g, eq3_q, eq4_f, eq4_g, eq4_q, comp_thr, comp_rat, gate_thr, guia_texto."""

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt_sistema,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        return {"status": "ok", "datos": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
