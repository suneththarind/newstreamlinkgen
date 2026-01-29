import os
import logging
import urllib.parse
from telethon import TelegramClient, events
from quart import Quart, Response, request
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# --- Config ---
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
BIN_CHANNEL = int(os.getenv('BIN_CHANNEL'))
STREAM_URL = os.getenv('STREAM_URL').rstrip('/')
MONGO_URI = os.getenv('MONGO_URI')

# Database Setup
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client['telegram_bot']
links_col = db['file_links']

app = Quart(__name__)
client = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

@app.route('/')
async def index():
    return "🚀 High-Speed Multi-Threaded Server is Online!"

# --- Optimized Generator ---
async def file_generator(file_msg, start, end):
    # CHUNK_SIZE එක 512KB ලෙස තැබීම Streaming වලට වඩාත් සුදුසුයි
    CHUNK_SIZE = 512 * 1024 
    offset = start
    
    async for chunk in client.iter_download(
        file_msg.media,
        offset=offset,
        limit=(end - start + 1),
        request_size=CHUNK_SIZE
    ):
        yield chunk

@app.route('/download/<int:msg_id>')
@app.route('/watch/<int:msg_id>')
async def stream_handler(msg_id):
    try:
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not file_msg or not file_msg.file:
            return "File Not Found", 404

        file_size = file_msg.file.size
        file_name = file_msg.file.name or f"video_{msg_id}.mp4"
        mime_type = file_msg.file.mime_type or 'video/mp4'
        
        range_header = request.headers.get('Range', None)
        start_byte = 0
        end_byte = file_size - 1

        if range_header:
            range_parts = range_header.replace('bytes=', '').split('-')
            start_byte = int(range_parts[0])
            if range_parts[1]:
                end_byte = int(range_parts[1])

        # 'inline' යෙදීමෙන් Download නොවී Stream වීම සිදු වේ
        disposition = 'inline' if 'watch' in request.path else 'attachment'
        
        headers = {
            'Content-Type': mime_type,
            'Accept-Ranges': 'bytes',
            'Content-Length': str(end_byte - start_byte + 1),
            'Content-Disposition': f'{disposition}; filename="{file_name}"',
            'Access-Control-Allow-Origin': '*',
        }

        status_code = 206 if range_header else 200
        if range_header:
            headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{file_size}'

        return Response(
            file_generator(file_msg, start_byte, end_byte),
            status=status_code,
            headers=headers
        )

    except Exception as e:
        logger.error(f"Streaming Error: {e}")
        return "Internal Error", 500

# --- Bot Events with MongoDB Duplicate Check ---
@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    # File Unique ID එක ලබා ගැනීම (Duplicate check කිරීමට)
    file_id = event.file.id
    
    # 1. පද්ධතියේ කලින් තිබේදැයි පරීක්ෂා කිරීම
    existing_file = await links_col.find_one({"file_id": file_id})
    
    if existing_file:
        res_text = f"♻️ **කලින් සකස් කරන ලද Link එක:**\n\n" + existing_file['text']
        return await event.respond(res_text, link_preview=False)

    prog_msg = await event.respond("අලුත් Link එකක් සකසමින් පවතිනවා... ⏳")
    
    try:
        forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
        file_name = event.file.name or "video.mp4"
        clean_name = urllib.parse.quote(file_name)
        
        dl_link = f"{STREAM_URL}/download/{forwarded.id}?name={clean_name}"
        watch_link = f"{STREAM_URL}/watch/{forwarded.id}?name={clean_name}"
        
        res_text = (
            f"📁 **File:** `{file_name}`\n"
            f"📊 **Size:** {event.file.size / (1024*1024):.2f} MB\n\n"
            f"📥 [Direct Download]({dl_link})\n"
            f"🎬 [Online Stream]({watch_link})"
        )

        # 2. අනාගත ප්‍රයෝජනය සඳහා Database එකේ සේව් කිරීම
        await links_col.insert_one({
            "file_id": file_id,
            "text": res_text,
            "msg_id": forwarded.id
        })

        await prog_msg.edit(f"✅ **Links Generated!**\n\n{res_text}", link_preview=False)
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await prog_msg.edit("දෝෂයක් සිදු විය.")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    client.loop.create_task(app.run_task(host='0.0.0.0', port=port))
    client.run_until_disconnected()
