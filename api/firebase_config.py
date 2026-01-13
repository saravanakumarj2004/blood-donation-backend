
import os
import json
import firebase_admin
from firebase_admin import credentials

def initialize_firebase():
    try:
        # Check if already initialized
        if firebase_admin._apps:
            return

        # Load credentials from Environment Variable (for Render)
        service_account_json = os.getenv('FIREBASE_CREDENTIALS_JSON')
        
        if service_account_json:
            try:
                # Parse JSON string
                cred_dict = json.loads(service_account_json)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                print("Firebase Admin SDK Initialized Successfully")
            except Exception as e:
                print(f"Error parsing FIREBASE_CREDENTIALS_JSON: {e}")
        else:
            print("Warning: FIREBASE_CREDENTIALS_JSON not found. Notifications will not work.")
            
    except Exception as e:
        print(f"Error initializing Firebase: {e}")

# Initialize on import
initialize_firebase()
