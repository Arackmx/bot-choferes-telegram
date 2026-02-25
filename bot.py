"""
Bot de Telegram para Reportes de Choferes
Versión con cálculo automático de kilometraje total
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
            'Total de Kilómetros',
            'Comentarios'
        ]
        sheet.append_row(headers)
        logger.info("Encabezados creados en Google Sheets")
    else:
        logger.info("Google Sheets ya inicializado")

def guardar_reporte(datos):
    try:
        sheet = obtener_sheet()
        fila = [
            datos['fecha_hora'],
            datos['nombre'],
            datos['placa'],
            datos['km_inicial'],
            datos['km_final'],
            datos['total_km'],
            datos['comentarios']
        ]
        sheet.append_row(fila)
        logger.info(f"Reporte guardado para {datos['nombre']}")
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
        "El bot calculará automáticamente el total de kilómetros recorridos.\n\n"
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
    km_text = update.message.text.strip()
    
    # Validar que sea un número
    try:
        km_numero = float(km_text.replace(',', ''))
        context.user_data['km_inicial'] = km_text
        context.user_data['km_inicial_numero'] = km_numero
        await update.message.reply_text("Escribe el kilometraje FINAL:")
        return KM_FINAL
    except ValueError:
        await update.message.reply_text(
            "⚠️ Por favor, escribe solo números.\n"
            "Ejemplo: 1000 o 1000.5\n\n"
            "Escribe el kilometraje INICIAL:"
        )
        return KM_INICIAL

async def km_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    km_text = update.message.text.strip()
    
    # Validar que sea un número
    try:
        km_numero = float(km_text.replace(',', ''))
        context.user_data['km_final'] = km_text
        context.user_data['km_final_numero'] = km_numero
        
        # Calcular el total de kilómetros
        km_inicial = context.user_data['km_inicial_numero']
        total_km = km_numero - km_inicial
        
        # Validar que el km final sea mayor que el inicial
        if total_km < 0:
            await update.message.reply_text(
                "⚠️ El kilometraje final no puede ser menor que el inicial.\n\n"
                f"Kilometraje Inicial: {context.user_data['km_inicial']}\n"
                f"Kilometraje Final ingresado: {km_text}\n\n"
                "Por favor, escribe el kilometraje FINAL correcto:"
            )
            return KM_FINAL
        
        # Guardar el total calculado
        context.user_data['total_km'] = str(round(total_km, 2))
        
        # Mostrar el cálculo antes de pedir comentarios
        await update.message.reply_text(
            f"📊 Cálculo automático:\n\n"
            f"KM Final: {km_text}\n"
            f"KM Inicial: {context.user_data['km_inicial']}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"✅ Total recorrido: {context.user_data['total_km']} km\n\n"
            "Ahora agrega comentarios.\n"
            "Si no tienes comentarios escribe: sin comentarios"
        )
        return COMENTARIOS
        
    except ValueError:
        await update.message.reply_text(
            "⚠️ Por favor, escribe solo números.\n"
            "Ejemplo: 1150 o 1150.5\n\n"
            "Escribe el kilometraje FINAL:"
        )
        return KM_FINAL

async def comentarios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['comentarios'] = update.message.text
    context.user_data['fecha_hora'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    await update.message.reply_text("💾 Guardando reporte...")

    try:
        # Guardar directamente sin usar loop
        exito = guardar_reporte(context.user_data)

        if exito:
            await update.message.reply_text(
                "✅ Reporte guardado correctamente.\n\n"
                f"📋 Resumen:\n"
                f"• Nombre: {context.user_data['nombre']}\n"
                f"• Placa: {context.user_data['placa']}\n"
                f"• KM Inicial: {context.user_data['km_inicial']}\n"
                f"• KM Final: {context.user_data['km_final']}\n"
                f"• Total Recorrido: {context.user_data['total_km']} km\n\n"
                "Usa /reporte para registrar otro."
            )
        else:
            await update.message.reply_text(
                "❌ Error al guardar el reporte.\n"
                "Verifica que el Sheet esté compartido con el service account."
            )

    except Exception as e:
        logger.error(f"Error guardando: {e}")
        await update.message.reply_text(
            f"❌ Error inesperado: {str(e)}\n"
            "Contacta al administrador."
        )

    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Reporte cancelado.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Comandos disponibles:\n\n"
        "/start - Iniciar el bot\n"
        "/reporte - Crear un nuevo reporte\n"
        "/ayuda - Mostrar esta ayuda\n"
        "/cancelar - Cancelar reporte actual\n\n"
        "💡 El bot calcula automáticamente el total de kilómetros recorridos."
    )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error global: {context.error}")

# ==================== MAIN ====================

def main():

    if not TELEGRAM_TOKEN or not GOOGLE_SHEET_ID or not GOOGLE_CREDENTIALS_JSON:
        logger.error("❌ Faltan variables de entorno.")
        return

    try:
        inicializar_sheet()
        logger.info("✅ Google Sheets inicializado correctamente")
    except Exception as e:
        logger.error(f"❌ Error al inicializar Google Sheets: {e}")
        return

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

    # Iniciar servidor de salud para Render
    threading.Thread(target=run_health_server, daemon=True).start()
    logger.info("🚀 Servidor de salud iniciado")

    logger.info("🤖 Bot iniciado correctamente")
    logger.info("Bot funcionando 24/7 en Render.com")
    
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == "__main__":
    main()
