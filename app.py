from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from dotenv import load_dotenv
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import os
import time

load_dotenv()
app = Flask(__name__)

# Configurar Twilio
account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
client = Client(account_sid, auth_token)

# Diccionario para manejar los estados de los usuarios
user_data = {}

# Carpeta temporal para almacenar PDFs
TEMP_PDF_DIR = "temp_pdfs"

# Crear la carpeta si no existe
if not os.path.exists(TEMP_PDF_DIR):
    os.makedirs(TEMP_PDF_DIR)


def generar_pdf(numero_usuario, material, ancho, alto, cantidad, costo_total):
    """Genera un PDF con la cotización y devuelve la ruta del archivo."""
    file_name = f"cotizacion_{numero_usuario}_{int(time.time())}.pdf"
    file_path = os.path.join(TEMP_PDF_DIR, file_name)

    c = canvas.Canvas(file_path, pagesize=letter)
    c.drawString(100, 750, "Cotización de Impresión")
    c.drawString(100, 730, f"Cliente: {numero_usuario}")
    c.drawString(100, 710, f"Material: {material}")
    c.drawString(100, 690, f"Tamaño: {ancho}x{alto} cm")
    c.drawString(100, 670, f"Cantidad: {cantidad}")
    c.drawString(100, 650, f"Total estimado: ${costo_total:.2f}")
    c.drawString(100, 630, "Gracias por cotizar con nosotros.")
    
    c.save()
    return file_path  # Devolvemos la ruta del archivo PDF


def enviar_pdf_whatsapp(numero_usuario, file_path):
    """Envía el PDF por WhatsApp y luego lo elimina."""
    try:
        media_url = f"https://serigraph.onrender.com/temp_pdfs/{os.path.basename(file_path)}"  # Asegúrate de servir los archivos correctamente
        print(f"URL: {media_url}")
        message = client.messages.create(
            from_="whatsapp:+14155238886",  
            to=numero_usuario,
            media_url=[media_url],
            body="Aquí tienes tu cotización en PDF. ¡Gracias por cotizar con nosotros!"
        )
        print(f"MENSAJE : {message}")

        print(f"Mensaje enviado con SID: {message.sid}")

    except Exception as e:
        print(f"Error al enviar PDF: {e}")

    finally:
        # Eliminar el archivo después del envío
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"Archivo eliminado: {file_path}")


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

                # Generar el PDF
                file_path = generar_pdf(
                    user_number, user_data[user_number]["material"], 
                    user_data[user_number]["ancho"], user_data[user_number]["alto"], 
                    user_data[user_number]["cantidad"], costo_total
                )

                # Enviar el PDF y eliminarlo después
                enviar_pdf_whatsapp(user_number, file_path)

                response_message = "¡Tu cotización ha sido generada y enviada como PDF a tu WhatsApp!"
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
