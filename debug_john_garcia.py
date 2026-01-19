
import pymongo
from bson import ObjectId
import datetime
import os

# Connect to DB (assuming localhost for now as per runserver)
client = pymongo.MongoClient("mongodb://localhost:27017/") 
db = client['blood_donation_db']

# Find John Garcia
# Since I don't know his ID, I'll search by name or role=donor
donors = db.users.find({"role": "donor", "name": {"$regex": "Garcia", "$options": "i"}})

print(f"Found {db.users.count_documents({'role': 'donor'})} total donors.")

for d in donors:
    print(f"\n--- Checking Donor: {d.get('name')} ({d.get('_id')}) ---")
    last_date_str = d.get('lastDonationDate')
    print(f"Raw lastDonationDate: '{last_date_str}'")
    
    if last_date_str:
        try:
            if 'T' in last_date_str:
                 last_date = datetime.datetime.fromisoformat(last_date_str.replace('Z', '+00:00'))
                 print(f"Parsed via ISO: {last_date}")
            else:
                 last_date = datetime.datetime.strptime(last_date_str, "%Y-%m-%d")
                 print(f"Parsed via strptime: {last_date}")
                 last_date = last_date.replace(tzinfo=datetime.timezone.utc)

            if last_date.tzinfo is None:
                 last_date = last_date.replace(tzinfo=datetime.timezone.utc)
            
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            sixty_days_ago = now_utc - datetime.timedelta(days=60)
            
            print(f"Now (UTC): {now_utc}")
            print(f"60 Days Ago: {sixty_days_ago}")
            
            # Logic 1: Date Comparison
            if last_date > sixty_days_ago:
                print("RESULT 1: Ineligible (Recent Donation)")
            else:
                print("RESULT 1: Eligible")
                
            # Logic 2: Days Diff (HospitalListView style)
            days_diff = (now_utc - last_date).days
            print(f"Days Diff: {days_diff}")
            if days_diff < 60:
                print("RESULT 2: Ineligible (Diff < 60)")
            else:
                print("RESULT 2: Eligible")
                
        except Exception as e:
            print(f"ERROR Parsing: {e}")
    else:
        print("No last donation date in User Profile - Checking Appointments...")
        
    # Check Appointments
    last_appt = db.appointments.find_one(
        {"donorId": str(d['_id']), "status": "Completed"},
        sort=[("date", -1)]
    )
    if last_appt:
        print(f"FOUND Appointment: {last_appt.get('date')} (Reason: {last_appt.get('rejectionReason')})")
    else:
        print("No completed appointments found.")
