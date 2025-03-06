import subprocess
import sqlite3
import os
import time
from dotenv import load_dotenv
from typedstream.stream import TypedStreamReader

load_dotenv()

# Configuration loaded from .env file
DATABASE_PATH = os.path.expanduser(os.getenv("DATABASE_PATH", "~/Library/Messages/chat.db"))
PHONE_NUMBER = os.getenv("PHONE_NUMBER")  # Required in .env
APPLESCRIPT_PATH = os.getenv("APPLESCRIPT_PATH", "./SendMessage.scpt")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "10"))  # Seconds
DEBUG = os.getenv("DEBUG", "False").lower() == "true"  # Enable/disable debug messages

def decode_attributed_body(data):
    """Decodes the attributedBody."""
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

def send_message_applescript(recipient, message, applescript_path):
    """Sends a message using AppleScript."""
    try:
        result = subprocess.run(['osascript', applescript_path, message, recipient], check=True, capture_output=True, text=True)
        if DEBUG:
            print(f"send_message_applescript output: {result.stdout}")
        print(f"Message sent to {recipient} successfully!")
    except subprocess.CalledProcessError as e:
        print(f"AppleScript execution failed: {e.stderr}")
    except FileNotFoundError:
        print(f"AppleScript file not found: {applescript_path}")
    except Exception as e:
        print(f"Error sending message: {e}")

def fetch_new_messages(phone_number, database_path, scan_interval):
    """Fetches new messages from the specified chat (sent by others) within the scan interval."""
    SQL_QUERY = """
    SELECT T1.ROWID, T1.text, T1.attributedBody
    FROM message T1
    INNER JOIN chat_message_join T2 ON T1.ROWID = T2.message_id
    INNER JOIN chat T3 ON T2.chat_id = T3.ROWID
    WHERE T3.chat_identifier = ?
    AND T1.is_from_me = 0  -- Only messages NOT from me
    AND datetime(T1.date/1000000000 + strftime('%s','2001-01-01'), 'unixepoch', 'localtime') > datetime('now','localtime', '-{} second')
    ORDER BY T1.date;
    """.format(scan_interval)  # Insert scan_interval directly into the query

    try:
        conn = sqlite3.connect(database_path)
        cursor = conn.cursor()
        cursor.execute(SQL_QUERY, (phone_number,))
        messages = cursor.fetchall()

        return messages

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return []
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def process_message(message, config):
    """Processes a single message: decode, check for content, and send."""
    rowid, text, attributed_body = message
    content = text or decode_attributed_body(attributed_body)

    if not content:
        if DEBUG:
            print(f"Skipping empty message with rowid: {rowid}")
        return

    print(f"Sending content: {content[:50]}...")
    send_message_applescript(config['phone_number'], content, config['applescript_path'])

def main():
    """Main function to run the iMessage monitoring script."""
    # Load configuration
    phone_number = os.getenv("PHONE_NUMBER")
    if not phone_number:
        print("Error: PHONE_NUMBER must be set in the .env file.")
        return  # Exit if PHONE_NUMBER is not set

    applescript_path = os.getenv("APPLESCRIPT_PATH", "./SendMessage.scpt")
    database_path = os.path.expanduser(os.getenv("DATABASE_PATH", "~/Library/Messages/chat.db"))
    scan_interval = int(os.getenv("SCAN_INTERVAL", "10"))

    config = {
        "phone_number": phone_number,
        "applescript_path": applescript_path,
        "database_path": database_path
    }

    print(f"Monitoring phone number: {config['phone_number']}")

    try:
        while True:
            new_messages = fetch_new_messages(config['phone_number'], config['database_path'], scan_interval)

            if new_messages:
                print(f"Found {len(new_messages)} new messages...")
                for message in new_messages:
                    process_message(message, config)
            else:
                print(f"No new messages found in the last {scan_interval} seconds.")

            time.sleep(scan_interval)

    except KeyboardInterrupt:
        print("Program exiting.")

if __name__ == "__main__":
    if os.uname().sysname != 'Darwin':
        print("This script can only be run on macOS.")
        exit(1)

    main()