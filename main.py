import os
import re
import json
import random
import urllib.request
import urllib.parse
import time
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="World Presets API")

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
    if not BREVO_API_KEY: return False
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
        with urllib.request.urlopen(req) as response: return True
    except: return False

def registrar_usuario_en_supabase(email):
    if email == "test@test.com" or not SUPABASE_URL or not SUPABASE_KEY: return
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=representation"}
    url_get = f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url_get, headers=headers)) as response:
            if len(json.loads(response.read().decode('utf-8'))) > 0: return
    except: pass
    url_post = f"{SUPABASE_URL}/rest/v1/usuarios"
    body_post = json.dumps({"email": email, "usadas": 0, "limite": 10, "tipo_licencia": "DEMO"}).encode('utf-8')
    try: urllib.request.urlopen(urllib.request.Request(url_post, data=body_post, headers=headers, method='POST'))
    except: pass

def verificar_limite(email, hwid, consola_solicitada):
    if email == "test@test.com": return True, "Usuario de prueba aceptado (Ilimitado)"
    if not SUPABASE_URL or not SUPABASE_KEY: return False, "Faltan variables de Supabase"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=representation"}
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}", headers=headers)) as response:
            data = json.loads(response.read().decode('utf-8'))
    except Exception as e: return False, f"Error DB: {e}"
    
    if len(data) > 0:
        usuario = data[0]
        hwid_guardado = usuario.get("hwid")
        if hwid_guardado and hwid_guardado != hwid: return False, "Email en otra PC. Contactá a soporte."
        if not hwid_guardado and hwid:
            try: urllib.request.urlopen(urllib.request.Request(f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}", data=json.dumps({"hwid": hwid}).encode('utf-8'), headers=headers, method='PATCH'))
            except: pass
        if usuario.get("tipo_licencia") == "XR18" and consola_solicitada not in ["XR18 - MR18", "X32 - M32", "X32", "XR18"]:
            return False, "Licencia solo para XR18."
        if usuario["usadas"] >= usuario["limite"]: return False, f"Límite alcanzado ({usuario['limite']} gen)."
        return True, "Verificado"
    return True, "Nuevo usuario"

def cobrar_generacion(email, hwid):
    if email == "test@test.com": return
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}", headers=headers)) as response:
            data = json.loads(response.read().decode('utf-8'))
        if len(data) > 0:
            body_patch = json.dumps({"usadas": data[0]["usadas"] + 1}).encode('utf-8')
            urllib.request.urlopen(urllib.request.Request(f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}", data=body_patch, headers=headers, method='PATCH'))
        else:
            body_post = json.dumps({"email": email, "usadas": 1, "limite": 10, "hwid": hwid, "tipo_licencia": "DEMO"}).encode('utf-8')
            urllib.request.urlopen(urllib.request.Request(f"{SUPABASE_URL}/rest/v1/usuarios", data=body_post, headers=headers, method='POST'))
    except: pass

def construir_prompt(req):
    es_bateria = any(p in req.prompt.lower() for p in ["bateria","batería","drumkit","drums","kit"])
    num_presets = 8 if es_bateria else 3
    
    return f"""Eres un Ingeniero de Mezcla Senior. Usuario: "{req.prompt}" para {req.consola}.
Genera exactamente {num_presets} variaciones.
REGLA ESTRICTA: NO devuelvas EQ en 0.0. Debes aplicar EQ quirúrgico, Gates y Compresión con valores reales.

FORMATO OBLIGATORIO: Devuelve un array JSON válido. Cada elemento del array DEBE ser un objeto (diccionario) con las llaves exactas que se muestran en el ejemplo. NO devuelvas strings sueltos.

EJEMPLO DE RESPUESTA VÁLIDA:
[{{
    "nombre_variacion": "Bajo Rock Activo 1", 
    "gate_on": 1, "comp_on": 1, "eq_on": 1, 
    "eq1_f": 60, "eq1_g": 2.5, "eq1_q": 1.0, 
    "eq2_f": 400, "eq2_g": -3.0, "eq2_q": 1.5, 
    "eq3_f": 1500, "eq3_g": 3.0, "eq3_q": 1.0, 
    "eq4_f": 4000, "eq4_g": 2.0, "eq4_q": 1.2, 
    "comp_thr": -15, "comp_rat": 4, "gate_thr": -50, 
    "guia_texto": "PÁRRAFO 1: ... \n\n PÁRRAFO 2: ... \n\n PÁRRAFO 3: ..."
}}]

REGLAS PARA EL CAMPO "guia_texto":
Escribe una GUÍA PRÁCTICA y DETALLADA. 
EXTENSIÓN: Mínimo 3 párrafos. Sé tan detallado como sea necesario para explicar todo a un principiante, pero sé conciso y evita escribir una enciclopedia (máximo 6 párrafos).
1. Explicación del EQ y Compresor: Qué frecuencias tocaste y por qué.
2. RECOMENDACIÓN DE EFECTOS ESPECÍFICOS PARA {req.consola}: Menciona al menos un efecto que ESTÉ DISPONIBLE en el procesador de efectos de la {req.consola} (ej. Plate Reverb, Chorus, Delay) y da parámetros exactos (Decay, Mix, Time).
3. Consejo Pro de mezcla en vivo (ej. cómo manejar el fader, el gate o la ganancia).

MANUAL: Batería HPF 30-80, ataque 3-5k, corte 300-500. Bajo HPF 30, fund 80-100. Guitarras HPF 80-100, mordida 2-4k. Voz HPF 80, intel 3-5k.
Devuelve SOLO el array JSON con {num_presets} objetos."""

def generar_con_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"response_mime_type": "application/json"}}
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"}, method='POST')
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.loads(response.read().decode('utf-8'))["candidates"][0]["content"]["parts"][0]["text"]

def generar_con_groq(prompt):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    payload = {"model": "openai/gpt-oss-20b", "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.loads(response.read().decode('utf-8'))["choices"][0]["message"]["content"]

def generar_con_openrouter(prompt):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    payload = {"models": ["google/gemini-2.0-flash-exp:free", "meta-llama/llama-3.3-70b-instruct:free"], "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.loads(response.read().decode('utf-8'))["choices"][0]["message"]["content"]

@app.get("/")
def read_root(): return {"status": "Portero listo"}

@app.post("/enviar-codigo")
def enviar_codigo(req: EmailRequest):
    codigo = str(random.randint(100000, 999999))
    codigos_pendientes[req.email] = codigo
    if enviar_email_brevo(req.email, codigo): return {"status": "ok", "mensaje": "Código enviado"}
    else: raise HTTPException(status_code=500, detail="Error al enviar correo")

@app.post("/verificar-codigo")
def verificar_codigo(req: CodigoRequest):
    if req.email in codigos_pendientes and codigos_pendientes[req.email] == req.codigo:
        del codigos_pendientes[req.email]
        registrar_usuario_en_supabase(req.email)
        return {"status": "ok", "mensaje": "Verificado correctamente"}
    else: raise HTTPException(status_code=400, detail="Código incorrecto")

@app.post("/generar")
def generar_preset(req: PresetRequest):
    try:
        if not req.email: return JSONResponse(status_code=200, content={"status": "error", "detail": "Se requiere el email"})
        
        valido, msj = verificar_limite(req.email, req.hwid, req.consola)
        if not valido: return JSONResponse(status_code=200, content={"status": "error", "detail": msj})

        prompt_limpio = req.prompt.lower().strip()
        headers_supabase = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{SUPABASE_URL}/rest/v1/cache_presets?consola=eq.{req.consola}&prompt_buscado=eq.{prompt_limpio}", headers=headers_supabase)) as response:
                cache_data = json.loads(response.read().decode('utf-8'))
                if len(cache_data) > 0:
                    cached_json = cache_data[0]["datos_json"]
                    if isinstance(cached_json, list) and len(cached_json) > 0 and isinstance(cached_json[0], dict):
                        cobrar_generacion(req.email, req.hwid)
                        return {"status": "ok", "modelo_usado": "cache", "mensaje_limite": "Generación desde caché", "datos": json.dumps(cached_json)}
        except: pass

        prompt_sistema = construir_prompt(req)
        json_respuesta = None
        modelo_usado = None
        errores = []

        proveedores = [("gemini", generar_con_gemini), ("groq", generar_con_groq), ("openrouter", generar_con_openrouter)]

        for nombre, funcion in proveedores:
            try:
                print(f"Intentando con {nombre}...")
                respuesta_ai = funcion(prompt_sistema)
                if respuesta_ai.strip().startswith("```json"): respuesta_ai = respuesta_ai.replace("```json", "").replace("```", "").strip()
                
                parsed_json = json.loads(respuesta_ai)
                if not isinstance(parsed_json, list):
                    raise Exception("La IA no devolvió una lista.")
                for item in parsed_json:
                    if not isinstance(item, dict):
                        raise Exception("La IA devolvió un elemento que no es un diccionario.")

                json_respuesta = respuesta_ai
                modelo_usado = nombre
                break
            except Exception as e:
                errores.append(f"{nombre}: {str(e)}")
                print(f"Falló {nombre} (o formato incorrecto): {e}")
                continue

        if not json_respuesta:
            return JSONResponse(status_code=200, content={"status": "error", "detail": f"Servidores de IA saturados o respuesta inválida. Intenta de nuevo."})

        try:
            url_post_cache = f"{SUPABASE_URL}/rest/v1/cache_presets"
            body_post_cache = json.dumps({"consola": req.consola, "prompt_buscado": prompt_limpio, "datos_json": json.loads(json_respuesta)}).encode('utf-8')
            urllib.request.urlopen(urllib.request.Request(url_post_cache, data=body_post_cache, headers=headers_supabase, method='POST'))
        except: pass

        cobrar_generacion(req.email, req.hwid)
        return {"status": "ok", "modelo_usado": modelo_usado, "mensaje_limite": "Generación exitosa", "datos": json_respuesta}

    except Exception as e:
        return JSONResponse(status_code=200, content={"status": "error", "detail": f"Error interno: {str(e)}"})

@app.post("/gumroad-webhook")
async def gumroad_webhook(request: Request):
    try:
        body = await request.body()
        parsed = urllib.parse.parse_qs(body.decode('utf-8'))
        datos = {k: v[0] for k, v in parsed.items()}
        if datos.get("refunded") == "true": return {"status": "ok", "mensaje": "Reembolso ignorado"}
        email = datos.get("email")
        product_id = datos.get("short_product_id") or datos.get("product_id")
        if not email or not product_id: return {"status": "error", "mensaje": "Faltan datos"}
        
        ID_DEMO = "eqtcpr"
        ID_DEMO_ALT = "eqtpr"

        PACKS_LICENCIA = {
            "knbbu": 20,
            "kwcedd": 100, "xsocpy": 200, "sodyxd": 500, "xzkedi": 1000, "wzzlgq": 5000
        }
        RECARGAS = {"duahk": 100}
        
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=representation"}
        with urllib.request.urlopen(urllib.request.Request(f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}", headers=headers)) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        if len(data) > 0:
            usuario = data[0]
            if product_id in PACKS_LICENCIA:
                nuevo_limite = usuario["limite"] + PACKS_LICENCIA[product_id]
                urllib.request.urlopen(urllib.request.Request(f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}", data=json.dumps({"limite": nuevo_limite, "tipo_licencia": "FULL"}).encode('utf-8'), headers=headers, method='PATCH'))
                return {"status": "ok"}
            elif product_id in RECARGAS:
                if usuario.get("tipo_licencia") == "DEMO": return {"status": "error"}
                nuevo_limite = usuario["limite"] + RECARGAS[product_id]
                urllib.request.urlopen(urllib.request.Request(f"{SUPABASE_URL}/rest/v1/usuarios?email=eq.{email}", data=json.dumps({"limite": nuevo_limite}).encode('utf-8'), headers=headers, method='PATCH'))
                return {"status": "ok"}
            return {"status": "ok"}
        else:
            if product_id in PACKS_LICENCIA:
                urllib.request.urlopen(urllib.request.Request(f"{SUPABASE_URL}/rest/v1/usuarios", data=json.dumps({"email": email, "usadas": 0, "limite": PACKS_LICENCIA[product_id], "tipo_licencia": "FULL"}).encode('utf-8'), headers=headers, method='POST'))
                return {"status": "ok"}
            elif product_id == ID_DEMO or product_id == ID_DEMO_ALT:
                urllib.request.urlopen(urllib.request.Request(f"{SUPABASE_URL}/rest/v1/usuarios", data=json.dumps({"email": email, "usadas": 0, "limite": 10, "tipo_licencia": "DEMO"}).encode('utf-8'), headers=headers, method='POST'))
                return {"status": "ok"}
            return {"status": "error"}
    except Exception as e:
        return {"status": "error", "mensaje": str(e)}
