import os
import re
import json
import random
import urllib.request
import urllib.parse
import time
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

app = FastAPI(title="World Presets API")

# --- Configuración de las APIs ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
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

def construir_prompt(req):
    es_bateria = es_solicitud_de_bateria(req.prompt)
    reglas = "Genera 8 presets: Kick, Snare, HiHat, Tom1, Tom2, Tom3, OH-L, OH-R." if es_bateria else "Genera 3 variaciones."
    return f"""Eres un Ingeniero de Mezcla Senior. Usuario busca: "{req.prompt}" para {req.consola}. {reglas}
REGLA DE ORO: NO devuelvas ganancias de EQ en 0.0. Aplica EQ quirúrgico, Gates y Compresión.
MANUAL:
- Batería: HPF 30-80Hz, ataque 3-5kHz, corte 300-500Hz.
- Overheads: HPF 300Hz, aire 10-12kHz.
- Bajo: HPF 30Hz, fundamental 80-100Hz.
- Guitarras: HPF 80-100Hz, mordida 2-4kHz.
- Voz: HPF 80Hz, inteligibilidad 3-5kHz.
- Teclados: HPF 50Hz, aire 10kHz.
- Étnicos: HPF 100-150Hz, brillo 5-8kHz.
- Percusión: HPF 80Hz, ataque 3kHz.
- Metales: HPF 100Hz, brillo 6-8kHz.
GANANCIAS EQ: eq1_g (-4 a +4), eq2_g (-3 a -6), eq3_g (+2 a +5), eq4_g (+2 a +4). Q entre 0.8 y 2.5.
Gate: Batería ON, Overheads OFF, Voz OFF, Bajo ON.
Compresor: Batería ON, Overheads ON, Voz ON, Bajo ON, Suaves OFF.
Devuelve SOLO un array JSON con: nombre_variacion, gate_on, comp_on, eq_on, eq1_f, eq1_g, eq1_q, eq2_f, eq2_g, eq2_q, eq3_f, eq3_g, eq3_q, eq4_f, eq4_g, eq4_q, comp_thr, comp_rat, gate_thr, guia_texto."""

def generar_con_gemini(prompt_sistema):
    if not GEMINI_API_KEY:
        raise Exception("Gemini API Key no configurada")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {"contents": [{"parts": [{"text": prompt_sistema}]}], "generationConfig": {"response_mime_type": "application/json"}}
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=90) as response:
        res_data = json.loads(response.read().decode('utf-8'))
        return res_data["candidates"][0]["content"]["parts"][0]["text"]

def generar_con_groq(prompt_sistema):
    if not GROQ_API_KEY:
        raise Exception("Groq API Key no configurada")
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
    payload = {"model": "openai/gpt-oss-20b", "messages": [{"role": "user", "content": prompt_sistema}], "response_format": {"type": "json_object"}}
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=90) as response:
        res_data = json.loads(response.read().decode('utf-8'))
        return res_data["choices"][0]["message"]["content"]

def generar_con_openrouter(prompt_sistema):
    if not OPENROUTER_API_KEY:
        raise Exception("OpenRouter API Key no configurada")
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
    payload = {"models": ["google/gemini-2.0-flash-exp:free", "meta-llama/llama-3.3-70b-instruct:free"], "messages": [{"role": "user", "content": prompt_sistema}], "response_format": {"type": "json_object"}}
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=120) as response:
        res_data = json.loads(response.read().decode('utf-8'))
        return res_data["choices"][0]["message"]["content"]

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
    if not req.email:
        raise HTTPException(status_code=403, detail="Se requiere el email")
    valido, msj = verificar_limite(req.email, req.hwid, req.consola)
    if not valido:
        raise HTTPException(status_code=403, detail=msj)

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

    prompt_sistema = construir_prompt(req)
    json_respuesta = None
    modelo_usado = None
    errores = []

    proveedores = [
        ("gemini", generar_con_gemini),
        ("groq", generar_con_groq),
        ("openrouter", generar_con_openrouter),
    ]

    for nombre, funcion in proveedores:
        for attempt in range(3):
            try:
                print(f"Intentando con {nombre} (intento {attempt + 1})...")
                respuesta_ai = funcion(prompt_sistema)
                
                # --- VALIDACIÓN DEL JSON DE LA IA ---
                try:
                    # A veces la IA envuelve el JSON en markdown ```json ... ```
                    if respuesta_ai.strip().startswith("```json"):
                        respuesta_ai = respuesta_ai.replace("```json", "").replace("```", "").strip()
                    
                    json.loads(respuesta_ai) # Validamos que sea JSON
                    json_respuesta = respuesta_ai
                    modelo_usado = nombre
                    print(f"¡Éxito con {nombre}!")
                    break
                except json.JSONDecodeError:
                    raise Exception(f"{nombre} devolvió un formato inválido.")

            except urllib.error.HTTPError as e:
                if e.code in [409, 429, 503] and attempt < 2:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    print(f"Error {e.code} con {nombre}. Reintentando en {wait_time:.2f}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    errores.append(f"{nombre}: {str(e)}")
                    break
            except Exception as e:
                errores.append(f"{nombre}: {str(e)}")
                break
        if json_respuesta:
            break

    if not json_respuesta:
        raise HTTPException(status_code=500, detail=f"Todas las IAs fallaron. Detalles: {'; '.join(errores)}")

    # Guardar en caché y cobrar
    try:
        url_post_cache = f"{SUPABASE_URL}/rest/v1/cache_presets"
        body_post_cache = json.dumps({"consola": req.consola, "prompt_buscado": prompt_limpio, "datos_json": json.loads(json_respuesta)}).encode('utf-8')
        req_post_cache = urllib.request.Request(url_post_cache, data=body_post_cache, headers=headers_supabase, method='POST')
        urllib.request.urlopen(req_post_cache)
    except Exception as e:
        pass

    cobrar_generacion(req.email, req.hwid)
    return {"status": "ok", "modelo_usado": modelo_usado, "mensaje_limite": "Generación exitosa", "datos": json_respuesta}

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
        PACKS_LICENCIA = {"kwcedd": 100, "xsocpy": 200, "sodyxd": 500, "xzkedi": 1000, "wzzlgq": 5000}
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
