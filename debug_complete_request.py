
import requests
import pymongo
from bson import ObjectId

# Connect to DB to get a valid Request ID
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["blood_donation_db"]

# Find an Accepted Request
req = db.requests.find_one({"status": "Accepted"})

if not req:
    print("No 'Accepted' requests found in DB. Creating one for testing...")
    # Create a dummy request
    donor = db.users.find_one({"role": "donor"})
    hospital = db.users.find_one({"role": "hospital"})
    
    if not donor:
        print("No donor found to accept request.")
        exit()
        
    req_id = db.requests.insert_one({
        "status": "Accepted",
        "requesterId": str(hospital['_id']) if hospital else "dummy_req_id",
        "acceptedBy": str(donor['_id']),
        "bloodGroup": "A+",
        "units": 1,
        "hospitalName": "Test Hospital",
        "location": "Test Location",
        "date": "2023-01-01"
    }).inserted_id
    print(f"Created dummy accepted request: {req_id}")
else:
    req_id = req['_id']
    print(f"Found accepted request: {req_id}")

# Call API
url = "http://127.0.0.1:8000/api/donor/requests/complete/"
payload = {"requestId": str(req_id)}

print(f"Sending POST to {url} with {payload}")

try:
    resp = requests.post(url, json=payload)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text}")
except Exception as e:
    print(f"Request failed: {e}")
