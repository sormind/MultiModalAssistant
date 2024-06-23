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