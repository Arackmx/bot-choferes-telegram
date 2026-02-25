"""
Bot de Telegram para Reportes de Choferes
Versión optimizada - Solo datos
Optimizado para Render.com
"""

import os
import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

from telegram import Update, ReplyKeyboardRemove
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
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON')

# ==================== LOGGING ====================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== ESTADOS ====================

NOMBRE, PLACA, KM_INICIAL, KM_FINAL, COMENTARIOS = range(5)

# ==================== GOOGLE CONFIG ====================

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def obtener_credenciales():
    credentials_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    return Credentials.from_service_account_info(credentials_dict, scopes=SCOPES)

def obtener_sheet():
    creds = obtener_credenciales()
    client = gspread.authorize(creds)
    return client.open_by_key(GOOGLE_SHEET_ID).sheet1

def inicializar_sheet():
    sheet = obtener_sheet()
    if not sheet.row_values(1):
        headers = [
            'Fecha y Hora',
            'Nombre del Chofer',
            'Placa',
            'Kilometraje Inicial',
            'Kilometraje Final',
            'Comentarios'
        ]
        sheet.append_row(headers)

def guardar_reporte(datos):
    try:
        sheet = obtener_sheet()
        fila = [
            datos['fecha_hora'],
            datos['nombre'],
            datos['placa'],
            datos['km_inicial'],
            datos['km_final'],
            datos['comentarios']
        ]
        sheet.append_row(fila)
        return True
    except Exception as e:
        logger.error(f"Error guardando en Sheets: {e}")
        return False

# ==================== BOT ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hola.\n\n"
        "Para llenar el reporte debes tener:\n"
        "• Kilometraje inicial\n"
        "• Kilometraje final\n\n"
        "Usa /reporte para comenzar."
    )

async def iniciar_reporte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Escribe tu nombre completo:")
    return NOMBRE

async def nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['nombre'] = update.message.text
    await update.message.reply_text("Escribe la placa del vehículo:")
    return PLACA

async def placa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['placa'] = update.message.text.upper()
    await update.message.reply_text("Escribe el kilometraje INICIAL:")
    return KM_INICIAL

async def km_inicial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['km_inicial'] = update.message.text
    await update.message.reply_text("Escribe el kilometraje FINAL:")
    return KM_FINAL

async def km_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['km_final'] = update.message.text
    await update.message.reply_text(
        "Agrega comentarios.\n"
        "Si no tienes comentarios escribe: sin comentarios"
    )
    return COMENTARIOS

async def comentarios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['comentarios'] = update.message.text
    context.user_data['fecha_hora'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        loop = context.application.loop

        exito = await loop.run_in_executor(
            None,
            guardar_reporte,
            context.user_data
        )

        if exito:
            await update.message.reply_text(
                "✅ Reporte guardado correctamente.\n\n"
                "Usa /reporte para registrar otro."
            )
        else:
            await update.message.reply_text(
                "❌ Error al guardar el reporte."
            )

    except Exception as e:
        logger.error(f"Error async guardando: {e}")
        await update.message.reply_text("❌ Error inesperado al guardar.")

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
    logger.error(f"Error global: {context.error}")

# ==================== MAIN ====================

def main():

    if not TELEGRAM_TOKEN or not GOOGLE_SHEET_ID or not GOOGLE_CREDENTIALS_JSON:
        logger.error("Faltan variables de entorno.")
        return

    inicializar_sheet()

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('reporte', iniciar_reporte)],
        states={
            NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, nombre)],
            PLACA: [MessageHandler(filters.TEXT & ~filters.COMMAND, placa)],
            KM_INICIAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, km_inicial)],
            KM_FINAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, km_final)],
            COMENTARIOS: [MessageHandler(filters.TEXT & ~filters.COMMAND, comentarios)],
        },
        fallbacks=[CommandHandler('cancelar', cancelar)],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ayuda", ayuda))
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)

    threading.Thread(target=run_health_server, daemon=True).start()

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == "__main__":
    main()
