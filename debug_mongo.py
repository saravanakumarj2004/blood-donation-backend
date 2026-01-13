from pymongo import MongoClient
import sys

try:
    client = MongoClient("mongodb://localhost:27017/")
    db = client["blood_donation_db"]
    print("Connected to Mongo")
    
    # Clean up test user
    db.users.delete_many({"email": "debug_user@test.com"})
    
    # Insert
    user = {
        "name": "Debug User",
        "email": "debug_user@test.com",
        "password": "password123",
        "role": "donor"
    }
    res = db.users.insert_one(user)
    print(f"Inserted User ID: {res.inserted_id}")
    
    # Retrieve
    found = db.users.find_one({"email": "debug_user@test.com", "role": "donor"})
    if found:
        print("User Found:", found)
    else:
        print("User NOT Found")

except Exception as e:
    print(f"Error: {e}")
