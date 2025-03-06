import subprocess
import sqlite3
import os
import time
from dotenv import load_dotenv
from typedstream.stream import TypedStreamReader

load_dotenv()

# Configuration loaded from .env file
DATABASE_PATH = os.path.expanduser(os.getenv("DATABASE_PATH", "~/Library/Messages/chat.db"))
PHONE_NUMBER = os.getenv("PHONE_NUMBER")
APPLESCRIPT_PATH = os.getenv("APPLESCRIPT_PATH", "./SendMessage.scpt")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "10"))  # Seconds
DEBUG = os.getenv("DEBUG", "False").lower() == "true"  # Enable/disable debug messages

def decode_attributed_body(data):
    """Decode attributedBody."""
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
    """Send message using AppleScript."""
    try:
        result = subprocess.run(['osascript', applescript_path, message, recipient], check=True, capture_output=True, text=True)
        if DEBUG:
            print(f"send_message_applescript output: {result.stdout}")
        print(f"消息发送给 {recipient} 成功!")
    except subprocess.CalledProcessError as e:
        print(f"AppleScript 执行失败: {e.stderr}")
    except FileNotFoundError:
        print(f"找不到 AppleScript 文件: {applescript_path}")
    except Exception as e:
        print(f"发送消息时出错: {e}")

def is_message_from_me(message_id, db_path):
    """Check if message was sent by the current user."""
    query = "SELECT is_from_me FROM message WHERE ROWID = ?"
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(query, (message_id,))
        result = cursor.fetchone()
        return result[0] == 1 if result else False
    except sqlite3.Error as e:
        print(f"数据库错误: {e}")
        return False
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def fetch_new_messages(phone_number, database_path, scan_interval):
    """Fetch new messages from the specified chat (sent by others)."""
    SQL_QUERY = """
    SELECT T1.ROWID, T1.text, T1.attributedBody
    FROM message T1
    INNER JOIN chat_message_join T2 ON T1.ROWID = T2.message_id
    INNER JOIN chat T3 ON T2.chat_id = T3.ROWID
    WHERE T3.chat_identifier = ?
    AND T1.is_from_me = 0  -- Only messages NOT from me
    AND datetime(T1.date/1000000000 + strftime('%s','2001-01-01'), 'unixepoch', 'localtime') > datetime('now','localtime','-? second')
    ORDER BY T1.date;
    """.replace("-?", f"-{SCAN_INTERVAL}")


    try:
        conn = sqlite3.connect(database_path)
        cursor = conn.cursor()
        cursor.execute(SQL_QUERY, (phone_number, ))
        messages = cursor.fetchall()

        return messages

    except sqlite3.Error as e:
        print(f"数据库错误: {e}")
        return []
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def process_message(message, config):
    """Process a single message: decode, check for content, and send."""
    rowid, text, attributed_body = message
    content = text or decode_attributed_body(attributed_body)

    if not content:
        if DEBUG:
            print(f"Skipping empty message with rowid: {rowid}")
        return

    print(f"发送内容: {content[:50]}...")
    send_message_applescript(config['phone_number'], content, config['applescript_path'])

def main():
    # Load configuration
    phone_number = os.getenv("PHONE_NUMBER")
    applescript_path = os.getenv("APPLESCRIPT_PATH", "./SendMessage.scpt")
    database_path = os.path.expanduser(os.getenv("DATABASE_PATH", "~/Library/Messages/chat.db"))
    scan_interval = int(os.getenv("SCAN_INTERVAL", "10"))

    config = {
        "phone_number": phone_number,
        "applescript_path": applescript_path,
        "database_path": database_path
    }

    # Get receiving number
    input_num = input(f"输入接收号码 (默认: {config['phone_number']}): ")
    config['phone_number'] = input_num.strip() or config['phone_number']
    print(f"当前号码: {config['phone_number']}")

    try:
        while True:
            new_messages = fetch_new_messages(config['phone_number'], config['database_path'], scan_interval)

            if new_messages:
                print(f"找到 {len(new_messages)} 条新消息...")
                for message in new_messages:
                    process_message(message, config)
            else:
                print(f"在过去的 {scan_interval} 秒内没有找到新消息.")

            time.sleep(scan_interval)

    except KeyboardInterrupt:
        print("程序退出")

if __name__ == "__main__":
    if os.uname().sysname != 'Darwin':
        print("该脚本只能在 macOS 系统运行")
        exit(1)

    main()