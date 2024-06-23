import json
import os

CONFIG_FILE = 'config.json'
DEFAULT_ICON_FILE = 'icon.png'

default_config = {
    'voice': 'Antoni',
    'language': 'en',
    'max_memory': 10,
    'screenshot_dir': 'screenshots',
    'feedback_log_file': 'feedback.json',
    'cancel_hotkey': 'ctrl+c'
}

def create_default_icon():
    if not os.path.exists(DEFAULT_ICON_FILE):
        from PIL import Image
        img = Image.new('RGB', (64, 64), color = (73, 109, 137))
        img.save(DEFAULT_ICON_FILE)

def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(default_config)
        print(f"Created default configuration file: {CONFIG_FILE}")
    
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def ensure_directories(config):
    os.makedirs(config['screenshot_dir'], exist_ok=True)

def initialize_config():
    config = load_config()
    ensure_directories(config)
    create_default_icon()
    return config

config = initialize_config()