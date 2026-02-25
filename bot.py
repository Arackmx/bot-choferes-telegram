"""
Bot de Telegram para Reportes de Choferes
Optimizado para Render.com
Registra inicio/fin de jornada, datos del vehículo y fotos
Sube información a Google Sheets y fotos a Google Drive
"""

import logging
import os
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import json

# ==================== CONFIGURACIÓN ====================
# Estas variables se cargarán desde las variables de entorno en Render
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
GOOGLE_SHEET_ID = os.environ.get('GOOGLE_SHEET_ID')
GOOGLE_DRIVE_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')

# Las credenciales de Google se cargarán desde variable de entorno
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON')

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== ESTADOS DE CONVERSACIÓN ====================
TIPO_JORNADA, NOMBRE, PLACA, KILOMETRAJE, FOTO_PLACA, FOTO_KILOMETRAJE, FOTO_ESTADO = range(7)

# ==================== CONFIGURACIÓN DE GOOGLE ====================
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def obtener_credenciales():
    """Obtener credenciales de Google desde variable de entorno"""
    try:
        # Cargar las credenciales desde JSON string
        credentials_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        return Credentials.from_service_account_info(credentials_dict, scopes=SCOPES)
    except Exception as e:
        logger.error(f"Error al cargar credenciales: {e}")
        raise

def obtener_sheet():
    """Obtener el cliente de Google Sheets"""
    creds = obtener_credenciales()
    client = gspread.authorize(creds)
    return client.open_by_key(GOOGLE_SHEET_ID).sheet1

def obtener_drive_service():
    """Obtener el servicio de Google Drive"""
    creds = obtener_credenciales()
    return build('drive', 'v3', credentials=creds)

def inicializar_sheet():
    """Crear encabezados en Google Sheets si no existen"""
    try:
        sheet = obtener_sheet()
        # Verificar si ya hay encabezados
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
            logger.info("Encabezados creados en Google Sheets")
        else:
            logger.info("Google Sheets ya tiene encabezados")
    except Exception as e:
        logger.error(f"Error al inicializar sheet: {e}")
        raise

def subir_foto_a_drive(ruta_foto, nombre_archivo):
    """Subir foto a Google Drive y retornar el link"""
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
        
        # Hacer el archivo público para que el link funcione
        drive_service.permissions().create(
            fileId=file['id'],
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
        
        logger.info(f"Foto subida exitosamente: {file['webViewLink']}")
        return file['webViewLink']
    
    except Exception as e:
        logger.error(f"Error al subir foto a Drive: {e}")
        return "Error al subir"

def guardar_reporte_en_sheet(datos):
    """Guardar reporte completo en Google Sheets"""
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
        logger.info(f"Reporte guardado en Sheets para {datos['nombre']}")
        return True
    except Exception as e:
        logger.error(f"Error al guardar en Sheets: {e}")
        return False

# ==================== FUNCIONES DEL BOT ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start - Inicia el bot"""
    user = update.effective_user
    await update.message.reply_text(
        f"¡Hola {user.first_name}! 👋\n\n"
        "Soy el bot de reportes de choferes. 🏍️\n\n"
        "Usa /reporte para registrar tu jornada."
    )

async def iniciar_reporte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /reporte - Inicia el proceso de reporte"""
    context.user_data.clear()  # Limpiar datos previos
    
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
    """Guardar tipo de jornada"""
    text = update.message.text
    
    if '🟢' in text or 'Inicio' in text:
        context.user_data['tipo_jornada'] = 'Inicio de Jornada'
    else:
        context.user_data['tipo_jornada'] = 'Fin de Jornada'
    
    await update.message.reply_text(
        "Por favor, escribe tu nombre completo:",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return NOMBRE

async def nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guardar nombre del chofer"""
    context.user_data['nombre'] = update.message.text
    
    await update.message.reply_text(
        "Escribe la placa del vehículo:"
    )
    
    return PLACA

async def placa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guardar placa del vehículo"""
    context.user_data['placa'] = update.message.text.upper()
    
    await update.message.reply_text(
        "Escribe el kilometraje actual:"
    )
    
    return KILOMETRAJE

async def kilometraje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guardar kilometraje"""
    context.user_data['kilometraje'] = update.message.text
    
    await update.message.reply_text(
        "📸 Envía una foto de la PLACA del vehículo:"
    )
    
    return FOTO_PLACA

async def foto_placa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibir y procesar foto de placa"""
    # Obtener la foto de mayor calidad
    photo = update.message.photo[-1]
    
    # Descargar foto
    file = await context.bot.get_file(photo.file_id)
    nombre_archivo = f"placa_{context.user_data['placa']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    ruta_local = f"/tmp/{nombre_archivo}"
    await file.download_to_drive(ruta_local)
    
    await update.message.reply_text("⏳ Subiendo foto de placa a Drive...")
    
    # Subir a Drive
    link = subir_foto_a_drive(ruta_local, nombre_archivo)
    context.user_data['link_foto_placa'] = link
    context.user_data['foto_placa_local'] = ruta_local
    
    await update.message.reply_text(
        "✅ Foto de placa guardada.\n\n"
        "📸 Ahora envía una foto del KILOMETRAJE:"
    )
    
    return FOTO_KILOMETRAJE

async def foto_kilometraje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibir y procesar foto de kilometraje"""
    photo = update.message.photo[-1]
    
    file = await context.bot.get_file(photo.file_id)
    nombre_archivo = f"km_{context.user_data['placa']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    ruta_local = f"/tmp/{nombre_archivo}"
    await file.download_to_drive(ruta_local)
    
    await update.message.reply_text("⏳ Subiendo foto de kilometraje a Drive...")
    
    link = subir_foto_a_drive(ruta_local, nombre_archivo)
    context.user_data['link_foto_kilometraje'] = link
    context.user_data['foto_km_local'] = ruta_local
    
    await update.message.reply_text(
        "✅ Foto de kilometraje guardada.\n\n"
        "📸 Por último, envía una foto del ESTADO GENERAL de la moto:"
    )
    
    return FOTO_ESTADO

async def foto_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibir foto de estado y finalizar reporte"""
    photo = update.message.photo[-1]
    
    file = await context.bot.get_file(photo.file_id)
    nombre_archivo = f"estado_{context.user_data['placa']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    ruta_local = f"/tmp/{nombre_archivo}"
    await file.download_to_drive(ruta_local)
    
    await update.message.reply_text("⏳ Subiendo foto de estado a Drive...")
    
    link = subir_foto_a_drive(ruta_local, nombre_archivo)
    context.user_data['link_foto_estado'] = link
    context.user_data['foto_estado_local'] = ruta_local
    
    # Preparar datos completos
    context.user_data['fecha_hora'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Guardar en Google Sheets
    await update.message.reply_text("💾 Guardando reporte en Google Sheets...")
    
    exito = guardar_reporte_en_sheet(context.user_data)
    
    # Limpiar archivos temporales
    for key in ['foto_placa_local', 'foto_km_local', 'foto_estado_local']:
        if key in context.user_data:
            try:
                os.remove(context.user_data[key])
            except:
                pass
    
    if exito:
        await update.message.reply_text(
            "✅ ¡Reporte completado exitosamente! ✅\n\n"
            f"📋 Resumen:\n"
            f"• Tipo: {context.user_data['tipo_jornada']}\n"
            f"• Chofer: {context.user_data['nombre']}\n"
            f"• Placa: {context.user_data['placa']}\n"
            f"• Kilometraje: {context.user_data['kilometraje']} km\n\n"
            "Toda la información ha sido guardada en Google Sheets "
            "y las fotos en Google Drive.\n\n"
            "Usa /reporte para hacer otro reporte. 🏍️"
        )
    else:
        await update.message.reply_text(
            "❌ Hubo un error al guardar el reporte.\n"
            "Por favor, intenta nuevamente con /reporte"
        )
    
    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancelar el proceso de reporte"""
    await update.message.reply_text(
        "Reporte cancelado. Usa /reporte para iniciar uno nuevo.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ayuda - Muestra información de ayuda"""
    await update.message.reply_text(
        "📖 *Comandos disponibles:*\n\n"
        "/start - Iniciar el bot\n"
        "/reporte - Crear un nuevo reporte\n"
        "/ayuda - Mostrar esta ayuda\n"
        "/cancelar - Cancelar reporte actual\n\n"
        "💡 *Cómo usar:*\n"
        "1. Usa /reporte\n"
        "2. Selecciona inicio o fin de jornada\n"
        "3. Proporciona los datos solicitados\n"
        "4. Sube las 3 fotos requeridas\n"
        "5. ¡Listo! Todo se guarda automáticamente",
        parse_mode='Markdown'
    )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Manejar errores del bot"""
    logger.error(f"Exception while handling an update: {context.error}")

def main():
    """Función principal para ejecutar el bot"""
    # Verificar que las variables de entorno estén configuradas
    if not TELEGRAM_TOKEN:
        logger.error("ERROR: TELEGRAM_TOKEN no está configurado")
        return
    if not GOOGLE_SHEET_ID:
        logger.error("ERROR: GOOGLE_SHEET_ID no está configurado")
        return
    if not GOOGLE_DRIVE_FOLDER_ID:
        logger.error("ERROR: GOOGLE_DRIVE_FOLDER_ID no está configurado")
        return
    if not GOOGLE_CREDENTIALS_JSON:
        logger.error("ERROR: GOOGLE_CREDENTIALS_JSON no está configurado")
        return
    
    # Inicializar Google Sheets
    try:
        inicializar_sheet()
        logger.info("✅ Google Sheets inicializado correctamente")
    except Exception as e:
        logger.error(f"❌ Error al inicializar Google Sheets: {e}")
        logger.error("Verifica tus credenciales y IDs de configuración")
        return
    
    # Crear la aplicación
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Configurar el manejador de conversación
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
    
    # Agregar manejadores
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ayuda", ayuda))
    application.add_handler(conv_handler)
    
    # Agregar manejador de errores
    application.add_error_handler(error_handler)
    
    # Iniciar el bot
    logger.info("🤖 Bot iniciado correctamente en Render.com")
    logger.info("Bot funcionando 24/7...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
