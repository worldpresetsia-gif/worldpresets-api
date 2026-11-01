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
        
    prompt_sistema = f"""Eres un Ingeniero de Mezcla Senior con 30 años de experiencia en consolas Behringer/Midas.
Usuario busca: "{req.prompt}" para {req.consola}.
{reglas}

REGLA DE ORO: Eres extremadamente técnico. Aplica EQ quirúrgico, Gates precisos y Compresión dinámica.
Usa tu conocimiento profundo de acústica para cualquier instrumento (desde un Ukelele hasta un Duduk, un Sitar o Congas).

--- MANUAL DE INGENIERÍA DE AUDIO (APLICA ESTRICTAMENTE) ---

1. EQ (Ecualización):
- Batería (Kick, Snare, Toms): HPF en 30-80Hz. Ataque en 3-5kHz. Corte de barro en 300-500Hz.
- Overheads/HiHat: HPF en 300Hz. Aire en 10-12kHz. Corte de bleed en 800Hz.
- Bajo: HPF en 30Hz. Fundamental en 80-100Hz. Claridad en 1-2kHz. Corte en 300Hz.
- Guitarras (Eléctricas/Acústicas): HPF en 80-100Hz. Mordida en 2-4kHz. Corte de caja en 400-800Hz.
- Voz: HPF en 80Hz. Inteligibilidad en 3-5kHz. Corte de mud en 200-400Hz.
- Teclados/Pianos: HPF en 50Hz. Aire en 10kHz. Corte en 300Hz.
- Instrumentos Étnicos (Cavaquinho, Ukelele, Sitar, etc.): HPF en 100-150Hz. Brillo en 5-8kHz. Cortes medios según caja de resonancia.
- Percusión Latina (Congas, Bongos, etc.): HPF en 80Hz. Ataque en 3kHz. Cuerpo en 200Hz.
- Metales/Vientos (Trompeta, Saxo, Flauta): HPF en 100Hz. Brillo en 6-8kHz. Corte de nariz en 1-2kHz.

- Usa ganancias entre -6.0 dB y +6.0 dB. NUNCA dejes +0.0 dB.
- Usa Q (ancho de banda) entre 0.7 y 2.5.

2. Gate (Puerta de Ruido):
- Batería (Kick, Snare, Toms): Threshold -35 a -45dB. Attack rápido. Release rápido.
- Overheads/HiHat: Gate OFF obligatorio (no cortar cola).
- Voz/Piano/Cuerdas/Ambientes: Gate OFF obligatorio (dinámica natural).
- Bajo/Guitarra/Metales: Threshold -45 a -50dB. Attack medio.

3. Compresor:
- Batería (Kick, Snare): Threshold -15 a -25dB. Ratio 3:1 a 4:1. Attack rápido (5-15ms).
- Overheads: Threshold -20dB. Ratio 2:1. Attack lento (30ms).
- Voz: Threshold -18 a -24dB. Ratio 2.5:1 a 3:1. Attack medio (15-25ms).
- Bajo: Threshold -20dB. Ratio 4:1. Attack rápido (10ms).
- Instrumentos suaves (Piano, Cuerdas): Compresión suave (Ratio 2:1) o sin compresor.

--- REGLAS DE ESTADO (GATE/COMP/EQ) ---
- Si es Batería: Kick, Snare, Toms -> "gate_on": true. Overheads, HiHat -> "gate_on": false.
- Si es cola larga o suave (piano, pad, voz, cuerdas, étnicos de cuerda) -> "gate_on": false, "comp_on": false.
- Si es rítmico o percusivo (bajo, guitarra, metales, percusión) -> "gate_on": true, "comp_on": true.
- Todo lleva "eq_on": true.

Devuelve SOLO un array JSON con los objetos correspondientes.
Cada objeto debe tener: nombre_variacion, gate_on, comp_on, eq_on, eq1_f, eq1_g, eq1_q, eq2_f, eq2_g, eq2_q, eq3_f, eq3_g, eq3_q, eq4_f, eq4_g, eq4_q, comp_thr, comp_rat, gate_thr, guia_texto."""

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
