import os
import re
import json
import random
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException, Request
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
    hwid: str = None

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

def verificar_limite_y_actualizar(email, hwid, consola_solicitada):
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
        
        hwid_guardado = usuario.get("hwid")
        if hwid_guardado and hwid_guardado != hwid:
            return False, "Este email ya está registrado en otra computadora. Contactá a soporte."
        
        if not hwid_guardado and hwid:
            url_patch = f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}"
            body_patch = json.dumps({"hwid": hwid}).encode('utf-8')
            req_patch = urllib.request.Request(url_patch, data=body_patch, headers=headers, method='PATCH')
            try: urllib.request.urlopen(req_patch)
            except: pass

        licencia = usuario.get("tipo_licencia", "DEMO")
        if licencia == "XR18" and consola_solicitada not in ["XR18 - MR18", "X32 - M32", "X32", "XR18"]:
            return False, "Tu licencia es solo para XR18. Actualizá al Pack Estrella para usar todas las consolas."

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
        body_post = json.dumps({"email": email, "usadas": 1, "limite": 10, "hwid": hwid, "tipo_licencia": "DEMO"}).encode('utf-8')
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
        
    valido, msj = verificar_limite_y_actualizar(req.email, req.hwid, req.consola)
    if not valido:
        raise HTTPException(status_code=403, detail=msj)
    
    es_bateria = es_solicitud_de_bateria(req.prompt)
    if es_bateria:
        reglas = "Genera 8 presets: Kick, Snare, HiHat, Tom1, Tom2, Tom3, OH-L, OH-R."
    else:
        reglas = "Genera 3 variaciones."
        
    prompt_sistema = f"""Eres un Ingeniero de Mezcla Senior. Usuario busca: "{req.prompt}" para {req.consola}.
{reglas}

REGLA DE ORO: Eres extremadamente técnico. NO devuelvas ganancias de EQ en 0.0. Aplica EQ quirúrgico, Gates precisos y Compresión dinámica.

--- MANUAL DE INGENIERÍA (APLICA ESTRICTAMENTE) ---

1. EQ (Ecualización):
- Batería (Kick, Snare, Toms): HPF 30-80Hz. Ataque en 3-5kHz (eq3_f). Corte de barro en 300-500Hz (eq2_f).
- Overheads/HiHat: HPF 300Hz. Aire en 10-12kHz (eq4_f). Corte de bleed en 800Hz (eq3_f).
- Bajo: HPF 30Hz. Fundamental 80-100Hz (eq1_f). Claridad 1-2kHz (eq3_f). Corte 300Hz (eq2_f).
- Guitarras (Eléctricas/Acústicas): HPF 80-100Hz. Mordida 2-4kHz (eq3_f). Corte de caja 400-800Hz (eq2_f).
- Voz: HPF 80Hz. Inteligibilidad 3-5kHz (eq3_f). Corte mud 200-400Hz (eq2_f).
- Teclados/Pianos: HPF 50Hz. Aire 10kHz (eq4_f). Corte en 300Hz (eq2_f).
- Étnicos (Ukelele, Sitar, etc.): HPF 100-150Hz. Brillo 5-8kHz (eq4_f). Cortes medios según caja.
- Percusión Latina (Congas, etc.): HPF 80Hz. Ataque 3kHz (eq3_f). Cuerpo 200Hz (eq1_f).
- Metales/Vientos: HPF 100Hz. Brillo 6-8kHz (eq4_f). Corte nariz 1-2kHz (eq3_f).

GANANCIAS DE EQ OBLIGATORIAS:
- eq1_g: SIEMPRE entre -4.0 dB y +4.0 dB (NUNCA 0.0).
- eq2_g: SIEMPRE entre -3.0 dB y -6.0 dB (Corte obligatorio).
- eq3_g: SIEMPRE entre +2.0 dB y +5.0 dB (Realce de ataque).
- eq4_g: SIEMPRE entre +2.0 dB y +4.0 dB (Aire/Brillo).
- Usa valores de Q entre 0.8 y 2.5.

2. Gate:
- Batería (Kick, Snare, Toms): gate_on TRUE. Threshold -35 a -45dB. 
- Overheads/HiHat: gate_on FALSE.
- Voz/Piano/Cuerdas/Ambientes: gate_on FALSE.
- Bajo/Guitarra/Metales: gate_on TRUE. Threshold -45 a -50dB.

3. Compresor:
- Batería (Kick, Snare): comp_on TRUE. Threshold -15 a -25dB. Ratio 3:1 a 4:1.
- Overheads: comp_on TRUE. Threshold -20dB. Ratio 2:1.
- Voz: comp_on TRUE. Threshold -18 a -24dB. Ratio 2.5:1 a 3:1.
- Bajo: comp_on TRUE. Threshold -20dB. Ratio 4:1.
- Suaves (Piano/Cuerdas): comp_on FALSE o Ratio 2:1 muy suave.

--- ESTADOS ---
- Si es Batería: Kick/Snare/Toms gate_on=true. OHs/HiHat gate_on=false.
- Si es cola larga (piano, pad, voz, cuerdas): gate_on=false, comp_on=false.
- Si es rítmico (bajo, guitarra, percusión): gate_on=true, comp_on=true.
- eq_on: SIEMPRE true.

Devuelve SOLO un array JSON.
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

# --- INICIO WEBHOOK GUMROAD CON LICENCIAS ---
@app.post("/gumroad-webhook")
async def gumroad_webhook(request: Request):
    try:
        form_data = await request.form()
        datos = dict(form_data)
        
        if datos.get("refunded") == "true":
            return {"status": "ok", "mensaje": "Reembolso ignorado"}
        
        email = datos.get("email")
        product_id = datos.get("product_id")
        
        if not email or not product_id:
            return {"status": "error", "mensaje": "Faltan datos"}

        ID_PACK_XR18 = "ID_DEL_PACK_XR18_AQUI"
        ID_PACK_ESTRELLA = "ID_DEL_PACK_ESTRELLA_AQUI"
        ID_RECARGA_100 = "ID_DE_RECARGA_100_AQUI"
        ID_RECARGA_500 = "ID_DE_RECARGA_500_AQUI"

        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=representation"}
        url_get = f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}"
        req_get = urllib.request.Request(url_get, headers=headers)
        
        with urllib.request.urlopen(req_get) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        if len(data) > 0:
            usuario = data[0]
            licencia_actual = usuario.get("tipo_licencia", "DEMO")
            limite_actual = usuario["limite"]
            
            if product_id == ID_PACK_XR18:
                nuevo_limite = limite_actual + 100
                url_patch = f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}"
                body_patch = json.dumps({"limite": nuevo_limite, "tipo_licencia": "XR18"}).encode('utf-8')
                req_patch = urllib.request.Request(url_patch, data=body_patch, headers=headers, method='PATCH')
                urllib.request.urlopen(req_patch)
                return {"status": "ok", "mensaje": "Pack XR18 activado"}
                
            elif product_id == ID_PACK_ESTRELLA:
                nuevo_limite = limite_actual + 1000
                url_patch = f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}"
                body_patch = json.dumps({"limite": nuevo_limite, "tipo_licencia": "FULL"}).encode('utf-8')
                req_patch = urllib.request.Request(url_patch, data=body_patch, headers=headers, method='PATCH')
                urllib.request.urlopen(req_patch)
                return {"status": "ok", "mensaje": "Pack Estrella activado"}

            elif product_id in [ID_RECARGA_100, ID_RECARGA_500]:
                if licencia_actual == "DEMO":
                    return {"status": "error", "mensaje": "Compraste una recarga, pero no tenés licencia. Comprá un Pack Principal primero."}
                
                gens_a_sumar = 100 if product_id == ID_RECARGA_100 else 500
                nuevo_limite = limite_actual + gens_a_sumar
                url_patch = f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}"
                body_patch = json.dumps({"limite": nuevo_limite}).encode('utf-8')
                req_patch = urllib.request.Request(url_patch, data=body_patch, headers=headers, method='PATCH')
                urllib.request.urlopen(req_patch)
                return {"status": "ok", "mensaje": f"Recarga de {gens_a_sumar} activada"}
            
            else:
                return {"status": "ok", "mensaje": "Producto no reconocido"}
        else:
            if product_id == ID_PACK_XR18:
                url_post = f"{SUPABASE_URL}/rest/v1/usuarios"
                body_post = json.dumps({"email": email, "usadas": 0, "limite": 100, "tipo_licencia": "XR18"}).encode('utf-8')
                req_post = urllib.request.Request(url_post, data=body_post, headers=headers, method='POST')
                urllib.request.urlopen(req_post)
                return {"status": "ok", "mensaje": "Nuevo usuario XR18 creado"}
            elif product_id == ID_PACK_ESTRELLA:
                url_post = f"{SUPABASE_URL}/rest/v1/usuarios"
                body_post = json.dumps({"email": email, "usadas": 0, "limite": 1000, "tipo_licencia": "FULL"}).encode('utf-8')
                req_post = urllib.request.Request(url_post, data=body_post, headers=headers, method='POST')
                urllib.request.urlopen(req_post)
                return {"status": "ok", "mensaje": "Nuevo usuario FULL creado"}
            else:
                return {"status": "error", "mensaje": "Usuario nuevo intentó comprar recarga sin licencia"}

    except Exception as e:
        return {"status": "error", "mensaje": str(e)}
# --- FIN WEBHOOK GUMROAD ---
