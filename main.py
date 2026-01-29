import os
import time
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

START_TIME = time.time()

@app.route('/')
async def index():
    return "🚀 Multi-File High-Speed Server is Online!"

# --- Optimized High-Speed Generator ---
async def file_generator(file_msg, start, end):
    # 1MB Chunks for faster data flow
    CHUNK_SIZE = 1024 * 1024 
    
    async for chunk in client.iter_download(
        file_msg.media,
        offset=start,
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
        file_name = file_msg.file.name or f"file_{msg_id}"
        
        # ඕනෑම file type එකක් support කිරීම සඳහා mime_type ලබා ගැනීම
        mime_type = file_msg.file.mime_type or 'application/octet-stream'
        
        range_header = request.headers.get('Range', None)
        start_byte = 0
        end_byte = file_size - 1

        if range_header:
            range_parts = range_header.replace('bytes=', '').split('-')
            start_byte = int(range_parts[0])
            if len(range_parts) > 1 and range_parts[1]:
                end_byte = int(range_parts[1])

        # Streaming support (inline) for media files
        is_watch = 'watch' in request.path
        disposition = 'inline' if is_watch else 'attachment'
        
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
        logger.error(f"Error: {e}")
        return "Internal Error", 500

# --- Bot Commands ---

@client.on(events.NewMessage(pattern='/start'))
async def start_cmd(event):
    await event.respond(
        "👋 **ආයුබෝවන්!**\n\nමම ඕනෑම ගොනුවක් Direct Download Link එකක් බවට පත් කරන Bot කෙනෙක්.\n\n"
        "📂 **භාවිතා කරන ආකාරය:** ඕනෑම File එකක් මට එවන්න.\n"
        "⚡ **වේගය:** Unlimited High Speed.\n"
        "🛠 **Commands:** /ping, /help"
    )

@client.on(events.NewMessage(pattern='/ping'))
async def ping_cmd(event):
    start = time.time()
    msg = await event.respond("Pinging...")
    end = time.time()
    uptime = time.strftime("%Hh %Mm %Ss", time.gmtime(time.time() - START_TIME))
    await msg.edit(f"🚀 **Pong!**\n🛰 **Latency:** {round((end - start) * 1000)}ms\n⏰ **Uptime:** `{uptime}`")

@client.on(events.NewMessage(pattern='/help'))
async def help_cmd(event):
    await event.respond("උදව් අවශ්‍යද? ඕනෑම File එකක් හෝ Video එකක් මට Forward කරන්න. මම ඔබට එය බාගත කරගැනීමට හෝ Online නැරඹීමට හැකි සබැඳි (Links) ලබා දෙන්නම්.")

# --- File Handler with MongoDB ---
@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    file_id = event.file.id
    
    # Duplicate Check
    existing = await links_col.find_one({"file_id": file_id})
    if existing:
        return await event.respond(f"♻️ **කලින් සකස් කළ Link එක:**\n\n{existing['text']}", link_preview=False)

    prog = await event.respond("Processing File... ⏳")
    
    try:
        forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
        file_name = event.file.name or "file"
        clean_name = urllib.parse.quote(file_name)
        
        dl_link = f"{STREAM_URL}/download/{forwarded.id}?name={clean_name}"
        watch_link = f"{STREAM_URL}/watch/{forwarded.id}?name={clean_name}"
        
        # File type එක අනුව icon එක වෙනස් කිරීම
        icon = "🎬" if event.file.mime_type and "video" in event.file.mime_type else "📂"
        
        res_text = (
            f"{icon} **File:** `{file_name}`\n"
            f"📊 **Size:** {event.file.size / (1024*1024):.2f} MB\n\n"
            f"📥 [Direct Download]({dl_link})\n"
            f"🎬 [Online Stream]({watch_link})\n\n"
            f"🚀 *Fastest link generated for you!*"
        )

        await links_col.insert_one({"file_id": file_id, "text": res_text})
        await prog.edit(f"✅ **Links Generated!**\n\n{res_text}", link_preview=False)
        
    except Exception as e:
        logger.error(f"Bot Error: {e}")
        await prog.edit("දෝෂයක් සිදු විය. කරුණාකර නැවත උත්සාහ කරන්න.")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    client.loop.create_task(app.run_task(host='0.0.0.0', port=port))
    client.run_until_disconnected()
