import os
import django
import datetime
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
            "name": "Donor One",
            "email": "donor@blood.com",
            "password": "password123",
            "role": "donor",
            "bloodGroup": "O+",
            "location": "New York",
            "coordinates": {"lat": 40.7128, "lng": -74.0060},
            "lastDonationDate": (datetime.datetime.now() - datetime.timedelta(days=100)).isoformat(),
            "createdAt": datetime.datetime.now().isoformat()
        },
        {
            "name": "City Hospital",
            "email": "hospital@blood.com",
            "password": "password123",
            "role": "hospital",
            "location": "New York",
            "coordinates": {"lat": 40.7306, "lng": -73.9352},
            "createdAt": datetime.datetime.now().isoformat()
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
