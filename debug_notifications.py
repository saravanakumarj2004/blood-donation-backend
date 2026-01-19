import os
import django
from pymongo import MongoClient
import datetime
from bson import ObjectId

# Setup
client = MongoClient("mongodb://localhost:27017/") 
db = client['blood_donation_db']

def simulate_broadcast(cities, req_blood_group):
    print(f"\n--- Simulating Broadcast for {req_blood_group} in {cities} ---")
    
    # 1. Regex
    city_regex = "|".join([str(c) for c in cities])
    
    # 2. Compatibility Logic
    compatible_donors = {
         "A+": ["A+", "A-", "O+", "O-"],
         "O+": ["O+", "O-"],
         "B+": ["B+", "B-", "O+", "O-"],
         "AB+": ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"],
         "A-": ["A-", "O-"],
         "O-": ["O-"],
         "B-": ["B-", "O-"],
         "AB-": ["AB-", "A-", "B-", "O-"]
    }
    # This logic means: If Request is A+, we allow donors who are A+, A-, O+, O-
    eligible_groups = compatible_donors.get(req_blood_group, [])
    print(f"Eligible Donor Groups: {eligible_groups}")

    # 3. Query
    query_filter = {
        "role": "donor",
        "location": {"$regex": city_regex, "$options": "i"}
    }
        
    if eligible_groups:
        query_filter['bloodGroup'] = {"$in": eligible_groups}
        
    print(f"Mongo Query: {query_filter}")
    
    donors = list(db.users.find(query_filter))
    print(f"Matched Donors Count: {len(donors)}")
    for d in donors:
        print(f" -> MATCHED: {d.get('name')} ({d.get('bloodGroup')}) in {d.get('location')}")

# Test Case 1: Request A+ in New York (Should match O-, Should NOT match B-)
# We saw Susan (O-) in New York. We saw William (B-) in Chicago.
# Let's see if we have a B in New York? Or we can test "Chicago" (B-). A+ request in Chicago. B- can't give to A+.
simulate_broadcast(['Chicago'], 'A+') 
simulate_broadcast(['New York'], 'A+') 
