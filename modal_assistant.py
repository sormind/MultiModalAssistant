import os
import time
import asyncio
import json
import base64
import subprocess
import sys
from threading import Event
from concurrent.futures import ThreadPoolExecutor
import re
from collections import deque
import uuid

import anthropic
from PIL import Image, ImageGrab
import pyautogui
from RealtimeSTT import AudioToTextRecorder
import elevenlabs
import nltk
from nltk.tokenize import word_tokenize
from nltk.tag import pos_tag
import keyboard
from dotenv import load_dotenv

from user_profile import UserProfile
from config import config, save_config
from gui import AssistantGUI, AssistantThread

# Load environment variables
load_dotenv()

# Download necessary NLTK data
nltk.download('punkt', quiet=True)
nltk.download('averaged_perceptron_tagger', quiet=True)

# Initialize clients
claude_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
elevenlabs.set_api_key(os.getenv("ELEVENLABS_API_KEY"))

class Task:
    def __init__(self, description, steps):
        self.id = str(uuid.uuid4())
        self.description = description
        self.steps = steps
        self.current_step = 0
        self.completed = False

class ModalAssistant:
    def __init__(self, username):
        self.recorder = AudioToTextRecorder()
        self.last_screenshot = None
        self.context = []
        self.memory = deque(maxlen=config['max_memory'])
        self.current_task = None
        self.task_queue = deque()
        self.feedback_log = []
        self.is_listening = True
        self.voice = config['voice']
        self.screenshot_dir = config['screenshot_dir']
        self.user_profile = UserProfile(username)
        self.recording_action = False
        self.current_recording = []

    async def capture_screenshot(self):
        screenshot = ImageGrab.grab()
        filename = f"screenshot_{int(time.time())}.png"
        filepath = os.path.join(self.screenshot_dir, filename)
        screenshot.save(filepath)
        self.last_screenshot = filepath

    def extract_important_info(self, text):
        words = word_tokenize(text)
        tagged = pos_tag(words)
        important_info = []
        for word, tag in tagged:
            if tag.startswith('NN') or tag.startswith('VB') or tag == 'JJ':
                important_info.append(word)
        return ' '.join(important_info)

    async def process_voice_command(self, command):
        if command.lower() == "cancel current task":
            return await self.cancel_current_task()
        elif command.lower().startswith("start recording action"):
            return await self.start_recording_action(command)
        elif command.lower() == "stop recording action":
            return await self.stop_recording_action()
        elif command.lower().startswith("play action"):
            return await self.play_action(command)
        elif command.lower() == "list actions":
            return await self.list_actions()
        elif command.lower().startswith("delete action"):
            return await self.delete_action(command)
        elif command.lower().startswith("edit action"):
            return await self.edit_action(command)

        await self.capture_screenshot()
        
        with open(self.last_screenshot, "rb") as img_file:
            base64_image = base64.b64encode(img_file.read()).decode('utf-8')

        important_info = self.extract_important_info(command)
        self.memory.append(important_info)

        self.context.append({"role": "user", "content": command})
        
        messages = [
            {
                "role": "system",
                "content": "You are an AI assistant capable of analyzing screenshots and executing computer commands. Provide step-by-step instructions for each action. If you need clarification, ask a question. For complex tasks, break them down into subtasks."
            },
            *self.context,
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64_image
                        }
                    },
                    {
                        "type": "text",
                        "text": f"Command: {command}\nRecent context: {list(self.memory)}\nAnalyze the screenshot and provide step-by-step instructions to execute the command. Be specific about coordinates and actions. If you need clarification, ask a question. For complex tasks, break them down into subtasks."
                    }
                ]
            }
        ]

        response = claude_client.messages.create(
            model="claude-3-opus-20240229",
            max_tokens=1000,
            messages=messages
        )

        self.context.append({"role": "assistant", "content": response.content[0].text})
        return response.content[0].text

    async def parse_and_execute_actions(self, action_description):
        actions = action_description.split('\n')
        task_steps = []
        for action in actions:
            if action.strip():
                if action.lower().startswith("subtask:"):
                    if task_steps:
                        self.task_queue.append(Task(task_steps[0], task_steps[1:]))
                        task_steps = []
                    task_steps.append(action.replace("Subtask:", "").strip())
                elif action.lower().startswith("clarification needed:"):
                    response = await self.ask_for_clarification(action)
                    task_steps.extend(response.split('\n'))
                else:
                    task_steps.append(action.strip())
        
        if task_steps:
            self.task_queue.append(Task(task_steps[0], task_steps[1:]))

        await self.execute_task_queue()

    async def execute_task_queue(self):
        while self.task_queue:
            self.current_task = self.task_queue.popleft()
            await self.text_to_speech(f"Starting task: {self.current_task.description}")
            
            for step in self.current_task.steps:
                if not self.is_listening:
                    await self.text_to_speech("Task cancelled.")
                    return
                
                await self.execute_single_action(step)
                self.current_task.current_step += 1

            self.current_task.completed = True
            await self.text_to_speech(f"Task completed: {self.current_task.description}")
            await self.get_user_feedback()

    async def cancel_current_task(self):
        if self.current_task:
            self.is_listening = False
            self.task_queue.clear()
            return "Cancelling the current task."
        else:
            return "There is no task currently running."

    async def ask_for_clarification(self, question):
        clean_question = question.replace("Clarification needed:", "").strip()
        await self.text_to_speech(clean_question)
        print(f"Assistant: {clean_question}")
        
        clarification = await self.wait_for_voice_input()
        self.context.append({"role": "user", "content": clarification})
        return await self.process_voice_command(clarification)

    async def wait_for_voice_input(self):
        while True:
            text = self.recorder.text
            if text:
                self.recorder.clear()
                return text
            await asyncio.sleep(0.1)

    async def execute_single_action(self, action):
        try:
            if self.recording_action:
                self.current_recording.append(action)

            if "click" in action.lower():
                match = re.search(r'click (?:at |on )?\(?(\d+),?\s*(\d+)\)?', action.lower())
                if match:
                    x, y = map(int, match.groups())
                    pyautogui.click(x, y)
                    print(f"Clicked at ({x}, {y})")
                else:
                    print("Couldn't parse click coordinates")

            elif "double click" in action.lower():
                match = re.search(r'double click (?:at |on )?\(?(\d+),?\s*(\d+)\)?', action.lower())
                if match:
                    x, y = map(int, match.groups())
                    pyautogui.doubleClick(x, y)
                    print(f"Double clicked at ({x}, {y})")
                else:
                    print("Couldn't parse double click coordinates")

            elif "right click" in action.lower():
                match = re.search(r'right click (?:at |on )?\(?(\d+),?\s*(\d+)\)?', action.lower())
                if match:
                    x, y = map(int, match.groups())
                    pyautogui.rightClick(x, y)
                    print(f"Right clicked at ({x}, {y})")
                else:
                    print("Couldn't parse right click coordinates")

            elif "type" in action.lower():
                match = re.search(r'type "?(.*?)"?$', action)
                if match:
                    text = match.group(1)
                    pyautogui.typewrite(text)
                    print(f"Typed: {text}")
                else:
                    print("Couldn't parse text to type")

            elif "press" in action.lower():
                key = action.lower().split("press")[-1].strip()
                pyautogui.press(key)
                print(f"Pressed key: {key}")

            elif "hotkey" in action.lower():
                keys = action.lower().split("hotkey")[-1].strip().split("+")
                pyautogui.hotkey(*keys)
                print(f"Pressed hotkey: {'+'.join(keys)}")

            elif "open" in action.lower():
                app = action.lower().split("open")[-1].strip()
                if sys.platform == "win32":
                    os.startfile(app)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", "-a", app])
                else:
                    subprocess.Popen(["xdg-open", app])
                print(f"Opened application: {app}")

            elif "wait" in action.lower():
                match = re.search(r'wait for (\d+) seconds?', action.lower())
                if match:
                    seconds = int(match.group(1))
                    await asyncio.sleep(seconds)
                    print(f"Waited for {seconds} seconds")
                else:
                    print("Couldn't parse wait duration")

            elif "scroll" in action.lower():
                match = re.search(r'scroll (up|down) (\d+)', action.lower())
                if match:
                    direction, amount = match.groups()
                    amount = int(amount)
                    if direction == "up":
                        pyautogui.scroll(amount)
                    else:
                        pyautogui.scroll(-amount)
                    print(f"Scrolled {direction} by {amount}")
                else:
                    print("Couldn't parse scroll action")

            elif "drag" in action.lower():
                match = re.search(r'drag from \(?(\d+),?\s*(\d+)\)? to \(?(\d+),?\s*(\d+)\)?', action.lower())
                if match:
                    x1, y1, x2, y2 = map(int, match.groups())
                    pyautogui.moveTo(x1, y1)
                    pyautogui.dragTo(x2, y2, duration=1)
                    print(f"Dragged from ({x1}, {y1}) to ({x2}, {y2})")
                else:
                    print("Couldn't parse drag coordinates")

            else:
                print(f"Unknown action: {action}")

        except Exception as e:
            print(f"Error executing action '{action}': {str(e)}")

    async def get_user_feedback(self):
        await self.text_to_speech("How did I do? Please provide any feedback.")
        feedback = await self.wait_for_voice_input()
        self.feedback_log.append({
            "task": self.current_task.description,
            "feedback": feedback
        })
        print(f"Feedback received: {feedback}")
        await self.text_to_speech("Thank you for your feedback.")
        
        with open(config['feedback_log_file'], 'a') as f:
            json.dump(self.feedback_log[-1], f)
            f.write('\n')

    async def text_to_speech(self, text):
        audio = elevenlabs.generate(
            text=text,
            voice=self.voice
        )
        elevenlabs.play(audio)

    async def start_recording_action(self, command):
        parts = command.split(" ", 3)
        if len(parts) < 4:
            return "Please provide a name and description for the action."
        _, _, name, description = parts
        self.recording_action = True
        self.current_recording = []
        return f"Started recording action: {name}. {description}"

    async def stop_recording_action(self):
        if not self.recording_action:
            return "No action is currently being recorded."
        self.recording_action = False
        name = self.current_recording[0].split(" ", 3)[2]
        description = self.current_recording[0].split(" ", 3)[3]
        steps = self.current_recording[1:]
        self.user_profile.save_action(name, description, steps)
        return f"Action '{name}' has been saved."

    async def play_action(self, command):
        parts = command.split(" ", 2)
        if len(parts) < 3:
            return "Please specify the name of the action to play."
        _, _, name = parts
        action = self.user_profile.get_action(name)
        if not action:
            return f"No action found with the name '{name}'."
        for step in action['steps']:
            await self.process_voice_command(step)
        return f"Completed playing action: {name}"

    async def list_actions(self):
        actions = self.user_profile.list_actions()
        if not actions:
            return "No saved actions found."
        return "Saved actions:\n" + "\n".join(actions)

    async def delete_action(self, command):
        parts = command.split(" ", 2)
        if len(parts) < 3:
            return "Please specify the name of the action to delete."
        _, _, name = parts
        if self.user_profile.delete_action(name):
            return f"Action '{name}' has been deleted."
        return f"No action found with the name '{name}'."

    async def edit_action(self, command):
        parts = command.split(" ", 2)
        if len(parts) < 3:
            return "Please specify the name of the action to edit."
        _, _, name = parts
        action = self.user_profile.get_action(name)
        if not action:
            return f"No action found with the name '{name}'."
        await self.text_to_speech(f"Editing action '{name}'. Please provide new steps. Say 'finish editing' when done.")
        new_steps = []
        while True:
            step = await self.wait_for_voice_input()
            if step.lower() == "finish editing":
                break
            new_steps.append(step)
        self.user_profile.save_action(name, action['description'], new_steps)
        return f"Action '{name}' has been updated."

    async def main_loop(self):
        self.recorder.start()
        keyboard.add_hotkey(config['cancel_hotkey'], self.cancel_current_task)

        while True:
            self.is_listening = True
            text = self.recorder.text
            if text:
                print(f"User: {text}")
                response = await self.process_voice_command(text)
                await self.parse_and_execute_actions(response)
                await self.text_to_speech("Ready for the next command.")
                self.recorder.clear()
            await asyncio.sleep(0.1)

if __name__ == '__main__':
    username = input("Enter your username: ")
    assistant = ModalAssistant(username)
    gui = AssistantGUI(assistant)
    gui.run()