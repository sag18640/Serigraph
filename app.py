from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from dotenv import load_dotenv
import os
load_dotenv()  
app = Flask(__name__)

account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
auth_token = os.environ.get('TWILIO_AUTH_TOKEN')

client = Client(account_sid, auth_token)


user_data = {}

@app.route("/webhook", methods=["POST"])
def webhook():
    global user_data

    incoming_message = request.form.get("Body", "").lower()
    user_number = request.form.get("From", "")

    response_message = ""
    twiml = MessagingResponse()

    if "hola" in incoming_message:
        response_message = (
            "¡Hola! Bienvenido a nuestro servicio de atención al cliente. "
            "Por favor, elige una opción:\n\n"
            "1. Servicio de impresión\n"
            "2. Servicio de diseño\n"
            "3. Servicio de envíos"
        )
        user_data[user_number] = {"step": "menu"}  

    elif user_number in user_data:
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
            try:
                ancho, alto = incoming_message.split("x")
                response_message = (
                    f"Has ingresado un tamaño de {ancho}x{alto} cm.\n"
                    "Ahora, elige el material:\n"
                    "1. Papel couché\n"
                    "2. Vinil adhesivo\n"
                    "3. Lona"
                )
                user_data[user_number].update({"ancho": ancho, "alto": alto, "step": "seleccion_material"})
            except:
                response_message = "Formato incorrecto. Por favor, ingresa el ancho y alto en formato '20x30'."

        elif user_data[user_number]["step"] == "seleccion_material":
            materiales = {"1": "Papel couché", "2": "Vinil adhesivo", "3": "Lona"}
            if incoming_message in materiales:
                user_data[user_number]["material"] = materiales[incoming_message]
                response_message = (
                    f"Seleccionaste {materiales[incoming_message]}.\n"
                    "Ahora, ingresa la cantidad de volantes que deseas imprimir."
                )
                user_data[user_number]["step"] = "seleccion_cantidad"
            else:
                response_message = "Opción no válida. Por favor, elige 1, 2 o 3."

        elif user_data[user_number]["step"] == "seleccion_cantidad":
            if incoming_message.isdigit():
                user_data[user_number]["cantidad"] = int(incoming_message)
                response_message = (
                    f"Perfecto. Has solicitado {user_data[user_number]['cantidad']} volantes en "
                    f"{user_data[user_number]['material']} de {user_data[user_number]['ancho']}x{user_data[user_number]['alto']} cm.\n"
                    "¿Confirmas? (Responde 'sí' o 'no')."
                )
                user_data[user_number]["step"] = "confirmacion_final"
            else:
                response_message = "Por favor, ingresa un número válido."

        elif user_data[user_number]["step"] == "confirmacion_final":
            if "sí" in incoming_message:
                precios = {"Papel couché": 0.50, "Vinil adhesivo": 1.00, "Lona": 2.00}
                costo_total = precios[user_data[user_number]["material"]] * user_data[user_number]["cantidad"]

                response_message = (
                    f"¡Gracias! Tu cotización es:\n"
                    f"Material: {user_data[user_number]['material']}\n"
                    f"Tamaño: {user_data[user_number]['ancho']}x{user_data[user_number]['alto']} cm\n"
                    f"Cantidad: {user_data[user_number]['cantidad']}\n"
                    f"Total estimado: ${costo_total:.2f}\n\n"
                    "Nos pondremos en contacto para finalizar el pedido."
                )
                del user_data[user_number]
            else:
                response_message = "Cotización cancelada. ¿En qué más puedo ayudarte?"
                del user_data[user_number]

    else:
        response_message = "Por favor, escribe 'hola' para comenzar."

    twiml.message(response_message)
    return str(twiml)

if __name__ == "__main__":
    app.run(debug=True)