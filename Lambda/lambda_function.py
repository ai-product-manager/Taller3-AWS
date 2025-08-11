# lambda_function.py
import os, json, uuid, datetime
import boto3
from boto3.dynamodb.conditions import Key

DDB = boto3.resource("dynamodb").Table(os.getenv("TABLE_NAME", "WorkshopAppointments"))

def _close(intent_name, text):
    # Lex V2 Close response
    return {
        "sessionState": {
            "dialogAction": {"type": "Close"},
            "intent": {"name": intent_name, "state": "Fulfilled"},
        },
        "messages": [{"contentType": "PlainText", "content": text}],
    }

def _get_slot(event, name):
    slots = event["sessionState"]["intent"].get("slots") or {}
    v = slots.get(name)
    return v and v.get("value", {}).get("interpretedValue")

def _hours():
    it = DDB.get_item(Key={"pk": "INFO", "sk": "HOURS"}).get("Item")
    return it or {"open":"09:00","close":"18:00","slotMinutes":30}

def _parse_time(s):  # "HH:MM" -> datetime.time
    h, m = map(int, s.split(":"))
    return datetime.time(h, m)

def _iter_slots(day, t_open, t_close, minutes):
    cur = datetime.datetime.combine(day, t_open)
    end = datetime.datetime.combine(day, t_close)
    while cur <= end:
        yield cur.time().strftime("%H:%M")
        cur += datetime.timedelta(minutes=minutes)

def make_booking(intent_name, event):
    shop = _get_slot(event, "ShopId") or "Main"
    service = (_get_slot(event, "Service") or "Mantenimiento").title()
    date_s = _get_slot(event, "Date")
    time_s = _get_slot(event, "Time")
    name = _get_slot(event, "Name") or "Cliente"
    phone = _get_slot(event, "Phone")
    plate = _get_slot(event, "Plate") or "-"
    if not (date_s and time_s and phone):
        return _close(intent_name, "Me faltan datos (fecha, hora y teléfono).")

    # Validar horario y colisión
    hrs = _hours()
    t_open, t_close = _parse_time(hrs["open"]), _parse_time(hrs["close"])
    if not (hrs["open"] <= time_s <= hrs["close"]):
        return _close(intent_name, f"Nuestro horario es {hrs['open']} a {hrs['close']}.")

    appt_id = "A-" + uuid.uuid4().hex[:8].upper()
    shop_pk = f"SHOP#{shop}"
    sk = f"APPT#{date_s}#{time_s}#{appt_id}"

    # Chequear colisión exacta en ese horario
    q = DDB.query(
        KeyConditionExpression=Key("pk").eq(shop_pk) & Key("sk").begins_with(f"APPT#{date_s}#{time_s}#")
    )
    if q.get("Items"):
        return _close(intent_name, "Ese horario ya está tomado. ¿Quieres otro?")

    # Escribir dos items: por SHOP y por CUSTOMER
    DDB.put_item(Item={
        "pk": shop_pk, "sk": sk,
        "service": service, "date": date_s, "time": time_s,
        "name": name, "phone": phone, "plate": plate
    })
    DDB.put_item(Item={
        "pk": f"CUSTOMER#{phone}", "sk": sk,
        "service": service, "date": date_s, "time": time_s,
        "name": name, "shop": shop, "plate": plate
    })
    msg = f"Listo {name}. Reservé {service} el {date_s} a las {time_s}. Tu ID es {appt_id}."
    return _close(intent_name, msg)

def cancel_booking(intent_name, event):
    appt_id = _get_slot(event, "AppointmentId")
    phone = _get_slot(event, "Phone")
    date_s = _get_slot(event, "Date")
    shop = _get_slot(event, "ShopId") or "Main"

    items_to_del = []
    if appt_id:
        # Buscar por SHOP y por CUSTOMER usando begins_with
        shop_pk = f"SHOP#{shop}"
        q1 = DDB.query(KeyConditionExpression=Key("pk").eq(shop_pk) & Key("sk").begins_with(f"APPT#"))
        for it in q1.get("Items", []):
            if it["sk"].endswith(appt_id):
                items_to_del.append(("SHOP", it))
        # Buscar en CUSTOMER
        if phone:
            q2 = DDB.query(KeyConditionExpression=Key("pk").eq(f"CUSTOMER#{phone}") & Key("sk").begins_with("APPT#"))
            for it in q2.get("Items", []):
                if it["sk"].endswith(appt_id):
                    items_to_del.append(("CUST", it))
    elif phone and date_s:
        # Cancelar la primera cita del cliente ese día
        q = DDB.query(
            KeyConditionExpression=Key("pk").eq(f"CUSTOMER#{phone}") & Key("sk").begins_with(f"APPT#{date_s}#")
        )
        if q.get("Items"):
            items_to_del.append(("CUST", q["Items"][0]))
    else:
        return _close(intent_name, "Indica el ID de la cita, o teléfono y fecha.")

    if not items_to_del:
        return _close(intent_name, "No encontré la cita a cancelar.")

    # Borrar en ambas particiones si es posible
    deleted = 0
    for _, it in items_to_del:
        DDB.delete_item(Key={"pk": it["pk"], "sk": it["sk"]})
        deleted += 1
    msg = "Cita cancelada." if deleted else "No se pudo cancelar."
    return _close(intent_name, msg)

def check_availability(intent_name, event):
    shop = _get_slot(event, "ShopId") or "Main"
    service = (_get_slot(event, "Service") or "Mantenimiento").title()
    date_s = _get_slot(event, "Date")
    if not date_s:
        return _close(intent_name, "¿Para qué fecha necesitas disponibilidad?")
    hrs = _hours()
    day = datetime.date.fromisoformat(date_s)
    taken = set()

    q = DDB.query(
        KeyConditionExpression=Key("pk").eq(f"SHOP#{shop}") & Key("sk").begins_with(f"APPT#{date_s}#")
    )
    for it in q.get("Items", []):
        taken.add(it["time"])
    slots = [
        t for t in _iter_slots(day, _parse_time(hrs["open"]), _parse_time(hrs["close"]), int(hrs.get("slotMinutes", 30)))
        if t not in taken
    ]
    if not slots:
        return _close(intent_name, f"No hay horarios disponibles el {date_s}.")
    msg = f"Disponibilidad para {service} el {date_s}: " + ", ".join(slots[:10]) + "."
    return _close(intent_name, msg)

def opening_hours(intent_name, event):
    hrs = _hours()
    return _close(intent_name, f"Atendemos de {hrs['open']} a {hrs['close']}.")

def lambda_handler(event, context):
    intent = event["sessionState"]["intent"]["name"]
    if intent == "MakeBooking":
        return make_booking(intent, event)
    if intent == "CancelBooking":
        return cancel_booking(intent, event)
    if intent == "CheckAvailability":
        return check_availability(intent, event)
    if intent == "OpeningHours":
        return opening_hours(intent, event)
    return _close(intent, "Puedo ayudarte a reservar, cancelar, ver horarios y disponibilidad.")
