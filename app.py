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

DIMENSION_ALIASES = {
    "carta 8.5x11": (8.5, 11),        # 8.5" x 11"
    "oficio 8.5x14": (8.5, 14),       # 8.5" x 14"
    "media carta 8.5x5.5": (8.5, 5.5),  # 8.5" x 5.5"
    "medio oficio 8.5x7": (8.5, 7),   # 8.5" x 7"
    # Agrega aquí más equivalencias si lo requieres...
}

def formato_monetario(valor):
    return f"Q{valor:,.2f}"

def generar_pdf(client_name, material, flyer_width, cantidad, costo_total, descripcion_producto, quote_folder):
    """
    Genera un PDF de cotización con información esencial y lo guarda en el folder quote_folder.
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

def parse_dimension(dim_str: str) -> (float, float):
    """
    Devuelve (width, height) en cm a partir de una cadena como '20x30', 'carta' o 'carta 8.5x11'.
    Si no se puede parsear, devuelve (0,0).
    """
    dim_str = dim_str.lower().strip()
    
    # Buscar un patrón que contenga dos números separados por "x"
    match = re.search(r'(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)', dim_str)
    if match:
        try:
            w = float(match.group(1))
            h = float(match.group(2))
            if w > 0 and h > 0:
                return (w, h)
        except Exception:
            return (0, 0)
    
    # Si no se encontró un patrón numérico, se busca el alias completo en DIMENSION_ALIASES.
    if dim_str in DIMENSION_ALIASES:
        return DIMENSION_ALIASES[dim_str]
    
    return (0, 0)

# Flujo del webhook de Telegram.
def telegram_webhook(update: Update, context):
    user_number = update.message.chat.id
    incoming_message = update.message.text.strip()

    # -------------------------------------------------------
    # Opción de "paso atrás": se aceptan "atras" o "atrás"
    if user_number in user_data and incoming_message.lower() in ["r", "R"]:
        current_step = user_data[user_number].get("step", "")
        back_steps = {
            "menu": None,  # No se permite retroceder desde el menú principal
            "productos": "menu",
            "nuevo_producto": "productos",
            "dimensiones": "productos",
            "dimension_specific": "dimensiones",
            "material": "dimensiones",
            "cantidad": "material",
            "digital": "cantidad",
            "ask_additional": "digital",
            "ask_extra_cost": "ask_additional",
            "extra_cost_amount": "ask_extra_cost",
            "extra_cost_description": "extra_cost_amount",
            "ask_margin": "ask_extra_cost",
            "set_margin": "ask_margin",
            "confirmacion": "set_margin",
            "admin_charges": "menu",
            "add_charge": "admin_charges",
            "delete_charge": "admin_charges"
        }
        if current_step in back_steps and back_steps[current_step]:
            prev = back_steps[current_step]
            user_data[user_number]["step"] = prev
            response_message = f"Retrocediendo. Por favor ingresa nuevamente la información para '{prev}':"
            update.message.reply_text(response_message)
            return
        else:
            response_message = "No puedes retroceder en este paso."
            update.message.reply_text(response_message)
            return
    # -------------------------------------------------------

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
        if step == "ask_nombre":
            client_name = incoming_message.strip()
            logging.info(f"Nueva cotización para cliente {client_name}")
            if not client_name:
                response_message = "El nombre no puede estar vacío. Ingresa tu nombre de cliente:"
            else:
                user_data[user_number]["client_name"] = client_name
                response_message = "Bienvenido\n1. Cotización\n2. Editar cobros adicionales"
                user_data[user_number]["step"] = "menu"
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
                response_message = "Ingresa el nombre y la descripción separados por coma.\nEj: Pegamento, Especial"
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
                    texto = f"{producto} - \nElige tamaño (dimensional inches):\n"
                    texto += "0. Agregar nuevo tamaño (Ej: 20x10)\n"
                    texto += "\n".join([f"{i+1}. {dim}" for i, dim in enumerate(diccionario_dimensiones.keys())])
                    response_message = texto
                    user_data[user_number]["step"] = "dimensiones"
        elif step == "nuevo_producto":
            new_product_name = incoming_message.strip()
            cursor.execute("INSERT INTO products (name, price) VALUES (?, ?)", (new_product_name, 0.0))
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
                        texto = f"Tamaño: {dim} - \nSelecciona material:\n"
                        texto += "\n".join([f"{i}. {mat}" for i, mat in materiales.items()])
                        response_message = texto
                        user_data[user_number].update({"step": "material", "dimensiones": (dim, precio_dim)})
            except Exception as e:
                logging.error(f"Error en selección de dimensión: {e}")
                response_message = "Error, ingresa un tamaño válido."
        elif step == "dimension_specific":
            pattern = r'^\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*$'
            match = re.fullmatch(pattern, incoming_message)
            if match:
                width, height = match.groups()
                width, height = float(width), float(height)
                if width <= 0 or height <= 0:
                    response_message = "Las dimensiones deben ser mayores a 0. Ingresa el tamaño nuevamente (Ej: 20x10):"
                    return update.message.reply_text(response_message)
                dim_str = f"{width}x{height}"
                cursor.execute("INSERT INTO dimensions_volante (dimension, price) VALUES (?, ?)", (dim_str, 0.0))
                conn.commit()
                texto = f"Tamaño: {dim_str} - \nSelecciona material:\n"
                texto += "\n".join([f"{i}. {mat}" for i, mat in enumerate(materiales.values())])
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
        # Paso: determinar si es digital y luego preparar cargos adicionales
        elif step == "digital":
            if incoming_message.lower() in ["si", "sí", "no"]:
                # Se guarda True si es digital, False en caso contrario
                user_data[user_number]["digital"] = (incoming_message.lower() in ["si", "sí"])
                cursor.execute("SELECT id, name, description FROM additional_charges")
                additional_list = cursor.fetchall()
                # Si es digital se eliminan los cargos de "clicks"; si no, se incluyen
                print(user_data[user_number]["digital"])
                logging.warning(f"DATA DIGITAL: {user_data[user_number]["digital"]}")
                if user_data[user_number]["digital"]:
                    additional_list = [charge for charge in additional_list if charge[2].lower() != "clicks"]
                user_data[user_number]["additional_list"] = additional_list
                user_data[user_number]["current_charge_index"] = 0
                user_data[user_number]["additional_values"] = []
                if additional_list:
                    charge = additional_list[0]
                    response_message = f"Ingrese el precio para {charge[1]} ({charge[2]}): "
                    user_data[user_number]["step"] = "ask_additional"
                else:
                    response_message = "No hay cargos adicionales. ¿Desea agregar algún costo extra? (si/no):"
                    user_data[user_number]["step"] = "ask_extra_cost"
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
                    response_message = "Todos los cargos adicionales han sido registrados. ¿Desea agregar algún costo extra? (si/no):"
                    user_data[user_number]["step"] = "ask_extra_cost"
            except:
                response_message = "Ingresa un valor numérico para el precio (valor >= 0)."
        # Flujo para agregar costos extras (no predefinidos)
        elif step == "ask_extra_cost":
            if incoming_message.lower() in ["si", "sí"]:
                response_message = "Ingresa el monto del costo extra:"
                user_data[user_number]["step"] = "extra_cost_amount"
            elif incoming_message.lower() in ["no"]:
                # Se pasa a preguntar por el margen justo antes de confirmar
                response_message = "Por defecto, el margen de ganancia es del 50%. ¿Desea modificarlo? (si/no):"
                user_data[user_number]["step"] = "ask_margin"
            else:
                response_message = "Respuesta no válida. Ingresa 'si' o 'no'."
        elif step == "extra_cost_amount":
            try:
                extra_cost = float(incoming_message)
                if extra_cost < 0:
                    response_message = "El monto no puede ser negativo. Ingresa un valor mayor o igual a 0:"
                    return update.message.reply_text(response_message)
                user_data[user_number]["temp_extra_cost"] = extra_cost
                response_message = "Ingresa la descripción para el costo extra:"
                user_data[user_number]["step"] = "extra_cost_description"
            except:
                response_message = "Ingresa un valor numérico para el costo extra."
        elif step == "extra_cost_description":
            extra_cost = user_data[user_number].pop("temp_extra_cost", 0)
            extra_desc = incoming_message.strip()
            nombre = f"costo"
            agregar_cobro(nombre, extra_desc)
            additional_values = user_data[user_number].get("additional_values", [])
            additional_values.append(extra_cost)
            user_data[user_number]["additional_values"] = additional_values
            response_message = "Costo extra agregado. ¿Desea agregar otro costo extra? (si/no):"
            user_data[user_number]["step"] = "ask_extra_cost"
        # Preguntar por el margen justo antes de confirmar
        elif step == "ask_margin":
            if incoming_message.lower() in ["si", "sí"]:
                response_message = "Ingresa el porcentaje de margen de ganancia (ej: 50 para 50%):"
                user_data[user_number]["step"] = "set_margin"
            elif incoming_message.lower() in ["no"]:
                user_data[user_number]["margin"] = 50  # Valor por defecto
                response_message = "Confirma tu pedido respondiendo 'si' o 'no':"
                user_data[user_number]["step"] = "confirmacion"
            else:
                response_message = "Respuesta no válida. Ingresa 'si' o 'no'."
        elif step == "set_margin":
            try:
                margin_val = float(incoming_message)
                if margin_val < 0:
                    response_message = "El margen no puede ser negativo. Ingresa un valor válido:"
                    return update.message.reply_text(response_message)
                user_data[user_number]["margin"] = margin_val
                response_message = "Confirma tu pedido respondiendo 'si' o 'no':"
                user_data[user_number]["step"] = "confirmacion"
            except Exception as e:
                logging.error(f"Error al establecer margen: {e}")
                response_message = "Por favor, ingresa un número válido para el margen."
        elif step == "confirmacion":
            if "si" in incoming_message.lower():
                cantidad = user_data[user_number]["cantidad"]
                dim_str, _precio_dim = user_data[user_number]["dimensiones"]
                flyer_width, flyer_height = parse_dimension(dim_str)
                if flyer_width <= 0 or flyer_height <= 0:
                    logging.warning(f"No se pudo parsear la dimensión {dim_str}, se usará 0,0")
                    flyer_width, flyer_height = (0, 0)
                material, mat_price, mat_medida = user_data[user_number]["material"]
                mat_w, mat_h = (0, 0)
                try:
                    if "x" in mat_medida:
                        mw, mh = mat_medida.lower().split("x")
                        mat_w, mat_h = float(mw), float(mh)
                        if mat_w <= 0 or mat_h <= 0:
                            mat_w, mat_h = (0, 0)
                    else:
                        mat_w, mat_h = parse_dimension(mat_medida)
                except:
                    mat_w, mat_h = (0, 0)
                flyer_area = flyer_width * flyer_height
                material_area = mat_w * mat_h
                if flyer_area <= 0 or material_area <= 0:
                    flyers_per_sheet = 1
                else:
                    flyers_per_sheet = max(math.floor(material_area / flyer_area) - 1, 1)
                required_sheets = math.ceil(cantidad / flyers_per_sheet) + 2
                cost_per_sheet = mat_price / 500.0
                paper_cost = required_sheets * cost_per_sheet
                additional_costs = sum(user_data[user_number].get("additional_values", []))
                total_cost = paper_cost + additional_costs
                margin = user_data[user_number].get("margin", 50)
                final_cost = (total_cost * (1 + margin / 100.0)) * 1.17
                client_name = user_data[user_number].get("client_name", "Cliente")
                descripcion_producto = f"{user_data[user_number]['product'][0]}, Tamaño: {dim_str}, Material: {user_data[user_number]['material'][0]}"
                quote_name = client_name
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
                response_message = "Debes ingresar 'si' o 'no'."
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
