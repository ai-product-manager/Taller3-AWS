# lambda_function.py
import json
import time
import math
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError

# --- APIs públicas sin API key ---
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
MET_NO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"

# --- Utilidades HTTP (reintentos, UA y timeout) ---

def _http_get(url, params, timeout=2.5, retries=2, backoff=0.35, ua="lambda-weather-demo/1.0"):
    """
    GET con reintentos exponenciales (para 5xx/URLError), timeout corto y User-Agent.
    Pensado para Lambdas con timeouts bajos.
    """
    q = urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(
        f"{url}?{q}",
        headers={"User-Agent": ua, "Accept": "application/json"}
    )
    last_err = None
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            # Reintentar solo 5xx
            if 500 <= e.code <= 599 and i < retries:
                last_err = e
                time.sleep(backoff * (2 ** i))
                continue
            raise
        except URLError as e:
            # Red transitoria: reintentar
            if i < retries:
                last_err = e
                time.sleep(backoff * (2 ** i))
                continue
            raise
    raise last_err

# --- Helpers de parámetros y formato Bedrock ---

def _extract_param(params, name, default=None):
    for p in params or []:
        if p.get("name") == name and p.get("value") not in (None, ""):
            return p.get("value")
    return default

def _bedrock_ok(event, body_dict, http_status=200):
    return _bedrock_response(event, http_status, body_dict)

def _bedrock_err(event, http_status, msg):
    return _bedrock_response(event, http_status, {"ok": False, "message": msg})

def _bedrock_response(event, status_code, body_dict):
    # Estructura exacta que Agents espera (body como *string* JSON)
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup"),
            "apiPath": event.get("apiPath"),
            "httpMethod": event.get("httpMethod"),
            "httpStatusCode": int(status_code),
            "responseBody": {
                "application/json": {
                    "body": json.dumps(body_dict, ensure_ascii=False)
                }
            }
        },
        "sessionAttributes": event.get("sessionAttributes", {}),
        "promptSessionAttributes": event.get("promptSessionAttributes", {})
    }

# --- Geocoding: Nominatim (sin key) ---

def geocode_city(city, lang="es"):
    """
    Usa Nominatim para obtener lat/lon de una ciudad. Devuelve (lat, lon, name)
    Nota: Nominatim recomienda User-Agent válido y uso responsable.
    """
    params = {
        "q": city,
        "format": "jsonv2",
        "limit": 1,
        "accept-language": lang
    }
    data = _http_get(NOMINATIM_URL, params, timeout=2.5, retries=1)
    if not data:
        return None, None, None
    item = data[0]
    lat = float(item["lat"])
    lon = float(item["lon"])
    name = item.get("display_name", city)
    return lat, lon, name

# --- Clima actual: MET Norway locationforecast (sin key) ---

def fetch_metno_current(lat, lon):
    """
    Llama a MET Norway Locationforecast 2.0 (compact) y extrae condiciones "actuales".
    - Requiere lat/lon.
    - Debes enviar User-Agent (si no, pueden responder 403).
    """
    # Recomendación oficial: limitar a 4 decimales para mejor caché.
    lat4 = round(float(lat), 4)
    lon4 = round(float(lon), 4)
    params = {"lat": lat4, "lon": lon4}

    data = _http_get(MET_NO_URL, params, timeout=2.5, retries=1, ua="lambda-weather-demo/1.0 (met.no)")
    props = (data or {}).get("properties") or {}
    ts = (props.get("timeseries") or [])
    if not ts:
        raise RuntimeError("MET.no sin timeseries")

    # Tomamos el primer bloque (ahora) – estructura: {time, data:{instant:{details}, next_1_hours:{summary, details}}}
    now = ts[0]
    when = now.get("time")
    inst = ((now.get("data") or {}).get("instant") or {}).get("details") or {}
    next1 = (now.get("data") or {}).get("next_1_hours") or {}
    precip_mm = None
    if "details" in next1 and "precipitation_amount" in next1["details"]:
        precip_mm = next1["details"]["precipitation_amount"]

    # Variables típicas en "instant.details"
    temp = inst.get("air_temperature")  # °C
    wind = inst.get("wind_speed")       # m/s
    wind_kmh = round(float(wind) * 3.6, 1) if wind is not None else None

    # Descripción básica a partir del summary (si está)
    summary = (next1.get("summary") or {}).get("symbol_code")  # ej: 'partlycloudy_day'
    desc = _symbol_to_spanish(summary)

    return {
        "ok": True,
        "provider": "met.no",
        "location": {
            "latitude": lat4,
            "longitude": lon4,
            "timezone": None
        },
        "current": {
            "temperature_c": temp,
            "feels_like_c": None,  # MET.no no entrega "feels_like" directo en este endpoint
            "precipitation_mm": precip_mm,
            "wind_speed_10m_kmh": wind_kmh,
            "weather_code": summary,
            "description_es": desc,
            "is_day": None,
            "time": when
        }
    }

def _symbol_to_spanish(symbol_code):
    """
    Traducción simple de códigos 'symbol_code' de MET.no a descripciones en español.
    (Mapa reducido a lo más común; puedes extenderlo según tu caso.)
    """
    if not symbol_code:
        return "condiciones no especificadas"
    base = symbol_code.replace("_day", "").replace("_night", "")
    mapping = {
        "clearsky": "cielo despejado",
        "cloudy": "nublado",
        "fair": "parcialmente despejado",
        "fog": "niebla",
        "heavyrain": "lluvia intensa",
        "lightrain": "lluvia ligera",
        "rain": "lluvia",
        "snow": "nieve",
        "heavysnow": "nieve intensa",
        "lightsnow": "nieve ligera",
        "partlycloudy": "parcialmente nublado",
        "thunderstorm": "tormenta"
    }
    return mapping.get(base, base.replace("-", " "))

# --- Handler principal (Agents for Bedrock) ---

def lambda_handler(event, context):
    """
    Soporta:
      - parameters: city | latitude + longitude
    Devuelve formato 'messageVersion 1.0' requerido por Agents (Action Group).
    """
    try:
        params = event.get("parameters", [])
        city = _extract_param(params, "city")
        lat = _extract_param(params, "latitude")
        lon = _extract_param(params, "longitude")

        # 1) Geocodificar si falta lat/lon y hay city
        if (not lat or not lon) and city:
            glat, glon, gname = geocode_city(city, lang="es")
            if not glat or not glon:
                return _bedrock_err(event, 404, f"No encontré coordenadas para '{city}'.")
            lat, lon = glat, glon
            city = gname or city

        if not lat or not lon:
            return _bedrock_err(event, 400, "Faltan parámetros: city o (latitude y longitude).")

        # 2) Consultar MET Norway
        try:
            met = fetch_metno_current(lat, lon)
        except Exception as e_met:
            # Si MET.no fallara (poco común), responde con error controlado
            return _bedrock_err(event, 502, f"No pude obtener clima ahora mismo (MET.no no disponible).")

        # 3) Armar mensaje amigable
        label = city or "las coordenadas dadas"
        desc = met["current"]["description_es"]
        temp = met["current"]["temperature_c"]
        feels = met["current"]["feels_like_c"]
        msg = f"En {label} ahora hay {desc}, temperatura {temp} °C."
        if feels is not None:
            msg = f"En {label} ahora hay {desc}, temperatura {temp} °C (sensación {feels} °C)."

        met["location"]["city"] = city
        met["message"] = msg

        return _bedrock_ok(event, met, http_status=200)

    except Exception as e:
        return _bedrock_err(event, 500, f"Error inesperado: {e}")
