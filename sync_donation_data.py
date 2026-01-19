
import pymongo
from bson import ObjectId
import datetime

client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client['blood_donation_db']

def sync_data():
    users = db.users.find({"role": "donor"})
    updated_count = 0
    
    for u in users:
        # Find latest completed appointment
        last_appt = db.appointments.find_one(
            {"donorId": str(u['_id']), "status": "Completed"},
            sort=[("date", -1)]
        )
        
        if last_appt:
            appt_date = last_appt.get('date')
            user_date = u.get('lastDonationDate')
            
            # If user profile empty, or appt date is NEWER
            should_update = False
            if not user_date or user_date == "None":
                should_update = True
            else:
                try:
                    # Compare
                    if 'T' in appt_date:
                        ad = datetime.datetime.fromisoformat(appt_date.replace('Z', '+00:00'))
                    else:
                        ad = datetime.datetime.strptime(appt_date, "%Y-%m-%d")
                        
                    if 'T' in user_date:
                        ud = datetime.datetime.fromisoformat(user_date.replace('Z', '+00:00'))
                    else:
                        ud = datetime.datetime.strptime(user_date, "%Y-%m-%d")

                    if ad > ud:
                        should_update = True
                except:
                    # If parsing fails, just overwrite with the valid appt date
                    should_update = True
            
            if should_update:
                print(f"Updating {u.get('name')}: Old={user_date} -> New={appt_date}")
                db.users.update_one(
                    {"_id": u['_id']},
                    {"$set": {"lastDonationDate": appt_date}}
                )
                updated_count += 1
                
    print(f"Sync Complete. Updated {updated_count} users.")

if __name__ == "__main__":
    sync_data()
