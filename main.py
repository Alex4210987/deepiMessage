import asyncio
import aiosqlite
import os
import time
from datetime import datetime, date
from dotenv import load_dotenv
from typedstream.stream import TypedStreamReader
import platform
import httpx  # Import httpx for asynchronous HTTP requests

# Load environment variables
load_dotenv()

# Configuration
DATABASE_PATH = os.path.expanduser(os.getenv("DATABASE_PATH", "~/Library/Messages/chat.db"))
PHONE_NUMBERS = [num.strip() for num in os.getenv("PHONE_NUMBERS", "").split(",") if num.strip()]
APPLESCRIPT_PATH = os.getenv("APPLESCRIPT_PATH", "./SendMessage.scpt")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "10"))
DEBUG = os.getenv("DEBUG", "True").lower() == "true"
PROMPT = os.getenv("PROMPT", "请生成一条中文回复。")
REPLY_TO_SENDER = os.getenv("REPLY_TO_SENDER", "True").lower() == "true" # Add this line
# DeepSeek Configuration
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com") # Added default value
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat") # Added default value

# Reminder Schedule (可自定义提示词)
REMINDER_SCHEDULE = [
    {
        "time": "09:00",
        "prompt": "请生成一条温馨的早餐提醒，并鼓励用户开始一天的学习和工作。要求：用中文，亲切自然，60字以内。"
    },
    {
        "time": "12:00",
        "prompt": "请生成一条午餐提醒，建议健康饮食并适当休息。要求：用中文，轻松幽默，50字左右。"
    },
    {
        "time": "18:00",
        "prompt": "请生成一条晚餐提醒，建议适量饮食并锻炼身体。要求：用中文，温暖关切，50字以内。"
    },
    {
        "time": "23:30",
        "prompt": "请生成一条睡前提醒，建议放下手机保证睡眠，用诗意的中文表达，40字以内。"
    }
]

# Track sent reminders
last_sent_dates = {}

def is_mac():
    return platform.system() == 'Darwin'


def decode_attributed_body(data):
    """Decodes rich text messages."""
    if not data:
        return None
    try:
        for event in TypedStreamReader.from_data(data):
            if isinstance(event, bytes):
                return event.decode("utf-8", errors="ignore")
    except Exception as e:
        if DEBUG:
            print(f"decode_attributed_body error: {e}")
        return None

async def send_message_applescript(recipient, message, applescript_path):
    """Sends messages via AppleScript."""
    if not is_mac():
        print("AppleScript only works on macOS.")
        return

    try:
        # Run AppleScript in a separate process to avoid blocking the event loop
        process = await asyncio.create_subprocess_exec(
            'osascript', applescript_path, message, recipient,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            print(f"AppleScript error: {stderr.decode()}")
        else:
            if DEBUG:
                print(f"Send successful: {stdout.decode()}")
            print(f"Message sent to {recipient}")

    except Exception as e:
        print(f"Send failed: {str(e)}")


async def generate_response(prompt):
    """Generates a response using the DeepSeek API asynchronously using httpx."""
    if not DEEPSEEK_API_KEY:
        print("Error: Missing DEEPSEEK_API_KEY in .env file")
        return None

    url = f"{DEEPSEEK_BASE_URL}/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    }
    data = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "temperature": 0.7,
        "max_tokens": int(os.getenv("MAX_TOKENS", "1000")),
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=data, timeout=30)
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            return response.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            print(f"DeepSeek API Error: HTTPStatusError - {e}")
            if DEBUG:
                print(f"Response content: {e.response.content.decode()}") # Print response content for debugging
            return None
        except httpx.RequestError as e:
            print(f"DeepSeek API Error: RequestError - {e}")
            return None
        except Exception as e:
            print(f"DeepSeek API Error: General Exception - {e}")
            return None


async def fetch_new_messages(phone_numbers, database_path, scan_interval):
    """Fetches new messages from the database."""
    SQL_QUERY = f"""
    SELECT T1.ROWID, T1.text, T1.attributedBody, T3.chat_identifier
    FROM message T1
    INNER JOIN chat_message_join T2 ON T1.ROWID = T2.message_id
    INNER JOIN chat T3 ON T2.chat_id = T3.ROWID
    WHERE T3.chat_identifier IN ({','.join(['?']*len(phone_numbers))})
    AND T1.is_from_me = 0
    AND datetime(T1.date/1000000000 + strftime('%s','2001-01-01'), 'unixepoch', 'localtime') > datetime('now','localtime', '-{scan_interval} second')
    ORDER BY T1.date;
    """

    try:
        async with aiosqlite.connect(database_path) as db:
            async with db.execute(SQL_QUERY, phone_numbers) as cursor:
                return await cursor.fetchall()
    except aiosqlite.Error as e:
        print(f"Database error: {e}")
        return []

async def process_message(message, config):
    """Processes a single message."""
    rowid, text, attributed_body, chat_identifier = message
    content = text or decode_attributed_body(attributed_body)

    if not content:
        if DEBUG:
            print(f"Skipping empty message: {rowid}")
        return

    use_ai = os.getenv("USE_AI", "False").lower() == "true"
    if use_ai:
        print(f"Received message: {content[:100]}...")
        response = await generate_response(content)

        if response:
            print(f"Generated response: {response[:100]}...")
            if REPLY_TO_SENDER: # Check the new env variable
                await send_message_applescript(
                    chat_identifier, # Send it back to the original sender
                    response,
                    config['applescript_path']
                )
            else:
                for number in config['phone_numbers']:
                    await send_message_applescript(
                        number,
                        response,
                        config['applescript_path']
                    )
        else:
            print("Failed to generate response")

async def check_reminders():
    """Check and send scheduled reminders."""
    current_time = datetime.now().strftime("%H:%M")
    today = date.today()

    for index, reminder in enumerate(REMINDER_SCHEDULE):
        if current_time == reminder["time"]:
            if last_sent_dates.get(index) != today:
                response = await generate_response(reminder["prompt"])
                if response:
                    for number in PHONE_NUMBERS:
                        await send_message_applescript(number, response, APPLESCRIPT_PATH)
                    last_sent_dates[index] = today
                    print(f"Sent {reminder['time']} reminder")
                else:
                    print(f"Failed to generate {reminder['time']} reminder")

async def main():
    """Main function."""
    if not PHONE_NUMBERS:
        print("Error: PHONE_NUMBERS must be configured.")
        return

    config = {
        "phone_numbers": PHONE_NUMBERS,
        "applescript_path": APPLESCRIPT_PATH,
        "database_path": DATABASE_PATH
    }

    print(f"Monitoring phone numbers: {', '.join(PHONE_NUMBERS)}")
    print("Reminder Schedule:")
    for reminder in REMINDER_SCHEDULE:
        print(f"{reminder['time']}: {reminder['prompt'][:30]}...")

    try:
        while True:
            # Process incoming messages
            messages = await fetch_new_messages(
                PHONE_NUMBERS,
                DATABASE_PATH,
                SCAN_INTERVAL
            )

            if messages:
                print(f"Found {len(messages)} new messages")
                for msg in messages:
                    await process_message(msg, config)

            # Check scheduled reminders
            await check_reminders()

            await asyncio.sleep(SCAN_INTERVAL)

    except KeyboardInterrupt:
        print("Program exiting")

if __name__ == "__main__":
    if not is_mac():
        print("This script only supports macOS")
        exit(1)

    asyncio.run(main())