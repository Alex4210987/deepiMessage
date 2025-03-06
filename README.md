# deepiMessage

A Python applocation for sending and receiving iMessages on macOS. 

## Usage

install the following dependencies:

```bash
pip install python-dotenv aiosqlite pytypedstream
```

run main.py

```bash
python main.py
```

## Features

- Send iMessages:
  An AppleScript will be executed to send iMessages to the target user.
- Receive iMessages:
  The SQLite database will be queried to get the latest iMessages received.
- Reminders:
  Send reminder messages to the target user.

## TODO

- Use deepseek or other LLMs to answer questions
- Integrate with websearch
- Set schedules