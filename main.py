import os
import logging
import urllib.parse
import asyncio
from telethon import TelegramClient, events
from pymongo import MongoClient
from quart import Quart, Response, request
from dotenv import load_dotenv

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Config
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
BIN_CHANNEL = int(os.getenv('BIN_CHANNEL'))
DATABASE_URL = os.getenv('DATABASE_URL')
STREAM_URL = os.getenv('STREAM_URL') 

# App and Client
app = Quart(__name__)
client = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# MongoDB
mongo_client = MongoClient(DATABASE_URL)
db = mongo_client['file_to_link']
files_collection = db['stored_files']

@app.route('/')
async def index():
    return "Stream & Download Server is Online! 🚀"

# --- Stream & Download Handler ---
@app.route('/watch/<int:msg_id>')
@app.route('/download/<int:msg_id>')
async def stream_handler(msg_id):
    try:
        is_download = 'download' in request.path
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not file_msg or not file_msg.file:
            return "File Not Found", 404

        file_size = file_msg.file.size
        file_name = file_msg.file.name or "video.mp4"
        mime_type = file_msg.file.mime_type or 'video/mp4'
        
        range_header = request.headers.get('Range', None)
        start_byte = 0
        if range_header:
            start_byte = int(range_header.replace('bytes=', '').split('-')[0])

        async def generate():
            # ටෙලිග්‍රෑම් එකෙන් බයිට්ස් ලබාගෙන ප්ලේයර් එකට යැවීම
            async for chunk in client.iter_download(file_msg.media, offset=start_byte, chunk_size=1024*1024):
                yield chunk

        headers = {
            'Content-Type': mime_type,
            'Content-Range': f'bytes {start_byte}-{file_size-1}/{file_size}',
            'Accept-Ranges': 'bytes',
            'Content-Length': str(file_size - start_byte),
        }

        if is_download:
            # බ්‍රවුසරයට ෆයිල් එකක් ලෙස සලකන ලෙස දැනුම් දීම
            headers['Content-Disposition'] = f'attachment; filename="{file_name}"'

        return Response(generate(), status=206 if range_header else 200, headers=headers)

    except Exception as e:
        logger.error(f"Error: {e}")
        return "Internal Server Error", 500

# --- Bot Events ---
@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.respond('ආයුබෝවන්! මට වීඩියෝවක් එවන්න, මම ස්ට්‍රීමිං සහ ඩවුන්ලෝඩ් ලිංක් ලබා දෙන්නම්. 🎬')

@client.on(events.NewMessage(incoming=True, func=lambda e: e.video or e.document))
async def handle_media(event):
    msg = await event.respond("ක්‍රියාවලිය සිදුවෙමින් පවතී... ⏳")
    try:
        # Bin Channel එකට යැවීම
        forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
        file_name = event.file.name or "video.mp4"
        clean_name = urllib.parse.quote(file_name)
        
        # ලිංක් සැකසීම
        watch_link = f"{STREAM_URL}/watch/{forwarded.id}?name={clean_name}"
        download_link = f"{STREAM_URL}/download/{forwarded.id}?name={clean_name}"
        
        # MongoDB හි තැන්පත් කිරීම
        files_collection.insert_one({
            'msg_id': forwarded.id,
            'name': file_name,
            'watch': watch_link,
            'download': download_link
        })

        res_text = (
            f"✅ **Links Generated!**\n\n"
            f"🎬 **Name:** `{file_name}`\n\n"
            f"🔗 **Stream Link:** `{watch_link}`\n\n"
            f"📥 **Direct Download:** `{download_link}`"
        )
        await msg.edit(res_text, link_preview=False)
    except Exception as e:
        await msg.edit(f"Error: {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    client.loop.create_task(app.run_task(host='0.0.0.0', port=port))
    client.run_until_disconnected()
