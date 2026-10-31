import os
import re
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

def obtener_mejor_modelo():
    try:
        candidatos = []
        for m in client.models.list():
            if "generateContent" not in m.supported_actions:
                continue
            nombre = m.name.split("/")[-1]
            if "flash" not in nombre.lower():
                continue
            match = re.search(r'(\d+\.\d+)', nombre)
            version = float(match.group(1)) if match else 0.0
            es_estable = 1 if "preview" not in nombre.lower() else 0
            candidatos.append((es_estable, version, nombre))
        
        if not candidatos:
            return "gemini-flash-latest"
        
        candidatos.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return candidatos[0][2]
    except Exception:
        return "gemini-flash-latest"

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
        modelo_elegido = obtener_mejor_modelo()
        response = client.models.generate_content(
            model=modelo_elegido,
            contents=prompt_sistema,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        return {"status": "ok", "modelo_usado": modelo_elegido, "datos": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
