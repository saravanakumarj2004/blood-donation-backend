import os
from pymongo import MongoClient
import ssl

# PASTE YOUR CONNECTION STRING HERE
MONGO_URI = "mongodb+srv://jsaravanakumar2004:sk948989@cluster0.jjj0e.mongodb.net/?appName=Cluster0"

# Helper to create admin
def create_admin():
    try:
        # Connect
        print(f"Connecting to: {MONGO_URI}")
        client = MongoClient(MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)
        db = client["blood_donation_db"] # Use your DB name
        
        users = db.users
        
        # Admin Data
        admin_user = {
            "name": "Super Admin",
            "email": "admin@blood.com",
            "password": "admin123", # Change this immediately after login!
            "role": "admin",
            "phone": "0000000000",
            "location": "Headquarters"
        }
        
        # Update or Insert
        users.update_one(
            {"email": admin_user["email"]},
            {"$set": admin_user},
            upsert=True
        )
        print("SUCCESS: Admin User created/updated!")
        print("Email: admin@blood.com")
        print("Password: admin123")
        
    except Exception as e:
        print(f"FAILED: {e}")
        print("Tip: Check if your IP is whitelisted in MongoDB Atlas Network Access (0.0.0.0/0)")

if __name__ == "__main__":
    create_admin()
