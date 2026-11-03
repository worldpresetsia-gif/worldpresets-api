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
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")

codigos_pendientes = {}

# ... (El resto de las funciones: enviar_email, registrar_usuario, verificar_limite, cobrar_generacion, es_solicitud_de_bateria se mantienen igual) ...

# --- Nueva función de generación con Fallback ---
def generar_preset_con_fallback(prompt_sistema):
    # Lista de proveedores en orden de preferencia (los más generosos en TPM primero)
    proveedores = [
        {
            "nombre": "gemini",
            "url": f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
            "headers": {"Content-Type": "application/json"},
            "payload": lambda p: {
                "contents": [{"parts": [{"text": p}]}],
                "generationConfig": {"response_mime_type": "application/json"}
            }
        },
        {
            "nombre": "mistral",
            "url": "https://api.mistral.ai/v1/chat/completions",
            "headers": {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
            "payload": lambda p: {
                "model": "mistral-large-latest",
                "messages": [{"role": "user", "content": p}],
                "response_format": {"type": "json_object"}
            }
        },
        {
            "nombre": "groq",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "headers": {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            "payload": lambda p: {
                "model": "openai/gpt-oss-20b",
                "messages": [{"role": "user", "content": p}],
                "response_format": {"type": "json_object"}
            }
        },
        {
            "nombre": "openrouter",
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "headers": {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            "payload": lambda p: {
                "models": ["google/gemini-2.0-flash-exp:free", "meta-llama/llama-3.3-70b-instruct:free"],
                "messages": [{"role": "user", "content": p}],
                "response_format": {"type": "json_object"}
            }
        }
    ]

    for prov in proveedores:
        # ... (lógica de reintento para cada proveedor) ...
        try:
            # ... realizar la petición ...
            # Si tiene éxito, devolver el JSON
            return json_respuesta
        except Exception as e:
            print(f"Proveedor {prov['nombre']} falló: {e}")
            continue # Pasar al siguiente proveedor

    raise HTTPException(status_code=500, detail="Todos los proveedores de IA fallaron.")

# --- Prompt Optimizado (más corto) ---
def construir_prompt(req):
    es_bateria = es_solicitud_de_bateria(req.prompt)
    reglas = "Genera 8 presets: Kick, Snare, HiHat, Tom1, Tom2, Tom3, OH-L, OH-R." if es_bateria else "Genera 3 variaciones."
    
    prompt = f"""Eres un Ingeniero de Mezcla Senior. Usuario busca: "{req.prompt}" para {req.consola}. {reglas}
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
    return prompt
