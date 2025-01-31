from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from dotenv import load_dotenv
import os
load_dotenv()  # Cargar variables desde .env
app = Flask(__name__)

# Obtener credenciales de Twilio desde variables de entorno
account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
auth_token = os.environ.get('TWILIO_AUTH_TOKEN')

# Inicializar el cliente de Twilio
client = Client(account_sid, auth_token)


# Estado de la conversación (simulado en memoria)
user_data = {}

@app.route("/webhook", methods=["POST"])
def webhook():
    global user_data

    # Obtener el mensaje entrante y el número del usuario
    incoming_message = request.form.get("Body", "").lower()
    user_number = request.form.get("From", "")

    # Inicializar la respuesta
    response_message = ""
    twiml = MessagingResponse()

    # Lógica del chatbot
    if "hola" in incoming_message:
        # Mostrar menú de servicios
        response_message = (
            "¡Hola! Bienvenido a nuestro servicio de atención al cliente. "
            "Por favor, elige una opción:\n\n"
            "1. Servicio de impresión\n"
            "2. Servicio de diseño\n"
            "3. Servicio de envíos"
        )
        user_data[user_number] = {"step": "menu"}  # Guardar estado

    elif user_number in user_data:
        # Manejar respuestas según el estado del usuario
        if user_data[user_number]["step"] == "menu":
            if "1" in incoming_message:
                response_message = (
                    "Has seleccionado el servicio de impresión. "
                    "Por favor, ingresa el ancho y alto en centímetros (ejemplo: 20x30)."
                )
                user_data[user_number] = {"step": "impresion", "service": "impresión"}
            elif "2" in incoming_message:
                response_message = (
                    "Has seleccionado el servicio de diseño. "
                    "Por favor, describe tu proyecto."
                )
                user_data[user_number] = {"step": "diseno", "service": "diseño"}
            elif "3" in incoming_message:
                response_message = (
                    "Has seleccionado el servicio de envíos. "
                    "Por favor, ingresa la dirección de entrega."
                )
                user_data[user_number] = {"step": "envios", "service": "envíos"}
            else:
                response_message = "Opción no válida. Por favor, elige 1, 2 o 3."

        elif user_data[user_number]["step"] == "impresion":
            # Procesar datos de impresión
            try:
                ancho, alto = incoming_message.split("x")
                response_message = (
                    f"Has ingresado un tamaño de {ancho}x{alto} cm para el servicio de impresión. "
                    "¿Confirmas? (responde 'sí' o 'no')."
                )
                user_data[user_number]["ancho"] = ancho
                user_data[user_number]["alto"] = alto
                user_data[user_number]["step"] = "confirmacion_impresion"
            except:
                response_message = "Formato incorrecto. Por favor, ingresa el ancho y alto en formato '20x30'."

        elif user_data[user_number]["step"] == "confirmacion_impresion":
            if "sí" in incoming_message:
                response_message = (
                    "¡Gracias! Hemos registrado tu pedido de impresión. "
                    f"Tamaño: {user_data[user_number]['ancho']}x{user_data[user_number]['alto']} cm."
                )
                del user_data[user_number]  # Limpiar estado
            else:
                response_message = "Pedido cancelado. ¿En qué más puedo ayudarte?"
                del user_data[user_number]  # Limpiar estado

        # Agregar más lógica para otros servicios (diseño, envíos, etc.)

    else:
        response_message = "Por favor, escribe 'hola' para comenzar."

    # Enviar respuesta
    twiml.message(response_message)
    return str(twiml)

if __name__ == "__main__":
    app.run(debug=True)