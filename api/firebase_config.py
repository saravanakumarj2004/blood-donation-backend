
import firebase_admin
from firebase_admin import credentials
import os
import json
from pathlib import Path

# Path to Service Account Key (Local Fallback)
BASE_DIR = Path(__file__).resolve().parent.parent

# Try multiple locations just in case
possible_paths = [
    BASE_DIR / 'blood_donation_project' / 'serviceAccountKey.json',
    BASE_DIR / 'config' / 'serviceAccountKey.json',
    BASE_DIR / 'serviceAccountKey.json',
]

cred_path = None
for p in possible_paths:
    if p.exists():
        cred_path = str(p)
        break

def initialize_firebase():
    if not firebase_admin._apps:
        try:
            # 1. Try Environment Variable (Production/Render)
            firebase_creds_json = os.getenv('FIREBASE_CREDENTIALS')
            if firebase_creds_json:
                cred_dict = json.loads(firebase_creds_json)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                print("Firebase Admin Initialized via Environment Variable")
                return

            # 2. Try Local File
            if cred_path:
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
                print(f"Firebase Admin Initialized with file: {cred_path}")
            else:
                print("Warning: serviceAccountKey.json not found and FIREBASE_CREDENTIALS not set. Notifications will not work.")
        
        except Exception as e:
            print(f"Failed to initialize Firebase: {e}")
    else:
        pass # Already initialized
