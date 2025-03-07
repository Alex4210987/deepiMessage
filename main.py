import asyncio
import aiosqlite
import os
import time
from datetime import datetime, date, timedelta
import random
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
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-reasoner") # Added default value
DEEPSEEK_FALLBACK_MODEL = "deepseek-chat"

# Reminder Schedule (可自定义提示词)
REMINDER_SCHEDULE = [
    {
        "time": "08:55",
        "prompt": "生成自然唤醒提示，建议起床学习。要求：中文配五言诗句开头，50字以内。"
    },
    {
        "time": "10:00",
        "prompt": "补水时间提醒，建议饮用温水并活动肩颈。要求：中文押韵口诀，40字左右。"
    },
    {
        "time": "13:15",
        "prompt": "餐后养生提醒，建议仙人揉腹法教学。要求：中文步骤说明，60字以内。"
    },
    {
        "time": "16:20",
        "prompt": "黄昏能量提醒，建议锻炼身体。要求：中文带励志名言引用，55字以内。"
    },
    {
        "time": "20:45",
        "prompt": "数码排毒提醒，建议纸质书阅读时段。要求：中文诗意表达，带诗歌意象。"
    },
    {
        "time": "21:10",
        "prompt": "足浴养生提醒，建议中药泡脚配方。要求：中医术语通俗化，50字左右。"
    },
    {
        "time": "23:00",
        "prompt": "生物钟校准提醒，建议478呼吸法指导。要求：中文步骤可视化描述，60字以内。"
    }
]

# Track sent reminders
last_sent_dates = {}

# Work hours configuration
WORK_START_HOUR = 9  # 9:00 AM
WORK_END_HOUR = 18  # 6:00 PM
STUDY_CHECK_INTERVAL_MINUTES = 60  # Check every hour
STUDY_CHECK_PROMPT = "给出一段话，询问在学什么，鼓励对方好好学习。要求：中文，100字以内"
LAST_STUDY_CHECK_TIME = None  # Initialize last study check time
MESSAGE_WINDOW = 10  # Collect messages within this many seconds

# Global flag to indicate if message processing is ongoing
processing_messages = False

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
    """Generates a response using the DeepSeek API asynchronously with retry logic and fallback model."""
    if not DEEPSEEK_API_KEY:
        print("Error: Missing DEEPSEEK_API_KEY in .env file")
        return None

    api_url = f"{DEEPSEEK_BASE_URL}/chat/completions"
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

    retries = 1  # Reduced retries for deepseek-reasoner
    for attempt in range(retries):
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(api_url, headers=headers, json=data, timeout=30)
                response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
                return response.json()["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as e:
                print(f"DeepSeek API Error: HTTPStatusError - {e}")
                if DEBUG:
                    print(f"Response content: {e.response.content.decode()}")  # Print response content for debugging
                return None
            except httpx.RequestError as e:
                print(f"DeepSeek API Error: RequestError - Attempt {attempt + 1}/{retries} using {DEEPSEEK_MODEL}- {e}")
                if attempt < retries - 1:  # Don't wait after the last attempt
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
            except Exception as e:
                print(f"DeepSeek API Error: General Exception - {e}")
                return None

    # If deepseek-reasoner fails, try deepseek-chat once
    print(f"{DEEPSEEK_MODEL} failed after {retries} attempts.  Trying {DEEPSEEK_FALLBACK_MODEL}.")

    data["model"] = DEEPSEEK_FALLBACK_MODEL  # Switch to fallback model
    # timeout limit: 90s
    async with httpx.AsyncClient(timeout=900.0) as client:
        try:
            response = await client.post(api_url, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:  # Catch all exceptions for the fallback attempt
            print(f"DeepSeek API Error: {DEEPSEEK_FALLBACK_MODEL} failed: {e}")
            return None

async def fetch_new_messages(phone_numbers, database_path, scan_interval):
    """Fetches new messages from the database."""
    SQL_QUERY = f"""
    SELECT T1.ROWID, T1.text, T1.attributedBody, T3.chat_identifier, T1.date
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


async def process_messages(messages, config):
    """Processes a batch of messages, combining them into a single prompt."""

    if not messages:
        return

    # Group messages by chat_identifier
    grouped_messages = {}
    for rowid, text, attributed_body, chat_identifier, timestamp in messages:
        if chat_identifier not in grouped_messages:
            grouped_messages[chat_identifier] = []
        grouped_messages[chat_identifier].append((rowid, text, attributed_body, timestamp))

    use_ai = os.getenv("USE_AI", "False").lower() == "true"
    if not use_ai:
        return

    for chat_identifier, message_list in grouped_messages.items():
        # Sort messages by timestamp
        message_list.sort(key=lambda x: x[3])

        # Collect messages within the MESSAGE_WINDOW
        prompt_messages = []
        last_message_time = None
        combined_content = ""

        for rowid, text, attributed_body, timestamp in message_list:
            content = text or decode_attributed_body(attributed_body)
            if not content:
                if DEBUG:
                    print(f"Skipping empty message: {rowid}")
                continue

            message_time = datetime.fromtimestamp(timestamp / 1000000000)  # Convert timestamp to datetime

            if last_message_time is None or (message_time - last_message_time).total_seconds() <= MESSAGE_WINDOW:
                combined_content += f"\n{content}"
                last_message_time = message_time
            else:
                # Process the previous combined content
                if combined_content:
                    print(f"Received combined message: {combined_content[:100]}...")
                    response = await generate_response(combined_content)

                    if response:
                        print(f"Generated response: {response[:100]}...")
                        if REPLY_TO_SENDER:
                            await send_message_applescript(
                                chat_identifier,  # Send it back to the original sender
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

                # Start a new combined content with the current message
                combined_content = content
                last_message_time = message_time

        # Process any remaining combined content
        if combined_content:
            print(f"Received combined message: {combined_content[:100]}...")
            response = await generate_response(combined_content)

            if response:
                print(f"Generated response: {response[:100]}...")
                if REPLY_TO_SENDER:
                    await send_message_applescript(
                        chat_identifier,  # Send it back to the original sender
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
    processing_messages = False  # Reset the flag when done


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


async def check_study_time():
    """Randomly check if the person is studying during work hours with a probability.
    If triggered, sends immediately without delay.
    """
    global LAST_STUDY_CHECK_TIME
    now = datetime.now()
    current_hour = now.hour
    probability = 1 / 20  # Set the probability (1/100 in this case)

    # Check if it's within work hours
    if WORK_START_HOUR <= current_hour < WORK_END_HOUR:
        # Only check if enough time has passed since the last check
        if LAST_STUDY_CHECK_TIME is None or (now - LAST_STUDY_CHECK_TIME) >= timedelta(minutes=STUDY_CHECK_INTERVAL_MINUTES):
            # Generate a random number between 0 and 1
            if random.random() < probability:
                # The random number is less than the probability, so proceed with the check *immediately*
                print("Checking if studying...")
                response = await generate_response(STUDY_CHECK_PROMPT)
                if response:
                    for number in PHONE_NUMBERS:
                        await send_message_applescript(number, response, APPLESCRIPT_PATH)
                    print("Sent study check prompt.")
                else:
                    print("Failed to generate study check prompt.")

                LAST_STUDY_CHECK_TIME = datetime.now()  # Update the last check time
            else:
                # The random number is greater than or equal to the probability, so skip the check
                print("Skipping study check due to random probability.")
        else:
            # It hasn't been long enough since the last check, so skip this time
            print("Skipping study check, not enough time has passed since the last check.")


async def main():
    """Main function."""
    global processing_messages

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
            # Fetch and process incoming messages
            messages = await fetch_new_messages(
                PHONE_NUMBERS,
                DATABASE_PATH,
                SCAN_INTERVAL
            )

            if messages:
                print(f"Found {len(messages)} new messages")
                asyncio.create_task(process_messages(messages, config)) # Pass the list of messages
            else:
                print("No new messages at:", datetime.now().strftime("%H:%M:%S"))

            # Check scheduled reminders
            await check_reminders()
            print("Checked reminders")

            # Check study time
            await check_study_time()
            print("Checked study time")

            print("Wait for", SCAN_INTERVAL, "seconds")
            time.sleep(SCAN_INTERVAL)

    except KeyboardInterrupt:
        print("Program exiting")

if __name__ == "__main__":
    if not is_mac():
        print("This script only supports macOS")
        exit(1)

    asyncio.run(main())