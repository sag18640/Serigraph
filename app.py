import os
import math
import time
from flask import Flask, request, send_from_directory
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Dispatcher, MessageHandler, Filters
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import sqlite3

load_dotenv()
app = Flask(__name__)

# Conexión a la base de datos (se asume que las tablas "products", "dimensions_volante" y "material" existen)
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

def generar_pdf(client_name, material, flyer_width, cantidad, costo_total, descripcion_producto):
    """
    Genera un PDF de cotización con información esencial:
      - Nombre del cliente
      - Producto, formato y material
      - Cantidad cotizada y costo final
      - Datos de la empresa
    """
    file_name = f"cotizacion_{client_name}_{int(time.time())}.pdf"
    file_path = os.path.join(TEMP_PDF_DIR, file_name)
    c = canvas.Canvas(file_path, pagesize=letter)

    # Logo y datos de la empresa
    logo = ImageReader('/var/www/db_serigraph/seri.png')
    c.drawImage(logo, 50, 720, width=120, height=70, preserveAspectRatio=True)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(200, 770, "Serigráfica Internacional, S.A.")
    c.setFont("Helvetica", 10)
    c.drawString(200, 755, "10 avenida 25-63 zona 13, Complejo Industrial Aurora Bodega 13")
    c.drawString(200, 740, "Tel: (502) 2319-2900")
    c.drawString(200, 725, "NIT: 528440-6")
    c.setFont("Helvetica-Bold", 11)
    c.drawString(430, 770, f"Cotización No. {int(time.time())%100000}")
    c.setFont("Helvetica", 10)
    c.drawString(430, 725, f"Fecha: {time.strftime('%d/%m/%Y')}")
    c.line(50, 710, 560, 710)

    # Datos del cliente y del producto
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, 690, f"Cliente: {client_name}")
    c.setFont("Helvetica", 10)
    c.drawString(50, 670, f"Producto: {descripcion_producto}")
    c.drawString(50, 650, f"Cantidad: {cantidad} unidades")
    c.drawString(50, 630, f"Costo final: {formato_monetario(costo_total)}")

    # Mensaje final
    c.setFont("Helvetica", 9)
    text_object = c.beginText(50, 600)
    text_object.setLeading(13)
    mensaje = (
        "El tiempo de entrega es de 5 días hábiles desde la aprobación del proyecto.\n"
        "El pago es contra entrega, salvo acuerdo previo.\n"
        "Envía tu diseño a: jjdahud@gmail.com\n\n"
        "Gracias por confiar en Serigráfica Internacional"
    )
    for linea in mensaje.split("\n"):
        text_object.textLine(linea)
    c.drawText(text_object)

    c.save()
    return file_path

# El webhook maneja cada mensaje, realizando las consultas a la DB para tener información actualizada
def telegram_webhook(update: Update, context):
    user_number = update.message.chat.id
    incoming_message = update.message.text.strip()

    # Se realizan las consultas en cada llamada para contar con datos actualizados
    cursor.execute("SELECT * FROM products;")
    products = cursor.fetchall()
    diccionario_productos = {fila[1]: fila[2] for fila in products}

    cursor.execute("SELECT * FROM dimensions_volante;")
    dimensions = cursor.fetchall()
    diccionario_dimensiones = {fila[1]: fila[2] for fila in dimensions}

    cursor.execute("SELECT * FROM material;")
    materials = cursor.fetchall()
    diccionario_material = {fila[1]: (fila[2], fila[3]) for fila in materials}
    materiales = {i+1: fila[1] for i, fila in enumerate(materials)}

    # Flujo de conversación
    if incoming_message.lower() == "hola":
        response_message = "¡Hola! Por favor ingresa tu nombre de cliente:"
        user_data[user_number] = {"step": "ask_nombre"}
    elif user_number in user_data:
        step = user_data[user_number]["step"]
        if step == "ask_nombre":
            client_name = incoming_message.strip()
            user_data[user_number]["client_name"] = client_name
            response_message = f"Bienvenido {client_name}.\n1. Cotización"
            user_data[user_number]["step"] = "menu"
        elif step == "menu":
            if incoming_message == "1":
                # Se muestran los productos actuales y se da opción de agregar uno nuevo
                texto = "Selecciona el producto:\n"
                texto += "0. Agregar nuevo producto\n"
                texto += "\n".join([f"{i+1}. {prod}" for i, prod in enumerate(diccionario_productos.keys())])
                response_message = texto
                user_data[user_number]["step"] = "productos"
            else:
                response_message = "Opción no válida. Envía '1' para Cotización."
        elif step == "productos":
            try:
                opcion = int(incoming_message)
            except:
                response_message = "Ingresa una opción válida."
                return update.message.reply_text(response_message)
            if opcion == 0:
                response_message = "Ingresa el nombre del nuevo producto y su precio separados por un espacio (Ej: producto 15.0):"
                user_data[user_number]["step"] = "nuevo_producto"
            else:
                product_keys = list(diccionario_productos.keys())
                if opcion > len(product_keys):
                    response_message = "Producto no válido."
                else:
                    producto = product_keys[opcion - 1]
                    precio_producto = diccionario_productos[producto]
                    user_data[user_number]["product"] = (producto, precio_producto)
                    response_message = ("Selecciona el formato:\n"
                                        "1. Carta (8.5x11)\n"
                                        "2. Oficio (8.5x13)\n"
                                        "3. Media Carta (8.5x5.5)\n"
                                        "4. Medio Oficio (8.5x6.5)\n"
                                        "5. Otro")
                    user_data[user_number]["step"] = "formato"
        elif step == "nuevo_producto":
            try:
                parts = incoming_message.split()
                new_product_name = " ".join(parts[:-1])
                new_product_price = float(parts[-1])
                cursor.execute("INSERT INTO products (product, price) VALUES (?, ?)", (new_product_name, new_product_price))
                conn.commit()
                response_message = f"Producto '{new_product_name}' agregado con éxito.\nSelecciona el producto:\n"
                # Se vuelve a listar los productos actualizados
                cursor.execute("SELECT * FROM products;")
                products = cursor.fetchall()
                diccionario_productos = {fila[1]: fila[2] for fila in products}
                texto = "0. Agregar nuevo producto\n"
                texto += "\n".join([f"{i+1}. {prod}" for i, prod in enumerate(diccionario_productos.keys())])
                response_message += texto
                user_data[user_number]["step"] = "productos"
            except Exception as e:
                response_message = "Error al agregar producto. Asegúrate de ingresar el nombre y precio (Ej: producto 15.0)."
        elif step == "formato":
            try:
                opcion = int(incoming_message)
            except:
                response_message = "Ingresa una opción válida (1-5)."
                return update.message.reply_text(response_message)
            if opcion == 1:
                formato = ("Carta", 8.5, 11)
            elif opcion == 2:
                formato = ("Oficio", 8.5, 13)
            elif opcion == 3:
                formato = ("Media Carta", 8.5, 5.5)
            elif opcion == 4:
                formato = ("Medio Oficio", 8.5, 6.5)
            elif opcion == 5:
                response_message = "Ingresa las dimensiones en formato anchoxalto (Ej: 20x10):"
                user_data[user_number]["step"] = "formato_personalizado"
                return update.message.reply_text(response_message)
            else:
                response_message = "Opción no válida."
                return update.message.reply_text(response_message)
            user_data[user_number]["formato"] = formato
            texto = f"Formato seleccionado: {formato[0]} ({formato[1]}x{formato[2]})\nSelecciona material:\n"
            texto += "\n".join([f"{i}. {mat}" for i, mat in materiales.items()])
            response_message = texto
            user_data[user_number]["step"] = "material"
        elif step == "formato_personalizado":
            try:
                ancho, alto = incoming_message.lower().split("x")
                formato = ("Personalizado", float(ancho), float(alto))
                user_data[user_number]["formato"] = formato
                texto = f"Formato seleccionado: Personalizado ({formato[1]}x{formato[2]})\nSelecciona material:\n"
                texto += "\n".join([f"{i}. {mat}" for i, mat in materiales.items()])
                response_message = texto
                user_data[user_number]["step"] = "material"
            except Exception as e:
                response_message = "Formato incorrecto. Intenta nuevamente, ej: 20x10"
        elif step == "material":
            try:
                material = materiales[int(incoming_message)]
            except Exception as e:
                response_message = "Selecciona un material válido."
                return update.message.reply_text(response_message)
            if material in diccionario_material:
                precio_mat, medida_mat = diccionario_material[material]
            else:
                precio_mat, medida_mat = (0, "0x0")
            user_data[user_number]["material"] = (material, precio_mat, medida_mat)
            response_message = "¿Cuántos volantes deseas cotizar?"
            user_data[user_number]["step"] = "cantidad"
        elif step == "cantidad":
            try:
                cantidad = int(incoming_message)
                user_data[user_number]["cantidad"] = cantidad
                response_message = "¿Es impresión digital? (si/no):"
                user_data[user_number]["step"] = "digital"
            except:
                response_message = "Ingresa una cantidad válida."
        elif step == "digital":
            if incoming_message.lower() in ["si", "sí"]:
                user_data[user_number]["digital"] = True
                response_message = "Ingresa el costo total de impresión digital:"
                user_data[user_number]["step"] = "digital_cost"
            elif incoming_message.lower() == "no":
                user_data[user_number]["digital"] = False
                user_data[user_number]["digital_cost"] = 0.0
                response_message = ("Ingresa los siguientes costos adicionales separados por espacio:\n"
                                    "Costo de máquina, costo de tinta, costo de laminado, costo de placas, costo de cortes, costo de empaque, costo de laminado extra, costo de goma\n"
                                    "Ej: 100 50 30 20 10 5 3 2")
                user_data[user_number]["step"] = "costos_adicionales"
            else:
                response_message = "Respuesta no válida, ingresa 'si' o 'no'."
        elif step == "digital_cost":
            try:
                digital_cost = float(incoming_message)
                user_data[user_number]["digital_cost"] = digital_cost
                response_message = ("Ingresa los siguientes costos adicionales separados por espacio:\n"
                                    "Costo de máquina, costo de tinta, costo de laminado, costo de placas, costo de cortes, costo de empaque, costo de laminado extra, costo de goma\n"
                                    "Ej: 100 50 30 20 10 5 3 2")
                user_data[user_number]["step"] = "costos_adicionales"
            except:
                response_message = "Ingresa un valor numérico para el costo digital."
        elif step == "costos_adicionales":
            try:
                parts = incoming_message.split()
                if len(parts) != 8:
                    response_message = "Por favor ingresa 8 valores separados por espacio."
                else:
                    machine_cost = float(parts[0])
                    ink_cost = float(parts[1])
                    lamination_cost = float(parts[2])
                    plate_cost = float(parts[3])
                    cortes_cost = float(parts[4])
                    empaque_cost = float(parts[5])
                    extra_laminado_cost = float(parts[6])
                    goma_cost = float(parts[7])
                    user_data[user_number]["costos_adicionales"] = {
                        "machine": machine_cost,
                        "ink": ink_cost,
                        "lamination": lamination_cost,
                        "plate": plate_cost,
                        "cortes": cortes_cost,
                        "empaque": empaque_cost,
                        "extra_laminado": extra_laminado_cost,
                        "goma": goma_cost,
                    }
                    response_message = "Confirma tu pedido respondiendo 'si' o 'no'."
                    user_data[user_number]["step"] = "confirmacion"
            except Exception as e:
                response_message = "Error al procesar los costos adicionales. Asegúrate de ingresar 8 valores numéricos separados por espacio."
        elif step == "confirmacion":
            if "si" in incoming_message.lower():
                cantidad = user_data[user_number]["cantidad"]
                formato = user_data[user_number]["formato"]
                flyer_area = formato[1] * formato[2]
                material, mat_price, mat_medida = user_data[user_number]["material"]
                try:
                    mat_dims = mat_medida.split("x")
                    mat_width = float(mat_dims[0])
                    mat_height = float(mat_dims[1])
                except:
                    mat_width, mat_height = (0, 0)
                material_area = mat_width * mat_height
                flyers_per_sheet = max(math.floor(material_area / flyer_area) - 1, 1)
                required_sheets = math.ceil(cantidad / flyers_per_sheet) + 2
                cost_per_sheet = mat_price / 500.0
                paper_cost = required_sheets * cost_per_sheet
                costos = user_data[user_number]["costos_adicionales"]
                digital_cost = user_data[user_number].get("digital_cost", 0.0)
                additional_costs = (costos["machine"] + costos["ink"] + costos["lamination"] +
                                    digital_cost + costos["plate"] + costos["cortes"] +
                                    costos["empaque"] + costos["extra_laminado"] + costos["goma"])
                total_cost = paper_cost + additional_costs
                final_cost = (total_cost * 1.5) * 1.17
                client_name = user_data[user_number].get("client_name", "Cliente")
                descripcion_producto = f"{user_data[user_number]['product'][0]}, Formato: {formato[0]}, Material: {user_data[user_number]['material'][0]}"
                
                # Se genera el PDF con datos esenciales: cliente, producto, cantidad y costo final
                file_path = generar_pdf(client_name, user_data[user_number]["material"][0], formato[1], cantidad, final_cost, descripcion_producto)
                context.bot.send_document(chat_id=user_number, document=open(file_path, 'rb'), filename=os.path.basename(file_path))
                response_message = "¡Cotización generada!"
                del user_data[user_number]
            else:
                response_message = "Cotización cancelada."
                del user_data[user_number]
        else:
            response_message = "No te entendí. Intenta de nuevo."
    else:
        response_message = "Envía 'hola' para comenzar."
    update.message.reply_text(response_message)

dispatcher.add_handler(MessageHandler(Filters.text, telegram_webhook))

@app.route(f"/{TOKEN}", methods=['POST'])
def webhook_telegram():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return 'ok'

@app.route('/temp_pdfs/<path:filename>')
def descargar_pdf(filename):
    return send_from_directory(TEMP_PDF_DIR, filename, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)
