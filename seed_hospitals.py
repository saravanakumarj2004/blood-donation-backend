import os
import django
import random
from datetime import datetime

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from api.db import get_db

def seed_hospitals():
    db = get_db()
    users_collection = db.users
    inventory_collection = db.inventory
    
    cities_nearby = ["Bangalore Central", "Indiranagar", "Koramangala", "Whitefield", "Jayanagar", "Malleswaram", "Yelahanka", "Electronic City", "Hebbal", "Banashankari"]
    cities_distant = ["New York", "London", "Tokyo", "Paris", "Berlin", "Sydney", "Toronto", "Dubai", "Singapore", "Mumbai"]
    
    blood_groups = ['A+', 'A-', 'B+', 'B-', 'O+', 'O-', 'AB+', 'AB-']

    print("--- Seeding 20 Hospitals (10 Nearby, 10 Distant) ---")

    hospitals = []

    # 1. Generate 10 Nearby Hospitals (Bangalore ~12.9716, 77.5946)
    for i in range(10):
        name = f"{cities_nearby[i]} General Hospital"
        email = f"hospital_nearby_{i+1}@test.com"
        
        # Randomize coords slightly around Bangalore
        lat = 12.9716 + random.uniform(-0.1, 0.1)
        lng = 77.5946 + random.uniform(-0.1, 0.1)
        
        hospital = {
            "name": name,
            "email": email,
            "password": "hospital123",
            "role": "hospital",
            "phone": f"080{random.randint(2000000, 9999999)}",
            "location": cities_nearby[i],
            "coordinates": {
                "latitude": lat,
                "longitude": lng
            },
            "type": "General",
            "accredited": True
        }
        hospitals.append(hospital)

    # 2. Generate 10 Distant Hospitals (Random Global)
    for i in range(10):
        name = f"{cities_distant[i]} Medical Center"
        email = f"hospital_far_{i+1}@test.com"
        
        # Random Global Coords
        lat = random.uniform(-80, 80)
        lng = random.uniform(-170, 170)
        
        hospital = {
            "name": name,
            "email": email,
            "password": "hospital123",
            "role": "hospital",
            "phone": f"000{random.randint(2000000, 9999999)}",
            "location": cities_distant[i],
            "coordinates": {
                "latitude": lat,
                "longitude": lng
            },
            "type": "Specialist",
            "accredited": True
        }
        hospitals.append(hospital)

    # Insert Hospitals and Create Inventory
    count = 0
    for h in hospitals:
        # Upsert User
        result = users_collection.update_one(
            {"email": h["email"]},
            {"$set": h},
            upsert=True
        )
        
        # Fetch the user to get the _id (needed for inventory linking)
        saved_user = users_collection.find_one({"email": h["email"]})
        hospital_id = str(saved_user["_id"])
        
        # Create/Update Inventory
        inventory_data = {
            "hospitalId": hospital_id,
            "lastUpdated": datetime.now().isoformat()
        }
        
        # Add random stock for each group
        stock_summary = []
        for bg in blood_groups:
            units = random.randint(0, 50) # 0 to 50 units
            inventory_data[bg] = units
            if units > 0:
                stock_summary.append(f"{bg}:{units}")

        inventory_collection.update_one(
            {"hospitalId": hospital_id},
            {"$set": inventory_data},
            upsert=True
        )
        
        count += 1
        print(f"Seeded {h['name']} ({h['location']}) - Inventory: {', '.join(stock_summary[:3])}...")

    print(f"--- Successfully seeded {count} hospitals with inventory ---")

if __name__ == "__main__":
    seed_hospitals()
