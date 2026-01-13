import os
import django
import random
from datetime import datetime, timedelta

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from api.db import get_db

def seed_donors():
    db = get_db()
    users_collection = db.users
    
    cities = ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia", "San Antonio", "San Diego", "Dallas", "San Jose"]
    blood_groups = ['A+', 'A-', 'B+', 'B-', 'O+', 'O-', 'AB+', 'AB-']
    
    first_names = ["James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda", "William", "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez"]

    print("--- Seeding 30 Donors ---")

    donors = []

    # 20 Eligible Donors (10 random old dates, 10 never donated)
    for i in range(20):
        first = random.choice(first_names)
        last = random.choice(last_names)
        name = f"{first} {last}"
        email = f"donor_eligible_{i+1}@test.com"
        
        # Age between 18 and 65
        age = random.randint(18, 65)
        dob = (datetime.now() - timedelta(days=age*365 + random.randint(0, 300))).strftime('%Y-%m-%d')

        # Eligibility Logic: Either None or Older than 60 days
        last_donation = None
        if i < 10: # First 10 have old donations
            days_ago = random.randint(61, 365)
            last_donation = (datetime.now() - timedelta(days=days_ago)).strftime('%Y-%m-%d')
        
        donor = {
            "name": name,
            "email": email,
            "password": "donor123", # Default password
            "role": "donor",
            "bloodGroup": random.choice(blood_groups),
            "phone": f"555{random.randint(1000000, 9999999)}",
            "location": random.choice(cities),
            "dob": dob,
            "lastDonationDate": last_donation,
            "isEligible": True # Explicitly setting based on logic, though backend usually calculates this
        }
        donors.append(donor)

    # 10 Ineligible Donors (Recent donations)
    for i in range(10):
        first = random.choice(first_names)
        last = random.choice(last_names)
        name = f"{first} {last}"
        email = f"donor_ineligible_{i+1}@test.com"
        
        age = random.randint(18, 65)
        dob = (datetime.now() - timedelta(days=age*365 + random.randint(0, 300))).strftime('%Y-%m-%d')

        # Eligibility Logic: Within last 60 days
        days_ago = random.randint(1, 59)
        last_donation = (datetime.now() - timedelta(days=days_ago)).strftime('%Y-%m-%d')

        donor = {
            "name": name,
            "email": email,
            "password": "donor123",
            "role": "donor",
            "bloodGroup": random.choice(blood_groups),
            "phone": f"555{random.randint(1000000, 9999999)}",
            "location": random.choice(cities),
            "dob": dob,
            "lastDonationDate": last_donation,
            "isEligible": False
        }
        donors.append(donor)

    # Insert into DB
    count = 0
    for donor in donors:
        # Use upsert to avoid duplicates if run multiple times
        users_collection.update_one(
            {"email": donor["email"]},
            {"$set": donor},
            upsert=True
        )
        count += 1
        status = "ELIGIBLE" if donor.get('isEligible') else "INELIGIBLE"
        print(f"Seeded {donor['name']} ({donor['email']}) - {status}")

    print(f"--- Successfully seeded {count} donors ---")

if __name__ == "__main__":
    seed_donors()
