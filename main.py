import os
import re
import json
import urllib.request
import urllib.parse
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

def verificar_licencia(license_key):
    """Verifica la licencia con la API de Gumroad."""
    if license_key == "test":
        return True, "Licencia de prueba aceptada"
    
    product_id = os.getenv("GUMROAD_PRODUCT_ID")
    if not product_id:
        return True, "Bypass: Falta configurar GUMROAD_PRODUCT_ID"
        
    url = "https://api.gumroad.com/v2/licenses/verify"
    data = urllib.parse.urlencode({
        "product_id": product_id,
        "license_key": license_key
    }).encode('utf-8')
    
    req = urllib.request.Request(url, data=data, method='POST')
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            if res_data.get("success"):
                return True, "Licencia válida"
            else:
                return False, "Licencia inválida o reembolsada"
    except Exception as e:
        return False, f"Error al verificar licencia: {e}"

def obtener_modelos_candidatos():
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
        
        candidatos.sort(key=lambda x: (x[0], x[1]), reverse=True)
        lista_final = [c[2] for c in candidatos]
        lista_final.append("gemini-flash-latest") 
        return lista_final
    except Exception:
        return ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-flash-latest"]

def es_solicitud_de_bateria(texto):
    return any(p in texto.lower() for p in ["bateria","batería","drumkit","drums","kit"])

@app.get("/")
def read_root():
    return {"status": "Portero listo y conectado a la IA"}

@app.post("/generar")
def generar_preset(req: PresetRequest):
    if not client:
        raise HTTPException(status_code=500, detail="API Key no configurada")
    
    # 1. Verificamos la licencia
    if not req.licencia:
        raise HTTPException(status_code=403, detail="Se requiere una licencia para generar presets")
        
    licencia_valida, msj = verificar_licencia(req.licencia)
    if not licencia_valida:
        raise HTTPException(status_code=403, detail=msj)
    
    # 2. Preparamos el prompt
    es_bateria = es_solicitud_de_bateria(req.prompt)
    if es_bateria:
        reglas = "Genera 8 presets: Kick, Snare, HiHat, Tom1, Tom2, Tom3, OH-L, OH-R."
    else:
        reglas = "Genera 3 variaciones."
        
    prompt_sistema = f"""Eres ingeniero de sonido experto en consolas Behringer/Midas.
Usuario busca: "{req.prompt}" para {req.consola}.
{reglas}
Devuelve SOLO un array JSON con los objetos correspondientes.
Cada objeto debe tener: nombre_variacion, eq1_f, eq1_g, eq1_q, eq2_f, eq2_g, eq2_q, eq3_f, eq3_g, eq3_q, eq4_f, eq4_g, eq4_q, comp_thr, comp_rat, gate_thr, guia_texto."""

    # 3. Generamos con IA (con reintentos)
    modelos = obtener_modelos_candidatos()
    ultimo_error = ""

    for modelo in modelos:
        try:
            response = client.models.generate_content(
                model=modelo,
                contents=prompt_sistema,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            return {"status": "ok", "modelo_usado": modelo, "datos": response.text}
        except Exception as e:
            ultimo_error = str(e)
            continue 
            
    raise HTTPException(status_code=500, detail=f"Todos los modelos fallaron. Último error: {ultimo_error}")
