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
      - Producto, tamaño y material
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

# El webhook se encarga de manejar cada mensaje consultando la DB en cada llamada para tener datos actualizados.
def telegram_webhook(update: Update, context):
    user_number = update.message.chat.id
    incoming_message = update.message.text.strip()

    # Consultas actualizadas
    cursor.execute("SELECT * FROM products;")
    products = cursor.fetchall()
    diccionario_productos = {fila[1]: fila[2] for fila in products}

    cursor.execute("SELECT * FROM dimensions_volante;")
    dimensions = cursor.fetchall()
    diccionario_dimensiones = {fila[1]: fila[2] for fila in dimensions}  # Ejemplo: "8.5x11": precio

    cursor.execute("SELECT * FROM material;")
    materials = cursor.fetchall()
    diccionario_material = {fila[1]: (fila[2], fila[3]) for fila in materials}
    materiales = {i+1: fila[1] for i, fila in enumerate(materials)}

    # Flujo de conversación
    if incoming_message.lower() == "hola":
        response_message = "¡Hola! Ingresa tu nombre de cliente:"
        user_data[user_number] = {"step": "ask_nombre"}
    elif user_number in user_data:
        step = user_data[user_number]["step"]
        if step == "ask_nombre":
            client_name = incoming_message.strip()
            user_data[user_number]["client_name"] = client_name
            response_message = "Bienvenido\n1. Cotización"
            user_data[user_number]["step"] = "menu"
        elif step == "menu":
            if incoming_message == "1":
                # Lista de productos con opción de agregar uno nuevo
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
                response_message = "Ingresa el nombre del nuevo producto:"
                user_data[user_number]["step"] = "nuevo_producto"
            else:
                product_keys = list(diccionario_productos.keys())
                if opcion > len(product_keys):
                    response_message = "Producto no válido."
                else:
                    producto = product_keys[opcion - 1]
                    precio_producto = diccionario_productos[producto]
                    user_data[user_number]["product"] = (producto, precio_producto)
                    # Se muestran los tamaños disponibles desde la DB
                    texto = f"{producto} - Q{precio_producto}\nElige tamaño:\n"
                    texto += "0. Agregar nuevo tamaño (Ej: 20x10)\n"
                    texto += "\n".join([f"{i+1}. {dim}" for i, dim in enumerate(diccionario_dimensiones.keys())])
                    response_message = texto
                    user_data[user_number]["step"] = "dimensiones"
        elif step == "nuevo_producto":
            new_product_name = incoming_message.strip()
            cursor.execute("INSERT INTO products (product, price) VALUES (?, ?)", (new_product_name, 0.0))
            conn.commit()
            response_message = f"Producto '{new_product_name}' agregado con éxito.\nSelecciona el producto:\n"
            cursor.execute("SELECT * FROM products;")
            products = cursor.fetchall()
            diccionario_productos = {fila[1]: fila[2] for fila in products}
            texto = "0. Agregar nuevo producto\n"
            texto += "\n".join([f"{i+1}. {prod}" for i, prod in enumerate(diccionario_productos.keys())])
            response_message += texto
            user_data[user_number]["step"] = "productos"
        elif step == "dimensiones":
            try:
                opcion = incoming_message.strip()
                if opcion == "0":
                    response_message = "Ingresa el tamaño en formato anchoxalto (Ej: 20x10):"
                    user_data[user_number]["step"] = "dimension_specific"
                    return update.message.reply_text(response_message)
                else:
                    opcion_int = int(opcion)
                    dims_list = list(diccionario_dimensiones.keys())
                    if opcion_int > len(dims_list):
                        response_message = "Tamaño no válido."
                    else:
                        dim = dims_list[opcion_int - 1]
                        precio_dim = diccionario_dimensiones[dim]
                        texto = f"Tamaño: {dim} - Q{precio_dim}\nSelecciona material:\n"
                        texto += "\n".join([f"{i}. {mat}" for i, mat in materiales.items()])
                        response_message = texto
                        user_data[user_number].update({"step": "material", "dimensiones": (dim, precio_dim)})
            except Exception as e:
                response_message = "Error, ingresa un tamaño válido."
        elif step == "dimension_specific":
            try:
                # Se espera solo la dimensión, sin precio
                dim_str = incoming_message.strip()
                cursor.execute("INSERT INTO dimensions_volante (dimension, price) VALUES (?, ?)", (dim_str, 0.0))
                conn.commit()
                texto = f"Tamaño: {dim_str} - Q0.0\nSelecciona material:\n"
                texto += "\n".join([f"{i}. {mat}" for i, mat in materiales.items()])
                response_message = texto
                user_data[user_number].update({"step": "material", "dimensiones": (dim_str, 0.0)})
            except Exception as e:
                response_message = "Error al procesar el tamaño. Usa el formato (Ej: 20x10)."
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
                # Para digital, solo se piden costo de máquina y costo de clicks
                response_message = "Ingresa el costo de máquina:"
                user_data[user_number]["step"] = "digital_costo_maquina"
            elif incoming_message.lower() == "no":
                user_data[user_number]["digital"] = False
                user_data[user_number]["digital_clicks"] = 0.0
                response_message = "Ingresa el costo de máquina:"
                user_data[user_number]["step"] = "costo_maquina"
            else:
                response_message = "Respuesta no válida, ingresa 'si' o 'no'."
        elif step == "digital_costo_maquina":
            try:
                machine_cost = float(incoming_message)
                if "costos" not in user_data[user_number]:
                    user_data[user_number]["costos"] = {}
                user_data[user_number]["costos"]["machine"] = machine_cost
                response_message = "Ingresa el costo de clicks:"
                user_data[user_number]["step"] = "digital_costo_clicks"
            except:
                response_message = "Ingresa un valor numérico para el costo de máquina."
        elif step == "digital_costo_clicks":
            try:
                digital_clicks = float(incoming_message)
                user_data[user_number]["digital_clicks"] = digital_clicks
                response_message = "Confirma tu pedido respondiendo 'si' o 'no'."
                user_data[user_number]["step"] = "confirmacion"
            except:
                response_message = "Ingresa un valor numérico para el costo de clicks."
        # Cadena de costos para modo no digital
        elif step == "costo_maquina":
            try:
                machine_cost = float(incoming_message)
                if "costos" not in user_data[user_number]:
                    user_data[user_number]["costos"] = {}
                user_data[user_number]["costos"]["machine"] = machine_cost
                response_message = "Ingresa el costo de tinta:"
                user_data[user_number]["step"] = "costo_tinta"
            except:
                response_message = "Ingresa un valor numérico para el costo de máquina."
        elif step == "costo_tinta":
            try:
                tinta_cost = float(incoming_message)
                user_data[user_number]["costos"]["ink"] = tinta_cost
                response_message = "Ingresa el costo de laminado:"
                user_data[user_number]["step"] = "costo_laminado"
            except:
                response_message = "Ingresa un valor numérico para el costo de tinta."
        elif step == "costo_laminado":
            try:
                laminado_cost = float(incoming_message)
                user_data[user_number]["costos"]["lamination"] = laminado_cost
                response_message = "Ingresa el costo de placas:"
                user_data[user_number]["step"] = "costo_placas"
            except:
                response_message = "Ingresa un valor numérico para el costo de laminado."
        elif step == "costo_placas":
            try:
                placas_cost = float(incoming_message)
                user_data[user_number]["costos"]["plate"] = placas_cost
                response_message = "Ingresa el costo de cortes:"
                user_data[user_number]["step"] = "costo_cortes"
            except:
                response_message = "Ingresa un valor numérico para el costo de placas."
        elif step == "costo_cortes":
            try:
                cortes_cost = float(incoming_message)
                user_data[user_number]["costos"]["cortes"] = cortes_cost
                response_message = "Ingresa el costo de empaque:"
                user_data[user_number]["step"] = "costo_empaque"
            except:
                response_message = "Ingresa un valor numérico para el costo de cortes."
        elif step == "costo_empaque":
            try:
                empaque_cost = float(incoming_message)
                user_data[user_number]["costos"]["empaque"] = empaque_cost
                response_message = "Ingresa el costo de laminado extra:"
                user_data[user_number]["step"] = "costo_extra_laminado"
            except:
                response_message = "Ingresa un valor numérico para el costo de empaque."
        elif step == "costo_extra_laminado":
            try:
                extra_laminado_cost = float(incoming_message)
                user_data[user_number]["costos"]["extra_laminado"] = extra_laminado_cost
                response_message = "Ingresa el costo de goma:"
                user_data[user_number]["step"] = "costo_goma"
            except:
                response_message = "Ingresa un valor numérico para el costo de laminado extra."
        elif step == "costo_goma":
            try:
                goma_cost = float(incoming_message)
                user_data[user_number]["costos"]["goma"] = goma_cost
                response_message = "Ingresa el costo de doblado:"
                user_data[user_number]["step"] = "costo_doblado"
            except:
                response_message = "Ingresa un valor numérico para el costo de goma."
        elif step == "costo_doblado":
            try:
                doblado_cost = float(incoming_message)
                user_data[user_number]["costos"]["doblado"] = doblado_cost
                response_message = "Ingresa el costo de troquelada:"
                user_data[user_number]["step"] = "costo_troquelada"
            except:
                response_message = "Ingresa un valor numérico para el costo de doblado."
        elif step == "costo_troquelada":
            try:
                troquelada_cost = float(incoming_message)
                user_data[user_number]["costos"]["troquelada"] = troquelada_cost
                response_message = "Ingresa el costo de encapsulado:"
                user_data[user_number]["step"] = "costo_encapsulado"
            except:
                response_message = "Ingresa un valor numérico para el costo de troquelada."
        elif step == "costo_encapsulado":
            try:
                encapsulado_cost = float(incoming_message)
                user_data[user_number]["costos"]["encapsulado"] = encapsulado_cost
                response_message = "Ingresa el costo de pegado:"
                user_data[user_number]["step"] = "costo_pegado"
            except:
                response_message = "Ingresa un valor numérico para el costo de encapsulado."
        elif step == "costo_pegado":
            try:
                pegado_cost = float(incoming_message)
                user_data[user_number]["costos"]["pegado"] = pegado_cost
                response_message = "Ingresa el costo de barniz:"
                user_data[user_number]["step"] = "costo_barniz"
            except:
                response_message = "Ingresa un valor numérico para el costo de pegado."
        elif step == "costo_barniz":
            try:
                barniz_cost = float(incoming_message)
                user_data[user_number]["costos"]["barniz"] = barniz_cost
                response_message = "Confirma tu pedido respondiendo 'si' o 'no'."
                user_data[user_number]["step"] = "confirmacion"
            except:
                response_message = "Ingresa un valor numérico para el costo de barniz."
        elif step == "confirmacion":
            if "si" in incoming_message.lower():
                cantidad = user_data[user_number]["cantidad"]
                # Se procesa el tamaño (dimensión) seleccionado desde la DB
                dim_str, precio_dim = user_data[user_number]["dimensiones"]
                try:
                    flyer_dimensions = dim_str.lower().split("x")
                    flyer_width = float(flyer_dimensions[0])
                    flyer_height = float(flyer_dimensions[1])
                except:
                    flyer_width, flyer_height = (0, 0)
                flyer_area = flyer_width * flyer_height

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

                # Si es digital, solo se suman el costo de máquina y el de clicks.
                if user_data[user_number].get("digital", False):
                    costos = user_data[user_number].get("costos", {})
                    digital_clicks = user_data[user_number].get("digital_clicks", 0.0)
                    additional_costs = costos.get("machine", 0.0) + digital_clicks
                else:
                    costos = user_data[user_number].get("costos", {})
                    additional_costs = (
                        costos.get("machine", 0.0) +
                        costos.get("ink", 0.0) +
                        costos.get("lamination", 0.0) +
                        costos.get("plate", 0.0) +
                        costos.get("cortes", 0.0) +
                        costos.get("empaque", 0.0) +
                        costos.get("extra_laminado", 0.0) +
                        costos.get("goma", 0.0) +
                        costos.get("doblado", 0.0) +
                        costos.get("troquelada", 0.0) +
                        costos.get("encapsulado", 0.0) +
                        costos.get("pegado", 0.0) +
                        costos.get("barniz", 0.0)
                    )
                total_cost = paper_cost + additional_costs
                final_cost = (total_cost * 1.5) * 1.17
                client_name = user_data[user_number].get("client_name", "Cliente")
                descripcion_producto = f"{user_data[user_number]['product'][0]}, Tamaño: {dim_str}, Material: {user_data[user_number]['material'][0]}"

                file_path = generar_pdf(client_name, user_data[user_number]["material"][0], flyer_width, cantidad, final_cost, descripcion_producto)
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
