import os
import django
from django.conf import settings

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from api.db import get_db

def seed_users():
    db = get_db()
    users_collection = db.users
    
    # Define Default Users
    default_users = [
        {
            "name": "Super Admin",
            "email": "admin@blood.com",
            "password": "admin123", # Plaintext for now as per current setup
            "role": "admin",
            "phone": "0000000000",
            "location": "Headquarters"
        },
        {
            "name": "City General Hospital",
            "email": "hospital@city.com",
            "password": "hospital123",
            "role": "hospital",
            "phone": "1234567890",
            "location": "Downtown",
            "coordinates": {
                "latitude": 12.9716, 
                "longitude": 77.5946 
            }
        }
    ]
    
    print("--- Seeding Users (Forcing Updates) ---")
    for user in default_users:
        users_collection.update_one(
            {"email": user["email"]},
            {"$set": user},
            upsert=True
        )
        print(f"Updated/Created user: {user['email']} / {user['password']} ({user['role']})")
    print("--- Done ---")

if __name__ == "__main__":
    seed_users()
