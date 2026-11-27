from datetime import datetime

def log(text: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}]\t{text}")
