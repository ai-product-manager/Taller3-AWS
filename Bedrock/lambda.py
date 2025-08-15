# lambda_function.py
import json
import urllib.parse
import urllib.request

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

def _http_get(url, params):
    query = urllib.parse.urlencode(params, doseq=True)
    with urllib.request.urlopen(f"{url}?{query}", timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _extract_param(params, name, default=None):
    for p in params or []:
        if p.get("name") == name and p.get("value") not in (None, ""):
            return p.get("value")
    return default

def lambda_handler(event, context):
    """
    Compatible con Action Group definido con OpenAPI schema.
    Formatos de entrada y salida según la doc de Bedrock Agents. 
    """
    # --- Leer parámetros del evento del agente ---
    params = event.get("parameters", [])
    city = _extract_param(params, "city")
    lat = _extract_param(params, "latitude")
    lon = _extract_param(params, "longitude")

    # Si no hay lat/lon, pero sí city -> geocodificar con Open-Meteo
    if (not lat or not lon) and city:
        geo = _http_get(GEOCODE_URL, {"name": city, "count": 1, "language": "es"})
        results = (geo or {}).get("results") or []
        if not results:
            return _bedrock_response(event, 404, {
                "ok": False,
                "message": f"No encontré coordenadas para '{city}'."
            })
        lat = results[0]["latitude"]
        lon = results[0]["longitude"]
        city = results[0].get("name") or city

    # Validación mínima
    if not lat or not lon:
        return _bedrock_response(event, 400, {
            "ok": False,
            "message": "Faltan parámetros: city o (latitude y longitude)."
        })

    # --- Llamar a Open-Meteo para 'current' ---
    # Variables 'current' según la doc de /v1/forecast
    query = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join([
            "temperature_2m",
            "apparent_temperature",
            "is_day",
            "precipitation",
            "weather_code",
            "wind_speed_10m"
        ]),
        "timezone": "auto"
    }
    try:
        data = _http_get(FORECAST_URL, query)
    except Exception as e:
        return _bedrock_response(event, 502, {
            "ok": False,
            "message": f"Error consultando Open-Meteo: {e}"
        })

    current = (data or {}).get("current") or {}
    if not current:
        return _bedrock_response(event, 502, {
            "ok": False,
            "message": "Respuesta de clima inválida o sin datos 'current'."
        })

    # Mapear weather_code (muy básico; puedes extenderlo)
    code = current.get("weather_code")
    code_map = {
        0: "cielo despejado",
        1: "mayormente despejado",
        2: "parcialmente nublado",
        3: "nublado",
        45: "niebla",
        48: "niebla con escarcha",
        51: "llovizna ligera",
        53: "llovizna",
        55: "llovizna intensa",
        61: "lluvia ligera",
        63: "lluvia",
        65: "lluvia intensa",
        71: "nieve ligera",
        80: "chubascos ligeros",
        95: "tormenta"
    }
    description = code_map.get(code, "condiciones no especificadas")

    payload = {
        "ok": True,
        "location": {
            "city": city,
            "latitude": float(lat),
            "longitude": float(lon),
            "timezone": data.get("timezone")
        },
        "current": {
            "temperature_c": current.get("temperature_2m"),
            "feels_like_c": current.get("apparent_temperature"),
            "precipitation_mm": current.get("precipitation"),
            "wind_speed_10m_kmh": current.get("wind_speed_10m"),
            "weather_code": code,
            "description_es": description,
            "is_day": bool(current.get("is_day")),
            "time": current.get("time")
        },
        # Mensaje listo para “decir” al usuario
        "message": (
            f"En {city or 'las coordenadas dadas'} ahora hay {description}, "
            f"temperatura {current.get('temperature_2m')} °C "
            f"(sensación {current.get('apparent_temperature')} °C)."
        )
    }

    # Respuesta en el **formato que espera Bedrock Agents** (OpenAPI schema)
    return _bedrock_response(event, 200, payload)

def _bedrock_response(event, status_code, body_dict):
    # Debe devolver 'application/json' con 'body' serializado como string JSON
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
