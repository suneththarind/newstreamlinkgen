import os
import logging
import urllib.parse
import asyncio
from telethon import TelegramClient, events
from quart import Quart, Response, request
from dotenv import load_dotenv

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# --- Config ---
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
BIN_CHANNEL = int(os.getenv('BIN_CHANNEL'))
STREAM_URL = os.getenv('STREAM_URL').rstrip('/')  # අන්තිමට / තිබේ නම් ඉවත් කරයි

app = Quart(__name__)
client = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

@app.route('/')
async def index():
    return "🚀 High-Speed Direct Download Server is Online!"

# --- ස්ථාවර Generator එක (මෙය ලොකු ෆයිල් වලට ඉතා වැදගත් වේ) ---
async def file_generator(file_msg, start, end):
    CHUNK_SIZE = 1024 * 1024  # 1MB chunks
    offset = start
    
    while offset <= end:
        # ඉතිරිව ඇති බයිට් ප්‍රමාණය ගණනය කිරීම
        remaining = end - offset + 1
        current_limit = min(CHUNK_SIZE, remaining)
        
        try:
            async for chunk in client.iter_download(
                file_msg.media,
                offset=offset,
                limit=current_limit,
                request_size=CHUNK_SIZE
            ):
                yield chunk
                offset += len(chunk)
                
            if current_limit == 0:
                break
        except Exception as e:
            logger.error(f"Error while generating chunks: {e}")
            break

@app.route('/download/<int:msg_id>')
@app.route('/watch/<int:msg_id>')
async def stream_handler(msg_id):
    try:
        # BIN_CHANNEL එකෙන් අදාළ පණිවිඩය ලබා ගැනීම
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not file_msg or not file_msg.file:
            return "File Not Found or Message Deleted", 404

        file_size = file_msg.file.size
        file_name = file_msg.file.name or f"file_{msg_id}.mp4"
        mime_type = file_msg.file.mime_type or 'application/octet-stream'
        
        # Range Header එක පරීක්ෂා කිරීම (Resume support සඳහා)
        range_header = request.headers.get('Range', None)
        start_byte = 0
        end_byte = file_size - 1

        if range_header:
            # bytes=0-1024 වැනි format එකෙන් දත්ත වෙන් කිරීම
            range_parts = range_header.replace('bytes=', '').split('-')
            start_byte = int(range_parts[0])
            if range_parts[1]:
                end_byte = int(range_parts[1])

        headers = {
            'Content-Type': mime_type,
            'Accept-Ranges': 'bytes',
            'Content-Length': str(end_byte - start_byte + 1),
            'Cache-Control': 'no-cache',
            'Content-Disposition': f'attachment; filename="{file_name}"',
        }

        # Range request එකක් නම් 206 Status එක ලබා දීම
        status_code = 200
        if range_header:
            headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{file_size}'
            status_code = 206

        return Response(
            file_generator(file_msg, start_byte, end_byte),
            status=status_code,
            headers=headers
        )

    except Exception as e:
        logger.error(f"Streaming Error: {str(e)}")
        return "Internal Server Error", 500

# --- Bot Events ---
@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.respond('👋 **ආයුබෝවන්!**\n\nඕනෑම File එකක් එවන්න, මම බාධාවකින් තොරව High Speed Download & Stream Links ලබා දෙන්නම්.\n\n⚠️ **වැදගත්:** ලොකු ෆයිල් Download කිරීමට IDM හෝ ADM වැනි Download Manager එකක් භාවිතා කරන්න.')

@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    prog_msg = await event.respond("Links සකසමින් පවතිනවා... ⏳")
    try:
        # BIN_CHANNEL එකට forward කිරීම (ස්ථාවරත්වය සඳහා)
        forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
        
        file_name = event.file.name or "video.mp4"
        clean_name = urllib.parse.quote(file_name)
        
        # Links සෑදීම
        dl_link = f"{STREAM_URL}/download/{forwarded.id}?name={clean_name}"
        watch_link = f"{STREAM_URL}/watch/{forwarded.id}?name={clean_name}"
        
        res_text = (
            f"✅ **Links Generated Successfully!**\n\n"
            f"📁 **File Name:** `{file_name}`\n"
            f"📊 **File Size:** {event.file.size / (1024*1024):.2f} MB\n\n"
            f"📥 **Direct Download:** [Click to Download]({dl_link})\n"
            f"🎬 **Online Stream:** [Click to Watch]({watch_link})\n\n"
            f"🚀 *වේගවත් අත්දැකීමක් සඳහා IDM භාවිතා කරන්න.*"
        )
        await prog_msg.edit(res_text, link_preview=False)
        
    except Exception as e:
        logger.error(f"Bot Error: {e}")
        await prog_msg.edit("යම් දෝෂයක් සිදු විය. නැවත උත්සාහ කරන්න.")

# --- Main Run ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    # Quart සහ Telethon එකට වැඩ කිරීමට loop එකට ඇතුළත් කිරීම
    client.loop.create_task(app.run_task(host='0.0.0.0', port=port))
    client.run_until_disconnected()
