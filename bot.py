"""
Bot de Telegram para Reportes de Choferes
Optimizado para Render.com
Registra inicio/fin de jornada, datos del vehículo y fotos
Sube información a Google Sheets y fotos a Google Drive
"""

import os
import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==================== SERVIDOR PARA RENDER ====================

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# ==================== CONFIGURACIÓN ====================

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
GOOGLE_SHEET_ID = os.environ.get('GOOGLE_SHEET_ID')
GOOGLE_DRIVE_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON')

# ==================== LOGGING ====================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== ESTADOS ====================

TIPO_JORNADA, NOMBRE, PLACA, KILOMETRAJE, FOTO_PLACA, FOTO_KILOMETRAJE, FOTO_ESTADO = range(7)

# ==================== GOOGLE CONFIG ====================

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def obtener_credenciales():
    credentials_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    return Credentials.from_service_account_info(credentials_dict, scopes=SCOPES)

def obtener_sheet():
    creds = obtener_credenciales()
    client = gspread.authorize(creds)
    return client.open_by_key(GOOGLE_SHEET_ID).sheet1

def obtener_drive_service():
    creds = obtener_credenciales()
    return build('drive', 'v3', credentials=creds)

def inicializar_sheet():
    sheet = obtener_sheet()
    if not sheet.row_values(1):
        headers = [
            'Fecha y Hora',
            'Tipo de Jornada',
            'Nombre del Chofer',
            'Placa',
            'Kilometraje',
            'Link Foto Placa',
            'Link Foto Kilometraje',
            'Link Foto Estado Moto'
        ]
        sheet.append_row(headers)

def subir_foto_a_drive(ruta_foto, nombre_archivo):
    try:
        drive_service = obtener_drive_service()

        file_metadata = {
            'name': nombre_archivo,
            'parents': [GOOGLE_DRIVE_FOLDER_ID]
        }

        media = MediaFileUpload(ruta_foto, resumable=True)

        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()

        drive_service.permissions().create(
            fileId=file['id'],
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()

        return file['webViewLink']

    except Exception as e:
        logger.error(f"Error al subir foto a Drive: {e}")
        return "Error al subir"

def guardar_reporte_en_sheet(datos):
    try:
        sheet = obtener_sheet()
        fila = [
            datos['fecha_hora'],
            datos['tipo_jornada'],
            datos['nombre'],
            datos['placa'],
            datos['kilometraje'],
            datos['link_foto_placa'],
            datos['link_foto_kilometraje'],
            datos['link_foto_estado']
        ]
        sheet.append_row(fila)
        return True
    except Exception as e:
        logger.error(f"Error al guardar en Sheets: {e}")
        return False

# ==================== BOT ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"¡Hola {user.first_name}! 👋\n\n"
        "Soy el bot de reportes de choferes. 🏍️\n\n"
        "Usa /reporte para registrar tu jornada."
    )

async def iniciar_reporte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    keyboard = [
        ['🟢 Inicio de Jornada'],
        ['🔴 Fin de Jornada']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        "Selecciona el tipo de jornada:",
        reply_markup=reply_markup
    )

    return TIPO_JORNADA

async def tipo_jornada(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if '🟢' in text:
        context.user_data['tipo_jornada'] = 'Inicio de Jornada'
    else:
        context.user_data['tipo_jornada'] = 'Fin de Jornada'

    await update.message.reply_text(
        "Por favor, escribe tu nombre completo:",
        reply_markup=ReplyKeyboardRemove()
    )

    return NOMBRE

async def nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['nombre'] = update.message.text
    await update.message.reply_text("Escribe la placa del vehículo:")
    return PLACA

async def placa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['placa'] = update.message.text.upper()
    await update.message.reply_text("Escribe el kilometraje actual:")
    return KILOMETRAJE

async def kilometraje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['kilometraje'] = update.message.text
    await update.message.reply_text("📸 Envía una foto de la PLACA del vehículo:")
    return FOTO_PLACA

async def foto_placa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    nombre_archivo = f"placa_{context.user_data['placa']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    ruta_local = f"/tmp/{nombre_archivo}"

    await file.download_to_drive(ruta_local)
    link = subir_foto_a_drive(ruta_local, nombre_archivo)

    context.user_data['link_foto_placa'] = link
    context.user_data['foto_placa_local'] = ruta_local

    await update.message.reply_text("📸 Envía una foto del KILOMETRAJE:")
    return FOTO_KILOMETRAJE

async def foto_kilometraje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    nombre_archivo = f"km_{context.user_data['placa']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    ruta_local = f"/tmp/{nombre_archivo}"

    await file.download_to_drive(ruta_local)
    link = subir_foto_a_drive(ruta_local, nombre_archivo)

    context.user_data['link_foto_kilometraje'] = link
    context.user_data['foto_km_local'] = ruta_local

    await update.message.reply_text("📸 Envía una foto del ESTADO GENERAL:")
    return FOTO_ESTADO

async def foto_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    nombre_archivo = f"estado_{context.user_data['placa']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    ruta_local = f"/tmp/{nombre_archivo}"

    await file.download_to_drive(ruta_local)
    link = subir_foto_a_drive(ruta_local, nombre_archivo)

    context.user_data['link_foto_estado'] = link
    context.user_data['foto_estado_local'] = ruta_local
    context.user_data['fecha_hora'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    exito = guardar_reporte_en_sheet(context.user_data)

    for key in ['foto_placa_local', 'foto_km_local', 'foto_estado_local']:
        if key in context.user_data:
            try:
                os.remove(context.user_data[key])
            except:
                pass

    if exito:
        await update.message.reply_text("✅ Reporte completado exitosamente.")
    else:
        await update.message.reply_text("❌ Error al guardar el reporte.")

    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Reporte cancelado.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start\n/reporte\n/ayuda\n/cancelar"
    )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

# ==================== MAIN ====================

def main():

    if not TELEGRAM_TOKEN or not GOOGLE_SHEET_ID or not GOOGLE_DRIVE_FOLDER_ID or not GOOGLE_CREDENTIALS_JSON:
        logger.error("Faltan variables de entorno.")
        return

    inicializar_sheet()

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('reporte', iniciar_reporte)],
        states={
            TIPO_JORNADA: [MessageHandler(filters.TEXT & ~filters.COMMAND, tipo_jornada)],
            NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, nombre)],
            PLACA: [MessageHandler(filters.TEXT & ~filters.COMMAND, placa)],
            KILOMETRAJE: [MessageHandler(filters.TEXT & ~filters.COMMAND, kilometraje)],
            FOTO_PLACA: [MessageHandler(filters.PHOTO, foto_placa)],
            FOTO_KILOMETRAJE: [MessageHandler(filters.PHOTO, foto_kilometraje)],
            FOTO_ESTADO: [MessageHandler(filters.PHOTO, foto_estado)],
        },
        fallbacks=[CommandHandler('cancelar', cancelar)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ayuda", ayuda))
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)

    threading.Thread(target=run_health_server, daemon=True).start()

    application.run_polling()

if __name__ == "__main__":
    main()
