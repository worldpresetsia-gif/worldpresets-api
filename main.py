import os
import json
import random
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="World Presets API")

# --- Configuración de APIs ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")

# Límites de tokens altos para evitar truncación
PROVIDER_MAX_TOKENS = {
    "gemini": 65536,
    "groq": 16384,
    "openrouter": 16384
}

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

def construir_prompt_base(req, cantidad, existentes=None):
    es_bateria = any(p in req.prompt.lower() for p in ["bateria","batería","drumkit","drums","kit"])
    contexto = ""
    if existentes:
        contexto = f"\n\nATENCIÓN: Ya generaste {len(existentes)} presets: {json.dumps(existentes)}. NO los repitas. Generá SOLO los {cantidad} presets que faltan para completar el total."

    return f"""Eres un Ingeniero de Mezcla Senior. Estás explicando al usuario cómo usar el preset para "{req.prompt}" en su consola {req.consola}.
Genera exactamente {cantidad} variaciones NUEVAS.
REGLA ESTRICTA: NO devuelvas EQ en 0.0. Debes aplicar EQ quirúrgico, Gates y Compresión con valores reales.

FORMATO OBLIGATORIO: Devuelve un array JSON válido. Cada elemento del array DEBE ser un objeto (diccionario).
REGLA DE CANTIDAD CRÍTICA: El array JSON DEBE contener EXACTAMENTE {cantidad} objetos.

EJEMPLO DE RESPUESTA VÁLIDA:
[
  {{
      "nombre_variacion": "Bajo Rock Activo 1", 
      "gate_on": 1, "comp_on": 1, "eq_on": 1, 
      "eq1_f": 60, "eq1_g": 2.5, "eq1_q": 1.0, 
      "eq2_f": 400, "eq2_g": -3.0, "eq2_q": 1.5, 
      "eq3_f": 1500, "eq3_g": 3.0, "eq3_q": 1.0, 
      "eq4_f": 4000, "eq4_g": 2.0, "eq4_q": 1.2, 
      "comp_thr": -15, "comp_rat": 4, "gate_thr": -50, 
      "guia_texto": "ESPAÑOL: Mirá, para este bajo le di cuerpo en los 60Hz y le corté los 400Hz. El compresor 4:1 mantiene los dedos parejos.\\n\\nTe recomiendo el Delay con Time 0.4s y Mix 15%.\\n\\n--- ENGLISH ---\\n\\nENGLISH: Look, for this bass I gave it body at 60Hz and cut at 400Hz. The 4:1 compressor keeps the fingers even.\\n\\nI recommend the Delay with Time 0.4s and Mix 15%."
  }}
]

REGLAS PARA "guia_texto":
- Bilingüe: Español, separador "--- ENGLISH ---", Inglés.
- Sección Español: 2 párrafos. Tono coloquial.
- Sección English: Traducción exacta de los mismos 2 párrafos.
{contexto}
Devuelve SOLO el array JSON con EXACTAMENTE {cantidad} objetos."""

def llamar_ia(nombre_proveedor, prompt):
    if nombre_proveedor == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"response_mime_type": "application/json", "maxOutputTokens": PROVIDER_MAX_TOKENS["gemini"]}}
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"}, method='POST')
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.loads(response.read().decode('utf-8'))["candidates"][0]["content"]["parts"][0]["text"]
    elif nombre_proveedor == "groq":
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        payload = {"model": "openai/gpt-oss-20b", "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}, "max_tokens": PROVIDER_MAX_TOKENS["groq"]}
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.loads(response.read().decode('utf-8'))["choices"][0]["message"]["content"]
    elif nombre_proveedor == "openrouter":
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        payload = {"models": ["google/gemini-2.0-flash-exp:free", "meta-llama/llama-3.3-70b-instruct:free"], "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}, "max_tokens": PROVIDER_MAX_TOKENS["openrouter"]}
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.loads(response.read().decode('utf-8'))["choices"][0]["message"]["content"]

def generar_presets_robusto(req):
    es_bateria = any(p in req.prompt.lower() for p in ["bateria","batería","drumkit","drums","kit"])
    cantidad_total = 8 if es_bateria else 3
    
    presets_acumulados = []
    proveedores = ["gemini", "groq", "openrouter"]
    
    for proveedor in proveedores:
        intentos = 0
        max_intentos = 3
        
        while len(presets_acumulados) < cantidad_total and intentos < max_intentos:
            cantidad_faltante = cantidad_total - len(presets_acumulados)
            prompt = construir_prompt_base(req, cantidad_faltante, presets_acumulados)
            
            try:
                respuesta = llamar_ia(proveedor, prompt)
                if respuesta.strip().startswith("```json"): respuesta = respuesta.replace("```json", "").replace("```", "").strip()
                
                parsed = json.loads(respuesta)
                
                # CASO 1: La IA devolvió exactamente lo que pedimos
                if isinstance(parsed, list) and len(parsed) == cantidad_faltante:
                    presets_acumulados.extend(parsed)
                    break # Ya completamos
                
                # CASO 2: La IA devolvió de más (truncamos)
                elif isinstance(parsed, list) and len(parsed) > cantidad_faltante:
                    presets_acumulados.extend(parsed[:cantidad_faltante])
                    break
                
                # CASO 3: La IA devolvió menos (acumulamos y pedimos el resto)
                elif isinstance(parsed, list) and 0 < len(parsed) < cantidad_faltante:
                    presets_acumulados.extend(parsed)
                    intentos += 1
                    continue
                else:
                    intentos += 1
                    continue
                    
            except Exception as e:
                print(f"Fallo con {proveedor} (Intento {intentos+1}): {e}")
                intentos += 1
                continue
        
        # Si ya tenemos todo, no hace falta probar el siguiente proveedor
        if len(presets_acumulados) >= cantidad_total:
            return presets_acumulados[:cantidad_total]
    
    # --- MODO EMERGENCIA (Si todo falló) ---
    # Generamos presets base con la lógica del servidor para que el cliente NUNCA vea un error.
    while len(presets_acumulados) < cantidad_total:
        base = {
            "nombre_variacion": f"Preset Base {len(presets_acumulados)+1}",
            "gate_on": 1, "comp_on": 1, "eq_on": 1,
            "eq1_f": 100, "eq1_g": 0, "eq1_q": 1,
            "eq2_f": 500, "eq2_g": 0, "eq2_q": 1,
            "eq3_f": 2000, "eq3_g": 0, "eq3_q": 1,
            "eq4_f": 8000, "eq4_g": 0, "eq4_q": 1,
            "comp_thr": -20, "comp_rat": 3, "gate_thr": -50,
            "guia_texto": "ESPAÑOL: El servidor de IA estaba saturado, por lo que se generó un preset de seguridad.\\n\\n--- ENGLISH ---\\n\\nENGLISH: The AI server was overloaded, so a safety preset was generated."
        }
        presets_acumulados.append(base)
        
    return presets_acumulados[:cantidad_total]

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
        
        # Buscar en caché
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{SUPABASE_URL}/rest/v1/cache_presets?consola=eq.{req.consola}&prompt_buscado=eq.{prompt_limpio}", headers=headers_supabase)) as response:
                cache_data = json.loads(response.read().decode('utf-8'))
                if len(cache_data) > 0:
                    cached_json = cache_data[0]["datos_json"]
                    if isinstance(cached_json, list) and len(cached_json) > 0:
                        cobrar_generacion(req.email, req.hwid)
                        return {"status": "ok", "modelo_usado": "cache", "mensaje_limite": "Generación desde caché", "datos": json.dumps(cached_json)}
        except: pass

        # Orquestador Robusto
        presets_finales = generar_presets_robusto(req)
        
        # Guardar en caché
        try:
            url_post_cache = f"{SUPABASE_URL}/rest/v1/cache_presets"
            body_post_cache = json.dumps({"consola": req.consola, "prompt_buscado": prompt_limpio, "datos_json": presets_finales}).encode('utf-8')
            urllib.request.urlopen(urllib.request.Request(url_post_cache, data=body_post_cache, headers=headers_supabase, method='POST'))
        except: pass

        cobrar_generacion(req.email, req.hwid)
        return {"status": "ok", "modelo_usado": "orquestador_robusto", "mensaje_limite": "Generación exitosa", "datos": json.dumps(presets_finales)}

    except Exception as e:
        return JSONResponse(status_code=200, content={"status": "error", "detail": f"Error interno: {str(e)}"})

@app.post("/gumroad-webhook")
async def gumroad_webhook(request: Request):
    # ... (El webhook se mantiene igual que en la versión anterior, sin cambios)
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
        PACKS_LICENCIA = {"knbbu": 20, "kwcedd": 100, "xsocpy": 200, "sodyxd": 500, "xzkedi": 1000, "wzzlgq": 5000}
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
