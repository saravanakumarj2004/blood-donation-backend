
import pymongo
from bson import ObjectId

client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["blood_donation_db"]

print("--- USERS ---")
users = list(db.users.find({}, {"name": 1, "email": 1, "role": 1}))
for u in users:
    print(f"User: {u['_id']} | {u.get('name')} | {u.get('email')}")

print("\n--- REQUESTS ---")
requests = list(db.requests.find({}))
for r in requests:
    print(f"Request: {r['_id']} | Requester: {r.get('requesterId')} | Status: {r.get('status')} | AcceptedBy: {r.get('acceptedBy')}")

print("\n--- ANALYSIS ---")
# Check if requesterIds match valid users
user_ids = [str(u['_id']) for u in users]
for r in requests:
    rid = r.get('requesterId')
    if rid not in user_ids:
        print(f"WARNING: Request {r['_id']} has orphan/invalid requesterId: {rid}")
    else:
        print(f"Request {r['_id']} belongs to valid user {rid}")
