from flask import Flask, request, send_from_directory
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from dotenv import load_dotenv
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import os
import sqlite3
import time

load_dotenv()
app = Flask(__name__)

#Configurar base de datos
conn = sqlite3.connect('/var/www/db_serigraph/seri.db')
cursor = conn.cursor()

# Configurar Twilio
account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
client = Client(account_sid, auth_token)

#productos
query_products="SELECT * FROM products;"
cursor.execute(query_products)
filas = cursor.fetchall()
diccionario_productos={}
for fila in filas:
    diccionario_productos[fila[1]]=fila[2]

#dimensiones
query_dim="SELECT * FROM dimensions_volante;"
cursor.execute(query_dim)
filas = cursor.fetchall()
diccionario_dimensiones={}
for fila in filas:
    diccionario_dimensiones[fila[1]]=fila[2]

#materiales
query_mat="SELECT * FROM material;"
cursor.execute(query_mat)
filas = cursor.fetchall()
diccionario_material={}
numero=1
for fila in filas:
    diccionario_material[fila[1]]=fila[2]
    materiales = {numero:fila[1]}
    numero+=1


# Diccionario para manejar los estados de los usuarios
user_data = {}

# Carpeta temporal para almacenar PDFs
TEMP_PDF_DIR = "temp_pdfs"

# Crear la carpeta si no existe
if not os.path.exists(TEMP_PDF_DIR):
    os.makedirs(TEMP_PDF_DIR)

def obtener_url_pdf(file_path):
    file_name = os.path.basename(file_path)
    return f"https://serigraph.onrender.com/temp_pdfs/{file_name}"

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
            # os.remove(file_path)
            print(f"Archivo eliminado: {file_path}")

@app.route("/temp_pdfs/<path:filename>")
def descargar_pdf(filename):
    """Sirve los archivos PDF almacenados en la carpeta temp_pdfs."""
    return send_from_directory(TEMP_PDF_DIR, filename, as_attachment=True)

@app.route("/webhook", methods=["POST"])
def webhook():
    global user_data

    incoming_message = request.form.get("Body", "").lower()
    user_number = request.form.get("From", "")

    response_message = ""
    twiml = MessagingResponse()
    print(incoming_message)
    if "hola" in incoming_message:
        response_message = (
            "¡Hola! Bienvenido al cotizador de Serigraph. "
            "Por favor, elige una opción:\n\n"
            "1. Cotización\n"
        )
        user_data[user_number] = {"step": "menu"}  

    elif user_number in user_data:
        if user_data[user_number]["step"] == "menu":
            if "1" in incoming_message:

                texto = "Has seleccionado el servicio de cotización \n. Ahora, elige el producto:\n"
                for i, producto in enumerate(diccionario_productos, start=1):
                    texto += f"{i}. {producto}\n"
                    
                print(texto)
                response_message = (
                    texto
                )
                user_data[user_number] = {"step": "productos", "service": "cotizacion"}
        
        elif user_data[user_number]["step"]=="productos":
            producto_selected=incoming_message
            if int(producto_selected)<=len(diccionario_productos):
                for i,producto in enumerate(diccionario_productos,start=1):
                    if i==int(producto_selected):
                        product=producto
                        price=diccionario_productos[producto]
                user_data[user_number] = {"step": "dimensiones", "service": "cotizacion","product":[product,price]}
                text_dimen = f"Has seleccionado {product} que tiene un precio de Q{price} \n. Ahora, elige el tamaño:\n"
                for i, dimen in enumerate(diccionario_dimensiones, start=1):
                    text_dimen += f"{i}. {dimen}\n"
                text_dimen+="Ó ingrese 0 si quiere ingresar un tamaño variable (Ej: 20x10) en cm"
                response_message=(text_dimen)
        elif user_data[user_number]["step"] == "dimensiones":
            dim_selected=incoming_message
            if int(dim_selected)<=len(diccionario_dimensiones):
                if dim_selected==0:
                    user_data[user_number]['step'] = "dimension_specific"
                    response_message("Por favor, ingresa el ancho y alto en centímetros y el precio de dicho tamaño (ejemplo: '20x30 10.0').")
                else:
                    for i,dimens in enumerate(diccionario_dimensiones,start=1):
                        if i==int(dim_selected):
                            dim=dimens
                            price_dim=diccionario_dimensiones[dimens]

                    text_mat = f"Has ingresado un tamaño de {dim} cm con un precio de Q{price_dim}.\n"
                    text_mat+="Ahora, elige el material:\n"
                    for i, mat in enumerate(diccionario_material, start=1):
                        text_mat += f"{i}. {mat}\n"
                    response_message = (text_mat)
                    user_data[user_number]['step'] = "material"
                    user_data[user_number]['dimensiones']=[dim,price_dim]
        elif user_data[user_number]["step"] == "dimension_specific":
            user_data[user_number]['step'] = "impresion"
        elif user_data[user_number]["step"] == "impresion":
            try:
                ancho, alto = incoming_message.split("x")
                alto,precio=alto.split(" ")
                # response_message = (
                    
                #     "Ahora, elige el material:\n"
                #     "1. Papel couché\n"
                #     "2. Vinil adhesivo\n"
                #     "3. Lona"
                # )
                text_mat = f"Has ingresado un tamaño de {ancho}x{alto} cm con un precio de Q{precio}.\n"
                text_mat+="Ahora, elige el material:\n"
                for i, mat in enumerate(diccionario_material, start=1):
                    text_mat += f"{i}. {mat}\n"
                response_message = (text_mat)
                anchoxalto=str(ancho)+"x"+str(alto)
                cursor.execute("INSERT INTO dimensions_volante (dimension, price) VALUES (?, ?)", (anchoxalto, precio))

                # Guarda los cambios en la base de datos
                conn.commit()
                user_data[user_number]['dimensiones']=[anchoxalto,price_dim]
                user_data[user_number]["step"]="seleccion_material"
            except:
                response_message = "Formato incorrecto. Por favor, ingresa el ancho y alto en formato 'anchoxalto precio'."

        elif user_data[user_number]["step"] == "seleccion_material":
            
            if incoming_message in materiales:
                user_data[user_number]["material"] = [materiales[incoming_message],diccionario_material[materiales[incoming_message]]]
                response_message = (
                    f"Seleccionaste {materiales[incoming_message]}.\n"
                    f"Ahora, ingresa la cantidad de {user_data[user_number]['product'][0]} que deseas cotizar."
                )
                user_data[user_number]["step"] = "seleccion_cantidad"
            else:
                response_message = "Opción no válida. Por favor, elige 1, 2 o 3."

        elif user_data[user_number]["step"] == "seleccion_cantidad":
            if incoming_message.isdigit():
                user_data[user_number]["cantidad"] = int(incoming_message)
                response_message = (
                    f"Perfecto. Has solicitado {user_data[user_number]['cantidad']} {user_data[user_number]['product'][0]} en "
                    f"{user_data[user_number]['material']} de tamaño {user_data[user_number]['dimensiones'][0]}.\n"
                    "¿Confirmas? (Responde 'sí' o 'no')."
                )
                user_data[user_number]["step"] = "confirmacion_final"
            else:
                response_message = "Por favor, ingresa un número válido."

        elif user_data[user_number]["step"] == "confirmacion_final":
            if "sí" in incoming_message:
                precios = {"Papel couché": 0.50, "Vinil adhesivo": 1.00, "Lona": 2.00}
                costo_total = (int(user_data[user_number]['dimensiones'][1])+int(user_data[user_number]['product'][1])+int(user_data[user_number]['material'][1]))*user_data[user_number]['cantidad']

                # Generar el PDF
                file_path = generar_pdf(
                    user_number, user_data[user_number]["material"], 
                    user_data[user_number]['dimensiones'][0], 
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
