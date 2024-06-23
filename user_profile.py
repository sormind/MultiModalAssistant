import json
import os

class UserProfile:
    def __init__(self, username):
        self.username = username
        self.settings = {}
        self.saved_actions = {}
        self.load_profile()

    def load_profile(self):
        filename = f"{self.username}_profile.json"
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                data = json.load(f)
                self.settings = data.get('settings', {})
                self.saved_actions = data.get('saved_actions', {})

    def save_profile(self):
        filename = f"{self.username}_profile.json"
        data = {
            'settings': self.settings,
            'saved_actions': self.saved_actions
        }
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)

    def save_action(self, name, description, steps):
        self.saved_actions[name] = {
            'description': description,
            'steps': steps
        }
        self.save_profile()

    def get_action(self, name):
        return self.saved_actions.get(name)

    def list_actions(self):
        return list(self.saved_actions.keys())

    def delete_action(self, name):
        if name in self.saved_actions:
            del self.saved_actions[name]
            self.save_profile()
            return True
        return False

    def update_settings(self, new_settings):
        self.settings.update(new_settings)
        self.save_profile()