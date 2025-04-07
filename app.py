import os
import re
import math
import time
import logging
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

# Configuración de logging
LOG_FILE = "/var/www/db_serigraph/logs/serigraph.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)

# Conexión a la base de datos.
# Se asume que las tablas "products", "dimensions_volante", "material" y "additional_charges" existen.
# La tabla additional_charges tiene: id, name, description (sin precio)
conn = sqlite3.connect('/var/www/db_serigraph/seri.db', check_same_thread=False)
cursor = conn.cursor()

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
bot = Bot(token=TOKEN)
dispatcher = Dispatcher(bot, None, workers=0)

user_data = {}

# Carpeta temporal para PDFs (aunque ahora se guardará en la carpeta de cotizaciones)
TEMP_PDF_DIR = "temp_pdfs"
if not os.path.exists(TEMP_PDF_DIR):
    os.makedirs(TEMP_PDF_DIR)

def formato_monetario(valor):
    return f"Q{valor:,.2f}"

def generar_pdf(client_name, material, flyer_width, cantidad, costo_total, descripcion_producto, quote_folder):
    """
    Genera un PDF de cotización con información esencial y lo guarda en el folder quote_folder:
      - Nombre del cliente
      - Producto, tamaño y material
      - Cantidad cotizada y costo final
      - Datos de la empresa
    """
    file_name = f"cotizacion_{client_name}_{int(time.time())}.pdf"
    file_path = os.path.join(quote_folder, file_name)
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
    c.drawString(430, 770, f"Cotización No. {int(time.time()) % 100000}")
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
    logging.info(f"PDF generado para {client_name} en {file_path}")
    return file_path

# Funciones para administrar cobros adicionales (menú de edición)
def agregar_cobro(nombre, descripcion):
    cursor.execute("INSERT INTO additional_charges (name, description) VALUES (?, ?)", (nombre, descripcion))
    conn.commit()
    logging.info(f"Cobro adicional agregado: {nombre} - {descripcion}")

def eliminar_cobro(cobro_id):
    cursor.execute("DELETE FROM additional_charges WHERE id=?", (cobro_id,))
    conn.commit()
    logging.info(f"Cobro adicional eliminado: ID {cobro_id}")

def obtener_cobros():
    cursor.execute("SELECT id, name, description FROM additional_charges")
    return cursor.fetchall()

# Flujo del webhook de Telegram.
def telegram_webhook(update: Update, context):
    user_number = update.message.chat.id
    incoming_message = update.message.text.strip()

    # Consultas de productos, dimensiones y materiales
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
        response_message = "¡Hola! Ingresa tu nombre de cliente:"
        user_data[user_number] = {"step": "ask_nombre"}
        logging.info(f"Nuevo inicio de conversación con {user_number}")
    elif user_number in user_data:
        step = user_data[user_number]["step"]
        # Paso 1: pedir nombre de cliente y luego nombre de cotización
        if step == "ask_nombre":
            client_name = incoming_message.strip()
            logging.info(f"Nueva cotización para cliente  {client_name}")
            if not client_name:
                response_message = "El nombre no puede estar vacío. Ingresa tu nombre de cliente:"
            else:
                user_data[user_number]["client_name"] = client_name
                response_message = "Bienvenido\n1. Cotización\n2. Editar cobros adicionales"
                user_data[user_number]["step"] = "menu"
                logging.info(f"Cotización  para cliente {user_data[user_number]['client_name']} ingresada por {user_number}")
                # user_data[user_number]["step"] = "menu"
                logging.info(f"Cliente {client_name} ingresado por {user_number}")
        elif step == "ask_quote_name":
            quote_name = incoming_message.strip()
            if not quote_name:
                response_message = "El nombre de la cotización no puede estar vacío. Ingresa el nombre de la cotización:"
            else:
                user_data[user_number]["quote_name"] = quote_name
        # Menú principal
        elif step == "menu":
            if incoming_message == "1":
                texto = "Selecciona el producto:\n"
                texto += "0. Agregar nuevo producto\n"
                texto += "\n".join([f"{i+1}. {prod}" for i, prod in enumerate(diccionario_productos.keys())])
                response_message = texto
                user_data[user_number]["step"] = "productos"
            elif incoming_message == "2":
                response_message = ("Has seleccionado editar cobros adicionales:\n"
                                    "1. Agregar cobro adicional\n"
                                    "2. Eliminar cobro adicional\n"
                                    "3. Ver cobros adicionales existentes")
                user_data[user_number]["step"] = "admin_charges"
            else:
                response_message = "Opción no válida. Envía '1' para Cotización o '2' para Editar cobros adicionales."
        elif step == "admin_charges":
            if incoming_message == "1":
                response_message = ("Ingresa el nombre y la descripción separados por coma.\nEj: Pegamento, Especial")
                user_data[user_number]["step"] = "add_charge"
            elif incoming_message == "2":
                charges = obtener_cobros()
                if charges:
                    response_message = "Selecciona el ID del cobro a eliminar:\n"
                    for charge in charges:
                        response_message += f"{charge[0]}. {charge[1]} - {charge[2]}\n"
                else:
                    response_message = "No hay cobros adicionales registrados."
                user_data[user_number]["step"] = "delete_charge"
            elif incoming_message == "3":
                charges = obtener_cobros()
                if charges:
                    response_message = "Cobros actuales:\n"
                    for charge in charges:
                        response_message += f"{charge[1]} ({charge[2]})\n"
                else:
                    response_message = "No hay cobros adicionales registrados."
                response_message += "\n\nMenú:\n1. Cotización\n2. Editar cobros adicionales"
                user_data[user_number]["step"] = "menu"
            else:
                response_message = "Opción no válida en administración de cobros. Intenta de nuevo."
        elif step == "add_charge":
            try:
                parts = incoming_message.split(",")
                if len(parts) < 2:
                    raise ValueError("Faltan datos")
                nombre = parts[0].strip()
                descripcion = parts[1].strip()
                agregar_cobro(nombre, descripcion)
                response_message = "Cobro agregado correctamente."
            except Exception as e:
                logging.error(f"Error al agregar cobro: {e}")
                response_message = "Formato incorrecto. Intenta de nuevo. Ej: Pegamento, Especial"
            user_data[user_number]["step"] = "menu"
        elif step == "delete_charge":
            try:
                charge_id = int(incoming_message)
                eliminar_cobro(charge_id)
                response_message = "Cobro eliminado correctamente."
            except Exception as e:
                logging.error(f"Error al eliminar cobro: {e}")
                response_message = "Opción inválida. Intenta de nuevo."
            user_data[user_number]["step"] = "menu"
        # Flujo de cotización:
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
                logging.error(f"Error en selección de dimensión: {e}")
                response_message = "Error, ingresa un tamaño válido."
        elif step == "dimension_specific":
            # Se espera un formato válido usando regex, ej. "20x10" o "20 x 10"
            pattern = r'^\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*$'
            match = re.fullmatch(pattern, incoming_message)
            if match:
                width, height = match.groups()
                width, height = float(width), float(height)
                if width <= 0 or height <= 0:
                    response_message = "Las dimensiones deben ser mayores a 0. Ingresa el tamaño nuevamente (Ej: 20x10):"
                    return update.message.reply_text(response_message)
                # Almacenamos la dimensión ingresada con precio 0.0 por defecto
                dim_str = f"{width}x{height}"
                cursor.execute("INSERT INTO dimensions_volante (dimension, price) VALUES (?, ?)", (dim_str, 0.0))
                conn.commit()
                texto = f"Tamaño: {dim_str} - Q0.0\nSelecciona material:\n"
                texto += "\n".join([f"{i}. {mat}" for i, mat in materiales.items()])
                response_message = texto
                user_data[user_number].update({"step": "material", "dimensiones": (dim_str, 0.0)})
                logging.info(f"Dimensión específica ingresada: {dim_str} por {user_number}")
            else:
                response_message = "Formato inválido. Usa el formato 'ancho x alto' (Ej: 20x10)."
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
            response_message = "¿Cuántos volantes deseas cotizar? (debe ser mayor a 0)"
            user_data[user_number]["step"] = "cantidad"
        elif step == "cantidad":
            try:
                cantidad = int(incoming_message)
                if cantidad <= 0:
                    response_message = "La cantidad debe ser mayor a 0. Ingresa la cantidad:"
                    return update.message.reply_text(response_message)
                user_data[user_number]["cantidad"] = cantidad
                response_message = "¿Es impresión digital? (si/no):"
                user_data[user_number]["step"] = "digital"
            except:
                response_message = "Ingresa una cantidad válida (número mayor a 0)."
        # Flujo para procesar cargos adicionales: tras la respuesta digital se recorren los cargos definidos en la DB.
        elif step == "digital":
            if incoming_message.lower() in ["si", "sí", "no"]:
                user_data[user_number]["digital"] = (incoming_message.lower() in ["si", "sí"])
                # Consultamos los cargos adicionales definidos en la DB.
                cursor.execute("SELECT id, name, description FROM additional_charges")
                additional_list = cursor.fetchall()
                user_data[user_number]["additional_list"] = additional_list
                user_data[user_number]["current_charge_index"] = 0
                user_data[user_number]["additional_values"] = []
                if additional_list:
                    charge = additional_list[0]
                    response_message = f"Ingrese el precio para {charge[1]} ({charge[2]}): (valor >= 0)"
                    user_data[user_number]["step"] = "ask_additional"
                else:
                    response_message = "No hay cargos adicionales. Confirma tu pedido respondiendo 'si' o 'no'."
                    user_data[user_number]["step"] = "confirmacion"
            else:
                response_message = "Respuesta no válida, ingresa 'si' o 'no'."
        elif step == "ask_additional":
            try:
                price = float(incoming_message)
                if price < 0:
                    response_message = "El precio no puede ser negativo. Ingresa un valor >= 0:"
                    return update.message.reply_text(response_message)
                additional_values = user_data[user_number].get("additional_values", [])
                additional_values.append(price)
                user_data[user_number]["additional_values"] = additional_values
                current_index = user_data[user_number]["current_charge_index"] + 1
                additional_list = user_data[user_number]["additional_list"]
                if current_index < len(additional_list):
                    user_data[user_number]["current_charge_index"] = current_index
                    charge = additional_list[current_index]
                    response_message = f"Ingrese el precio para {charge[1]} ({charge[2]}): "
                else:
                    response_message = "Todos los cargos adicionales han sido registrados. Confirma tu pedido respondiendo 'si' o 'no'."
                    user_data[user_number]["step"] = "confirmacion"
            except:
                response_message = "Ingresa un valor numérico para el precio (valor >= 0)."
        elif step == "confirmacion":
            if "si" in incoming_message.lower():
                cantidad = user_data[user_number]["cantidad"]

                # Procesamos la dimensión seleccionada.
                dim_str, precio_dim = user_data[user_number]["dimensiones"]
                try:
                    flyer_dimensions = dim_str.lower().split("x")
                    flyer_width = float(flyer_dimensions[0])
                    flyer_height = float(flyer_dimensions[1])
                    if flyer_width <= 0 or flyer_height <= 0:
                        raise ValueError("Dimensiones inválidas")
                except:
                    flyer_width, flyer_height = (0, 0)
                flyer_area = flyer_width * flyer_height

                material, mat_price, mat_medida = user_data[user_number]["material"]
                try:
                    mat_dims = mat_medida.split("x")
                    mat_width = float(mat_dims[0])
                    mat_height = float(mat_dims[1])
                    if mat_width <= 0 or mat_height <= 0:
                        raise ValueError("Dimensiones de material inválidas")
                except:
                    mat_width, mat_height = (0, 0)
                material_area = mat_width * mat_height
                logging.info(f"Información de cliente: {user_data[user_number]}")
                flyers_per_sheet = max(math.floor(material_area / flyer_area) - 1, 1)
                required_sheets = math.ceil(cantidad / flyers_per_sheet) + 2
                cost_per_sheet = mat_price / 500.0
                paper_cost = required_sheets * cost_per_sheet

                # Suma de los precios ingresados para cada cargo adicional.
                additional_costs = sum(user_data[user_number].get("additional_values", []))
                total_cost = paper_cost + additional_costs
                final_cost = (total_cost * 1.5) * 1.17

                client_name = user_data[user_number].get("client_name", "Cliente")
                descripcion_producto = f"{user_data[user_number]['product'][0]}, Tamaño: {dim_str}, Material: {user_data[user_number]['material'][0]}"

                # Creamos una carpeta para la cotización usando el nombre de cotización y fecha.
                quote_name = user_data[user_number].get("client_name", "cotizacion")
                timestamp = time.strftime('%Y%m%d_%H%M%S')
                quote_folder = f"/var/www/db_serigraph/cotis/{quote_name}_{timestamp}"
                if not os.path.exists(quote_folder):
                    os.makedirs(quote_folder)
                    logging.info(f"Carpeta creada: {quote_folder}")

                file_path = generar_pdf(client_name, user_data[user_number]["material"][0],
                                        flyer_width, cantidad, final_cost, descripcion_producto,
                                        quote_folder)
                context.bot.send_document(chat_id=user_number, document=open(file_path, 'rb'),
                                          filename=os.path.basename(file_path))
                response_message = "¡Cotización generada!"
                logging.info(f"Cotización generada para {client_name} en carpeta {quote_folder}")
                del user_data[user_number]
            elif "no" in incoming_message.lower():
                response_message = "Cotización cancelada."
                logging.info(f"Cotización cancelada por {user_number}")
                del user_data[user_number]
            else:
                response_message = "Debes ingresar 'si' ó 'no'."
                logging.info(f"Cotización cancelada por {user_number}")
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
