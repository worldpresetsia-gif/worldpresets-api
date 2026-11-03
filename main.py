import os
import re
import json
import random
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

app = FastAPI(title="World Presets API")

# --- Configuración de Groq ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")

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

def registrar_usuario_en_supabase(email):
    if email == "test@test.com":
        return
    if not SUPABASE_URL or not SUPABASE_KEY:
        return

    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=representation"}
    url_get = f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}"
    req_get = urllib.request.Request(url_get, headers=headers)
    try:
        with urllib.request.urlopen(req_get) as response:
            data = json.loads(response.read().decode('utf-8'))
        if len(data) > 0:
            return
    except:
        pass

    url_post = f"{SUPABASE_URL}/rest/v1/usuarios"
    body_post = json.dumps({"email": email, "usadas": 0, "limite": 10, "tipo_licencia": "DEMO"}).encode('utf-8')
    req_post = urllib.request.Request(url_post, data=body_post, headers=headers, method='POST')
    try:
        urllib.request.urlopen(req_post)
    except Exception as e:
        pass

def verificar_limite(email, hwid, consola_solicitada):
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
            
        return True, "Verificado"
    else:
        return True, "Usuario nuevo verificado"

def cobrar_generacion(email, hwid):
    if email == "test@test.com":
        return
    
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    url_get = f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}"
    req_get = urllib.request.Request(url_get, headers=headers)
    
    with urllib.request.urlopen(req_get) as response:
        data = json.loads(response.read().decode('utf-8'))

    if len(data) > 0:
        usuario = data[0]
        nuevas_usadas = usuario["usadas"] + 1
        url_patch = f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}"
        body_patch = json.dumps({"usadas": nuevas_usadas}).encode('utf-8')
        req_patch = urllib.request.Request(url_patch, data=body_patch, headers=headers, method='PATCH')
        urllib.request.urlopen(req_patch)
    else:
        url_post = f"{SUPABASE_URL}/rest/v1/usuarios"
        body_post = json.dumps({"email": email, "usadas": 1, "limite": 10, "hwid": hwid, "tipo_licencia": "DEMO"}).encode('utf-8')
        req_post = urllib.request.Request(url_post, data=body_post, headers=headers, method='POST')
        urllib.request.urlopen(req_post)

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
        registrar_usuario_en_supabase(req.email)
        return {"status": "ok", "mensaje": "Verificado correctamente"}
    else:
        raise HTTPException(status_code=400, detail="Código incorrecto o expirado")

@app.post("/generar")
def generar_preset(req: PresetRequest):
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="Groq API Key no configurada")
    if not req.email:
        raise HTTPException(status_code=403, detail="Se requiere el email")
        
    valido, msj = verificar_limite(req.email, req.hwid, req.consola)
    if not valido:
        raise HTTPException(status_code=403, detail=msj)

    # Lógica de caché (sin cambios)
    prompt_limpio = req.prompt.lower().strip()
    headers_supabase = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    url_cache = f"{SUPABASE_URL}/rest/v1/cache_presets?consola=eq.{req.consola}&prompt_buscado=eq.{prompt_limpio}"
    req_cache = urllib.request.Request(url_cache, headers=headers_supabase)
    
    try:
        with urllib.request.urlopen(req_cache) as response:
            cache_data = json.loads(response.read().decode('utf-8'))
            if len(cache_data) > 0:
                cobrar_generacion(req.email, req.hwid)
                return {"status": "ok", "modelo_usado": "cache", "mensaje_limite": "Generación desde caché", "datos": json.dumps(cache_data[0]["datos_json"])}
    except Exception as e:
        pass

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

    # --- Llamada a Groq (OpenAI-compatible) ---
    url_groq = "https://api.groq.com/openai/v1/chat/completions"
    headers_groq = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt_sistema}],
        "response_format": {"type": "json_object"}
    }

    try:
        req_ai = urllib.request.Request(url_groq, data=json.dumps(payload).encode('utf-8'), headers=headers_groq, method='POST')
        with urllib.request.urlopen(req_ai, timeout=60) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            json_respuesta = res_data["choices"][0]["message"]["content"]
            
            try:
                url_post_cache = f"{SUPABASE_URL}/rest/v1/cache_presets"
                body_post_cache = json.dumps({
                    "consola": req.consola, 
                    "prompt_buscado": prompt_limpio, 
                    "datos_json": json.loads(json_respuesta)
                }).encode('utf-8')
                req_post_cache = urllib.request.Request(url_post_cache, data=body_post_cache, headers=headers_supabase, method='POST')
                urllib.request.urlopen(req_post_cache)
            except Exception as e:
                pass

            cobrar_generacion(req.email, req.hwid) 
            
            return {"status": "ok", "modelo_usado": "groq-llama-3.3", "mensaje_limite": "Generación exitosa", "datos": json_respuesta}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error de Groq. Detalle: {str(e)}")

# El webhook de Gumroad se mantiene exactamente igual
@app.post("/gumroad-webhook")
async def gumroad_webhook(request: Request):
    try:
        body = await request.body()
        body_str = body.decode('utf-8')
        parsed = urllib.parse.parse_qs(body_str)
        datos = {k: v[0] for k, v in parsed.items()}
        
        if datos.get("refunded") == "true":
            return {"status": "ok", "mensaje": "Reembolso ignorado"}
        
        email = datos.get("email")
        product_id = datos.get("short_product_id") or datos.get("product_id")
        
        if not email or not product_id:
            return {"status": "error", "mensaje": "Faltan datos"}

        ID_DEMO = "eqtpr"
        PACKS_LICENCIA = {
            "kwcedd": 100, "xsocpy": 200, "sodyxd": 500, "xzkedi": 1000, "wzzlgq": 5000
        }
        RECARGAS = {"duahk": 100}

        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=representation"}
        url_get = f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}"
        req_get = urllib.request.Request(url_get, headers=headers)
        
        with urllib.request.urlopen(req_get) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        if len(data) > 0:
            usuario = data[0]
            licencia_actual = usuario.get("tipo_licencia", "DEMO")
            limite_actual = usuario["limite"]
            
            if product_id in PACKS_LICENCIA:
                gens_a_sumar = PACKS_LICENCIA[product_id]
                nuevo_limite = limite_actual + gens_a_sumar
                url_patch = f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}"
                body_patch = json.dumps({"limite": nuevo_limite, "tipo_licencia": "FULL"}).encode('utf-8')
                req_patch = urllib.request.Request(url_patch, data=body_patch, headers=headers, method='PATCH')
                urllib.request.urlopen(req_patch)
                return {"status": "ok", "mensaje": f"Pack de {gens_a_sumar} gen activado"}

            elif product_id in RECARGAS:
                if licencia_actual == "DEMO":
                    return {"status": "error", "mensaje": "Compraste una recarga, pero no tenés licencia. Comprá un Pack Principal primero."}
                
                gens_a_sumar = RECARGAS[product_id]
                nuevo_limite = limite_actual + gens_a_sumar
                url_patch = f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}"
                body_patch = json.dumps({"limite": nuevo_limite}).encode('utf-8')
                req_patch = urllib.request.Request(url_patch, data=body_patch, headers=headers, method='PATCH')
                urllib.request.urlopen(req_patch)
                return {"status": "ok", "mensaje": f"Recarga de {gens_a_sumar} activada"}
            
            elif product_id == ID_DEMO:
                return {"status": "ok", "mensaje": "Usuario DEMO ya registrado"}
            
            else:
                return {"status": "ok", "mensaje": "Producto no reconocido"}
        else:
            if product_id in PACKS_LICENCIA:
                gens = PACKS_LICENCIA[product_id]
                url_post = f"{SUPABASE_URL}/rest/v1/usuarios"
                body_post = json.dumps({"email": email, "usadas": 0, "limite": gens, "tipo_licencia": "FULL"}).encode('utf-8')
                req_post = urllib.request.Request(url_post, data=body_post, headers=headers, method='POST')
                urllib.request.urlopen(req_post)
                return {"status": "ok", "mensaje": f"Nuevo usuario FULL con {gens} creado"}
            
            elif product_id == ID_DEMO:
                url_post = f"{SUPABASE_URL}/rest/v1/usuarios"
                body_post = json.dumps({"email": email, "usadas": 0, "limite": 10, "tipo_licencia": "DEMO"}).encode('utf-8')
                req_post = urllib.request.Request(url_post, data=body_post, headers=headers, method='POST')
                urllib.request.urlopen(req_post)
                return {"status": "ok", "mensaje": "Nuevo usuario DEMO creado"}
                
            else:
                return {"status": "error", "mensaje": "Usuario nuevo intentó comprar recarga sin licencia"}

    except Exception as e:
        return {"status": "error", "mensaje": str(e)}
