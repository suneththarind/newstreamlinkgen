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

# Config
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
BIN_CHANNEL = int(os.getenv('BIN_CHANNEL'))
STREAM_URL = os.getenv('STREAM_URL').rstrip('/') # අවසානයට / තිබේ නම් ඉවත් කරයි

app = Quart(__name__)
client = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

@app.route('/')
async def index():
    return "🚀 High-Speed Direct Download Server is Online!"

# --- මෙතන තමයි වැදගත්ම කොටස: දත්ත බෙදා හරින Generator එක ---
async def file_generator(file_msg, start, end, chunk_size):
    offset = start
    while offset <= end:
        # ඉතිරිව ඇති බයිට් ප්‍රමාණය ගණනය කිරීම
        remaining = end - offset + 1
        current_chunk_size = min(chunk_size, remaining)
        
        # ටෙලිග්‍රෑම් එකෙන් අදාළ කොටස පමණක් ලබා ගැනීම
        async for chunk in client.iter_download(
            file_msg.media,
            offset=offset,
            limit=current_chunk_size
        ):
            yield chunk
            offset += len(chunk)
            
        if current_chunk_size == 0:
            break

@app.route('/download/<int:msg_id>')
@app.route('/watch/<int:msg_id>')
async def stream_handler(msg_id):
    try:
        file_msg = await client.get_messages(BIN_CHANNEL, ids=msg_id)
        if not file_msg or not file_msg.file:
            return "File Not Found", 404

        file_size = file_msg.file.size
        file_name = file_msg.file.name or f"file_{msg_id}.mp4"
        mime_type = file_msg.file.mime_type or 'application/octet-stream'
        
        # Range Request පාලනය (Download managers සඳහා ඉතා වැදගත්)
        range_header = request.headers.get('Range', None)
        start_byte = 0
        end_byte = file_size - 1

        if range_header:
            range_val = range_header.replace('bytes=', '').split('-')
            start_byte = int(range_val[0])
            if range_val[1]:
                end_byte = int(range_val[1])

        # Headers සැකසීම
        headers = {
            'Content-Type': mime_type,
            'Accept-Ranges': 'bytes',
            'Content-Length': str(end_byte - start_byte + 1),
            'Content-Disposition': f'attachment; filename="{file_name}"',
            'Cache-Control': 'no-cache',
        }

        if range_header:
            headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{file_size}'
            status_code = 206
        else:
            status_code = 200

        # Generator එකට දත්ත ටික ලබා දීම
        # chunk_size එක 1MB (1024*1024) ලෙස තැබීම ස්ථාවරත්වයට උදව් වේ
        return Response(
            file_generator(file_msg, start_byte, end_byte, 1024 * 1024),
            status=status_code,
            headers=headers
        )

    except Exception as e:
        logger.error(f"Streaming Error: {str(e)}")
        return "Internal Server Error", 500

# --- Bot Events ---
@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.respond('👋 සාදරයෙන් පිළිගන්නවා!\nමට ඕනෑම File එකක් එවන්න, මම බාධාවකින් තොරව High Speed Download & Stream Links ලබා දෙන්නම්.')

@client.on(events.NewMessage(incoming=True, func=lambda e: e.media))
async def handle_media(event):
    prog_msg = await event.respond("Links සකසමින් පවතිනවා... ⏳")
    try:
        # BIN_CHANNEL එකට forward කිරීම
        forwarded = await client.forward_messages(BIN_CHANNEL, event.message)
        
        file_name = event.file.name or "video.mp4"
        # URL එකේ නමට පාවිච්චි කළ නොහැකි අකුරු ඉවත් කිරීම (Safe Encoding)
        encoded_name = urllib.parse.quote(file_name)
        
        dl_link = f"{STREAM_URL}/download/{forwarded.id}?name={encoded_name}"
        stream_link = f"{STREAM_URL}/watch/{forwarded.id}?name={encoded_name}"
        
        res_text = (
            f"✅ **Links Ready!**\n\n"
            f"📁 **File:** `{file_name}`\n"
            f"📊 **Size:** {event.file.size / (1024*1024):.2f} MB\n\n"
            f"📥 **Direct Download:** [Click Here]({dl_link})\n"
            f"🎬 **Online Stream:** [Watch Now]({stream_link})\n\n"
            f"ℹ️ *ලොකු ෆයිල් Download කිරීමේදී IDM වැනි App එකක් භාවිතා කරන්න.*"
        )
        await prog_msg.edit(res_text, link_preview=False)
        
    except Exception as e:
        logger.error(f"Bot Error: {e}")
        await prog_msg.edit("යම් දෝෂයක් සිදු විය. නැවත උත්සාහ කරන්න.")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    # Quart සහ Telethon එකට වැඩ කිරීමට සැලැස්වීම
    client.loop.create_task(app.run_task(host='0.0.0.0', port=port))
    client.run_until_disconnected()
