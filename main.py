import os
import re
import json
import random
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google import genai
from google.genai import types

app = FastAPI(title="World Presets API")

API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")

client = None
if API_KEY:
    client = genai.Client(api_key=API_KEY)

codigos_pendientes = {}

class EmailRequest(BaseModel):
    email: str

class CodigoRequest(BaseModel):
    email: str
    codigo: str

class PresetRequest(BaseModel):
    prompt: str
    consola: str
    email: str = None

def enviar_email_brevo(destinatario, codigo):
    if not BREVO_API_KEY:
        return False
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {"accept": "application/json", "api-key": BREVO_API_KEY, "content-type": "application/json"}
    data = {
        "sender": {"name": "World Presets", "email": "worldpresets.ia@gmail.com"},
        "to": [{"email": destinatario}],
        "subject": "Tu código de verificación - World Presets",
        "htmlContent": f"<html><body><h2>Tu código es:</h2><h1>{codigo}</h1></body></html>"
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as response:
            return True
    except:
        return False

def verificar_limite_y_actualizar(email):
    if email == "test@test.com":
        return True, "Usuario de prueba aceptado (Ilimitado)"
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False, "Faltan configurar las variables de Supabase"

    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=representation"}
    url_get = f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}"
    req_get = urllib.request.Request(url_get, headers=headers)
    
    try:
        with urllib.request.urlopen(req_get) as response:
            data = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        return False, f"Error conectando a Supabase: {e}"

    if len(data) > 0:
        usuario = data[0]
        if usuario["usadas"] >= usuario["limite"]:
            return False, f"Límite alcanzado ({usuario['limite']} generaciones)."
        nuevas_usadas = usuario["usadas"] + 1
        url_patch = f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}"
        body_patch = json.dumps({"usadas": nuevas_usadas}).encode('utf-8')
        req_patch = urllib.request.Request(url_patch, data=body_patch, headers=headers, method='PATCH')
        urllib.request.urlopen(req_patch)
        return True, f"Generación {nuevas_usadas} de {usuario['limite']} permitida"
    else:
        url_post = f"{SUPABASE_URL}/rest/v1/usuarios"
        body_post = json.dumps({"email": email, "usadas": 1, "limite": 10}).encode('utf-8')
        req_post = urllib.request.Request(url_post, data=body_post, headers=headers, method='POST')
        urllib.request.urlopen(req_post)
        return True, "Generación 1 de 10 permitida (Nuevo usuario registrado)"

def obtener_modelos_candidatos():
    try:
        candidatos = []
        for m in client.models.list():
            if "generateContent" not in m.supported_actions: continue
            nombre = m.name.split("/")[-1]
            if "flash" not in nombre.lower(): continue
            match = re.search(r'(\d+\.\d+)', nombre)
            version = float(match.group(1)) if match else 0.0
            es_estable = 1 if "preview" not in nombre.lower() else 0
            candidatos.append((es_estable, version, nombre))
        candidatos.sort(key=lambda x: (x[0], x[1]), reverse=True)
        lista_final = [c[2] for c in candidatos]
        lista_final.append("gemini-flash-latest") 
        return lista_final
    except:
        return ["gemini-2.5-flash", "gemini-flash-latest"]

def es_solicitud_de_bateria(texto):
    return any(p in texto.lower() for p in ["bateria","batería","drumkit","drums","kit"])

@app.get("/")
def read_root():
    return {"status": "Portero listo"}

@app.post("/enviar-codigo")
def enviar_codigo(req: EmailRequest):
    codigo = str(random.randint(100000, 999999))
    codigos_pendientes[req.email] = codigo
    if enviar_email_brevo(req.email, codigo):
        return {"status": "ok", "mensaje": "Código enviado"}
    else:
        raise HTTPException(status_code=500, detail="Error al enviar correo")

@app.post("/verificar-codigo")
def verificar_codigo(req: CodigoRequest):
    if req.email in codigos_pendientes and codigos_pendientes[req.email] == req.codigo:
        del codigos_pendientes[req.email]
        return {"status": "ok", "mensaje": "Verificado correctamente"}
    else:
        raise HTTPException(status_code=400, detail="Código incorrecto o expirado")

@app.post("/generar")
def generar_preset(req: PresetRequest):
    if not client:
        raise HTTPException(status_code=500, detail="API Key no configurada")
    if not req.email:
        raise HTTPException(status_code=403, detail="Se requiere el email")
        
    valido, msj = verificar_limite_y_actualizar(req.email)
    if not valido:
        raise HTTPException(status_code=403, detail=msj)
    
    es_bateria = es_solicitud_de_bateria(req.prompt)
    if es_bateria:
        reglas = "Genera 8 presets: Kick, Snare, HiHat, Tom1, Tom2, Tom3, OH-L, OH-R."
    else:
        reglas = "Genera 3 variaciones."
        
    prompt_sistema = f"""Eres ingeniero de sonido experto en consolas Behringer/Midas.
Usuario busca: "{req.prompt}" para {req.consola}.
{reglas}
IMPORTANTE: Debes aplicar ganancias de EQ notorias. No uses +0.0 dB. 
Usa valores entre -6.0 dB y +6.0 dB para las bandas (eq1_g, eq2_g, eq3_g, eq4_g). 
Si recortas, usa al menos -3.0 dB. Si realzas, usa al menos +2.0 dB. 
Haz que el sonido cambie drásticamente para bien.
Además, decide si el instrumento necesita Gate, Compresor y EQ.
Si es un instrumento de cola larga o suave (piano, pad, voz), pon gate_on en false. Si es rítmico (batería, bajo, guitarra), pon true.
Devuelve SOLO un array JSON con los objetos correspondientes.
Cada objeto debe tener: nombre_variacion, gate_on (true/false), comp_on (true/false), eq_on (true/false), eq1_f, eq1_g, eq1_q, eq2_f, eq2_g, eq2_q, eq3_f, eq3_g, eq3_q, eq4_f, eq4_g, eq4_q, comp_thr, comp_rat, gate_thr, guia_texto."""

    modelos = obtener_modelos_candidatos()
    ultimo_error = ""

    for modelo in modelos:
        try:
            response = client.models.generate_content(
                model=modelo,
                contents=prompt_sistema,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            return {"status": "ok", "modelo_usado": modelo, "mensaje_limite": msj, "datos": response.text}
        except Exception as e:
            ultimo_error = str(e)
            continue 
            
    raise HTTPException(status_code=500, detail=f"Error: {ultimo_error}")
