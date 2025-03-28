import os
from flask import Flask, request, send_from_directory
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import sqlite3
import time

load_dotenv()
app = Flask(__name__)

# Base de datos
conn = sqlite3.connect('/var/www/db_serigraph/seri.db', check_same_thread=False)
cursor = conn.cursor()

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
bot = Bot(token=TOKEN)

dispatcher = Dispatcher(bot, None, workers=0)

user_data = {}

TEMP_PDF_DIR = "temp_pdfs"
if not os.path.exists(TEMP_PDF_DIR):
    os.makedirs(TEMP_PDF_DIR)

def formato_monetario(valor):
    return f"Q{valor:,.2f}"


def generar_pdf(numero_usuario, material, dimensiones, cantidad, costo_total, user_number, descripcion_producto):
    file_name = f"cotizacion_{numero_usuario}_{int(time.time())}.pdf"
    file_path = os.path.join(TEMP_PDF_DIR, file_name)

    c = canvas.Canvas(file_path, pagesize=letter)

    # Inserta la imagen del logo correctamente (ajusta tamaño y posición según tu logo real)
    logo = ImageReader('/var/www/db_serigraph/seri.png')
    c.drawImage(logo, 50, 720, width=120, height=70, preserveAspectRatio=True)

    # Datos de la empresa (alineación más precisa)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(200, 770, "Serigráfica Internacional, S.A.")
    c.setFont("Helvetica", 10)
    c.drawString(200, 755, "10 avenida 25-63 zona 13, Complejo Industrial Aurora Bodega 13")
    c.drawString(200, 740, "Tel: (502) 2319-2900")
    c.drawString(200, 725, "NIT: 528440-6")

    # Número de cotización y fecha (bien alineados)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(430, 770, f"Cotización No. {int(time.time())%100000}")
    c.setFont("Helvetica", 10)
    c.drawString(430, 755, f"Fecha: {time.strftime('%d/%m/%Y')}")

    # Línea divisoria superior
    c.line(50, 710, 560, 710)

    # Dirigido a (ajuste en posición)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, 690, f"Dirigido a: {numero_usuario}")

    # Información adicional (mejor espaciado)
    c.setFont("Helvetica", 9)
    texto_info = (
        "El tiempo de entrega es de 5 días hábiles, desde la aprobación del proyecto y arte.\n"
        "Si el proyecto está antes, se le notificará.\n"
        "El pago es contra entrega, salvo acuerdo contrario.\n"
        "Si cuenta con el diseño de impresión, envíelo a: jjdahud@gmail.com\n\n"
        "Gracias por contactar a Serigráfica Internacional\n\n"
        "Att: José David\n"
        "Gerente General"
    )
    text_object = c.beginText(50, 660)
    text_object.setLeading(13)  # Espaciado entre líneas más legible
    for linea in texto_info.split("\n"):
        text_object.textLine(linea)
    c.drawText(text_object)

    # Tabla de producto y precios (claramente dividida y alineada)
    c.rect(50, 480, 500, 80, stroke=True, fill=False)

    # Encabezados
    c.setFont("Helvetica-Bold", 10)
    c.drawString(60, 545, "CANTIDAD")
    c.drawString(150, 545, "DESCRIPCIÓN")
    c.drawString(480, 545, "TOTAL")

    # Línea separadora bajo encabezado
    c.line(50, 540, 550, 540)

    # Contenido (mejor espaciado y formato monetario adecuado)
    c.setFont("Helvetica", 10)
    c.drawString(60, 520, f"{cantidad} UNIDADES")
    c.drawString(150, 520, descripcion_producto.upper())
    c.drawRightString(540, 520, formato_monetario(costo_total))

    # Total final claramente resaltado y alineado a la derecha
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(540, 460, f"TOTAL: {formato_monetario(costo_total)}")

    c.save()

    return file_path

@app.route('/temp_pdfs/<path:filename>')
def descargar_pdf(filename):
    return send_from_directory(TEMP_PDF_DIR, filename, as_attachment=True)

# Mensajes de Telegram
def telegram_webhook(update: Update, context):
    user_number = update.message.chat.id
    incoming_message = update.message.text.lower()
    # Carga diccionarios (igual que en tu código original)
    diccionario_productos = {fila[1]: fila[2] for fila in cursor.execute("SELECT * FROM products;")}
    diccionario_dimensiones = {fila[1]: fila[2] for fila in cursor.execute("SELECT * FROM dimensions_volante;")}
    diccionario_material = {fila[1]: fila[2] for fila in cursor.execute("SELECT * FROM material;")}
    materiales = {i+1: fila[1] for i, fila in enumerate(cursor.execute("SELECT * FROM material;"))}

    if "hola" in incoming_message:
        response_message = "¡Hola! Bienvenido al cotizador de Serigraph.\n1. Cotización"
        user_data[user_number] = {"step": "menu"}

    elif user_number in user_data:
        step = user_data[user_number]["step"]
        response_message = "No te entendí. Intenta de nuevo."

        if step == "menu" and "1" in incoming_message:
            texto = "Selecciona el producto:\n"
            texto += "\n".join([f"{i}. {prod}" for i, prod in enumerate(diccionario_productos, 1)])
            response_message = texto
            user_data[user_number]["step"] = "productos"

        elif step == "productos":
            seleccionado = int(incoming_message)
            producto = list(diccionario_productos.keys())[seleccionado - 1]
            precio = diccionario_productos[producto]

            texto = f"{producto} - Q{precio}\nElige tamaño:\n"
            texto += "\n".join([f"{i}. {dim}" for i, dim in enumerate(diccionario_dimensiones, 1)])
            texto += "\n0. Otro tamaño (Ej: 20x10 15.0)"

            response_message = texto
            user_data[user_number].update({"step": "dimensiones", "product": [producto, precio]})

        elif step == "dimensiones":
            seleccionado = incoming_message
            if seleccionado == "0":
                response_message = "Ingresa 'anchoxalto precio' (ej: 20x10 15.0):"
                user_data[user_number]["step"] = "dimension_specific"
            else:
                dim = list(diccionario_dimensiones.keys())[int(seleccionado) - 1]
                precio_dim = diccionario_dimensiones[dim]

                texto = f"Tamaño: {dim} - Q{precio_dim}\nSelecciona material:\n"
                texto += "\n".join([f"{i}. {mat}" for i, mat in materiales.items()])
                response_message = texto
                user_data[user_number].update({"step": "material", "dimensiones": [dim, precio_dim]})

        elif step == "dimension_specific":
            ancho_alto, precio_dim = incoming_message.split("x")
            cursor.execute("INSERT INTO dimensions_volante (dimension, price) VALUES (?, ?)", (ancho_alto, precio_dim))
            conn.commit()

            texto = f"Tamaño: {ancho_alto} - Q{precio_dim}\nSelecciona material:\n"
            texto += "\n".join([f"{i}. {mat}" for i, mat in materiales.items()])
            response_message = texto
            user_data[user_number].update({"step": "material", "dimensiones": [ancho_alto, precio_dim]})

        elif step == "material":
            material = materiales[int(incoming_message)]
            precio_mat = diccionario_material[material]
            response_message = f"Material: {material}\n¿Cuántas unidades deseas cotizar?"
            user_data[user_number].update({"step": "cantidad", "material": [material, precio_mat]})

        elif step == "cantidad":
            cantidad = int(incoming_message)
            user_data[user_number]["cantidad"] = cantidad
            response_message = "Confirma tu pedido respondiendo 'si' o 'no'."
            user_data[user_number]["step"] = "confirmacion"

        elif step == "confirmacion":
            if "si" in incoming_message:
                costo_total = (float(user_data[user_number]['dimensiones'][1]) + float(user_data[user_number]['product'][1]) + float(user_data[user_number]['material'][1])) * user_data[user_number]['cantidad']
                file_path = generar_pdf(user_number, user_data[user_number]["material"][0], user_data[user_number]['dimensiones'][0], user_data[user_number]["cantidad"], costo_total, user_number,descripcion_producto=f"{user_data[user_number]['product'][0]}, {user_data[user_number]['dimensiones'][0]}, {user_data[user_number]['material'][0]}")
                
                context.bot.send_document(chat_id=user_number, document=open(file_path, 'rb'), filename=os.path.basename(file_path))
                response_message = "¡Cotización generada!"
                del user_data[user_number]
            else:
                response_message = "Cotización cancelada."
                del user_data[user_number]

    else:
        response_message = "Envía 'hola' para comenzar."

    update.message.reply_text(response_message)

dispatcher.add_handler(MessageHandler(Filters.text, telegram_webhook))

@app.route(f"/{TOKEN}", methods=['POST'])
def webhook_telegram():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return 'ok'

if __name__ == "__main__":
    app.run(debug=True)
