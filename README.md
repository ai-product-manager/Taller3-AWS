# Recap muy rápido (Sesiones 1 y 2)
- Tienes un bot Lex V2 con intents/slots listo y (opcional) fulfillment en Lambda + persistencia en DynamoDB.
- Ahora en la Sesión 3 lo haremos multicanal: texto (Lex) + voz (Polly) con una web sencilla y credenciales seguras (Cognito).

# Paso a paso
- Importar el bot en Amazon Lex V2
  - Entra a Amazon Lex V2 → Bots → Import.
  - Sube el ZIP de export (si tiene password, indícalo).
  - Finaliza la importación y espera a que aparezca el bot. 

# Crear/ajustar DynamoDB
- Abre DynamoDB → Tables → Create table (p.ej. TallerReservas con PK pk, SK sk).
- Semilla: horarios/servicios (pk: INFO, sk: HOURS) y pruebas de citas.
- Verifica que el IAM role de tu Lambda tenga dynamodb:GetItem/PutItem/Query.

# Build, Version & Alias
- Abre el bot importado → Build (compilar).
- Cuando termine: Versions → Create version (foto del estado).
- Ve a Aliases → Create alias (ej. prod) y apúntalo a la versión creada.
  - Anota Bot ID y Alias ID para el front.

# Conectar Lambda en el alias
- En el bot → Aliases → selecciona tu alias → Code hooks.
- Marca Fulfillment (y Initialization & validation solo si tu Lambda valida slots).
- Selecciona tu Lambda y guarda. (Luego Build si te pide).

# Probar el bot en el Test panel de Lex
- Testea intents/slots con mensajes típicos (p.ej., “Quiero reservar mantenimiento mañana a las 10”).
- Así confirmas que la importación quedó OK antes de ir a web.

# Crear Cognito Identity Pool (credenciales seguras en el navegador)
- Ve a Cognito → Identity pools → Create identity pool.
- Marca Guest access (unauthenticated) (si tu web no autentica usuarios).
- Termina el asistente: te crea el Identity Pool ID y los roles (guest/auth).

# Dar permisos al rol guest (Identity Pool) para Lex + Polly
- En Cognito → tu Identity pool → User access, haz clic en el rol unauthenticated para abrirlo en IAM.
- Add inline policy (JSON) y pega (ajusta región/cuenta/bot/alias):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "lex:RecognizeText",
      "Resource": "arn:aws:lex:us-east-1:TU_CUENTA:bot-alias/TU_BOT_ID/TU_ALIAS_ID" },
    { "Effect": "Allow", "Action": "polly:SynthesizeSpeech", "Resource": "*" }
  ]
}
```

- La acción RecognizeText es la que usa tu web en runtime. 
- El ARN debe ser de bot-alias (no del bot). 

# Probar Polly (voz LATAM) en consola
- Abre Amazon Polly → pestaña Text-to-Speech.
- Elige es-MX y la voz Mia (o Andrés).
- Sintetiza y escucha para confirmar acento. (Neural si está disponible).

# Conectar la web (index.html + webapp.js)
- En tu webapp.js, rellena: REGION, IDENTITY_POOL_ID, BOT_ID, BOT_ALIAS_ID, LOCALE_ID=es_419; usa VoiceId = "Mia".
- Tu web llama a RecognizeText (Lex) y a SynthesizeSpeech (Polly). 