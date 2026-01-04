
import os
import logging
import urllib.parse
import asyncio
from telethon import TelegramClient, events
from pymongo import MongoClient
from quart import Quart, Response, request, stream_with_context
from dotenv import load_dotenv

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
BIN_CHANNEL = int(os.getenv('BIN_CHANNEL'))
DATABASE_URL = os.getenv('DATABASE_URL')
STREAM_URL = os.getenv('STREAM_URL')

app = Quart(__name__)
client = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

mongo_client = MongoClient(DATABASE_URL)
db = mongo_client['file_to_link']
files_collection = db['stored_files']

@app.route('/')
async def index():
    return "Memory Optimized Stream Server is Online! 🚀"

# --- RAM එක පාවිච්චි නොවන පරිදි Streaming කිරීම ---
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
        end_byte = file_size - 1

        if range_header:
            ranges = range_header.replace('bytes=', '').split('-')
            start_byte = int(ranges[0])
            if ranges[1]:
                end_byte = int(ranges[1])

        # මෙහිදී stream_with_context භාවිතා කර දත්ත ටික ටික (Chunk by Chunk) යවයි
        @stream_with_context
        async def generate():
            # Chunk size එක 128KB වැනි කුඩා අගයකට තැබීමෙන් RAM එක ආරක්ෂා වේ
            chunk_size = 128 * 1024 
            try:
                async for chunk in client.iter_download(
                    file_msg.media, 
                    offset=start_byte, 
                    limit=end_byte - start_byte + 1,
                    chunk_size=chunk_size
                ):
                    yield chunk
                    # දත්ත යැවූ පසු පොඩි විරාමයක් ලබා දීමෙන් CPU එකට සහ RAM එකට සහනයක් ලැබේ
                    await asyncio.sleep(0.001) 
            except Exception as e:
                logger.error(f"Download Interrupted: {e}")

        headers = {
            'Content-Type': mime_type,
            'Accept-Ranges': 'bytes',
            'Content-Length': str(end_byte - start_byte + 1),
            'Cache-Control': 'public, max-age=3600',
        }

        if range_header:
            headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{file_size}'

        if is_download:
            headers['Content-Disposition'] = f'attachment; filename="{file_name}"'
        else:
            headers['Content-Disposition'] = f'inline; filename="{file_name}"'

        return Response(generate(), status=206 if range_header else 200, headers=headers)

    except Exception as e:
        logger.error(f"Server Error: {e}")
        return "Internal Server Error", 500

# --- Bot Logic ---
@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.respond('ආයුබෝවන්! දැන් වඩාත් ස්ථාවරව ඩවුන්ලෝඩ් කළ හැකි ලෙස සකසා ඇත. 🎬')

@client.on(events.NewMessage(incoming=True, func=lambda e: e.video or e.document))
async def handle_media(event):
    msg = await event.respond("ලින්ක් සකසමින් පවතිනවා... ⏳")
    try:
        forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
        file_name = event.file.name or "video.mp4"
        clean_name = urllib.parse.quote(file_name)
        
        watch_link = f"{STREAM_URL}/watch/{forwarded.id}?name={clean_name}"
        download_link = f"{STREAM_URL}/download/{forwarded.id}?name={clean_name}"
        
        await msg.edit(
            f"✅ **Links Generated!**\n\n🎬 **Name:** `{file_name}`\n\n🔗 **Stream:** `{watch_link}`\n📥 **Download:** `{download_link}`",
            link_preview=False
        )
    except Exception as e:
        await msg.edit(f"Error: {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    # Quart run එකේදී use_reloader=False දැමීමෙන් RAM භාවිතය තවත් අඩු වේ
    client.loop.create_task(app.run_task(host='0.0.0.0', port=port, use_reloader=False))
    client.run_until_disconnected()
