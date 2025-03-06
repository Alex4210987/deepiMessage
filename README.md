# deepiMessage

A Python library for sending and receiving iMessages on macOS. 

## Usage

install the following dependencies:

```bash
pip install sqlite3
pip install typedstream
pip install python-dotenv
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

## TODO

- Use deepseek or other LLMs to answer questions
- Integrate with websearch
- Set schedules and reminders