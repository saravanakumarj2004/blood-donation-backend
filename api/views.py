from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .db import get_db
from bson import ObjectId
import datetime
import math
from firebase_admin import messaging
from .firebase_config import initialize_firebase # Init on load
import traceback
import re

# Haversine Formula for Distance (km)
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371 # Earth radius in km
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) * math.sin(d_lat / 2) +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(d_lon / 2) * math.sin(d_lon / 2))
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# Helper to serialize Mongo document
def serialize_doc(doc):
    if not doc:
        return None
    doc['id'] = str(doc['_id'])
    del doc['_id']
    return doc

class RegisterView(APIView):
    def post(self, request):
        db = get_db()
        data = request.data
        
        email = data.get('email')
        role = data.get('role')
        
        if not email or not role:
             return Response({"message": "Email and Role are required"}, status=status.HTTP_400_BAD_REQUEST)

        # Check existing
        existing = db.users.find_one({"email": email})
        if existing:
             return Response({"message": "Email already exists"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Enforce Age > 18
        dob_str = data.get('dob')
        if dob_str:
            try:
                dob = datetime.datetime.fromisoformat(dob_str)
                today = datetime.datetime.now()
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                if age < 18:
                    return Response({"message": "You must be 18+ to register"}, status=status.HTTP_400_BAD_REQUEST)
            except:
                pass # Skip if invalid format, catch other validation later
        
        # Prepare User Data
        new_user = {
            "name": data.get('name'),
            "email": email,
            "password": data.get('password'), 
            "role": role,
            "phone": data.get('phone'),
            "location": data.get('location'),
            "coordinates": data.get('coordinates'), # Store Lat/Lng
            "bloodGroup": data.get('bloodGroup'), # For Donors
            "dob": data.get('dob'),
            "lastDonationDate": data.get('lastDonationDate'), # Initial value from registration
            "gender": data.get('gender'),
            "securityQuestion": data.get('securityQuestion'),
            "securityAnswer": data.get('securityAnswer'),
            "createdAt": datetime.datetime.now().isoformat()
        }
        
        # Save to DB
        result = db.users.insert_one(new_user)
        
        # Return success with ID
        new_user['id'] = str(result.inserted_id)
        del new_user['_id']
        del new_user['password'] 
        
        return Response({"success": True, "user": new_user}, status=status.HTTP_201_CREATED)

class LoginView(APIView):
    def post(self, request):
        db = get_db()
        email = request.data.get('email')
        password = request.data.get('password')
        role = request.data.get('role')
        
        if not email or not password or not role:
            return Response({"message": "All fields required"}, status=status.HTTP_400_BAD_REQUEST)
            
        user = db.users.find_one({"email": email, "role": role})
        
        if not user:
            return Response({"message": "Invalid credentials or role"}, status=status.HTTP_401_UNAUTHORIZED)
            
        if user.get('password') != password:
            return Response({"message": "Invalid password"}, status=status.HTTP_401_UNAUTHORIZED)
            
        return Response({"success": True, "user": serialize_doc(user)})

class DonorStatsView(APIView):
    def get(self, request):
        db = get_db()
        user_id = request.query_params.get('userId')
        if not user_id:
            return Response({"error": "userId required"}, status=400)
            
        # Use appointments collection where status is 'Completed'
        donations = db.appointments.count_documents({"donorId": user_id, "status": "Completed"})
        lives_saved = donations * 3 
        
        # Calculate Next Donation Date
        try:
            # 1. Check Appointment History
            last_appt = db.appointments.find_one(
                {"donorId": user_id, "status": "Completed"},
                sort=[("date", -1)]
            )
            
            # 2. Check User Profile (Initial Registration or Cached)
            user = db.users.find_one({"_id": ObjectId(user_id)})
            user_last_date_str = user.get('lastDonationDate') if user else None

            # Determine most recent date
            latest_date = None
            
            if last_appt:
                d_str = last_appt['date'].replace('Z', '+00:00')
                latest_date = datetime.datetime.fromisoformat(d_str)

            if user_last_date_str:
                try:
                    u_date = datetime.datetime.fromisoformat(user_last_date_str.replace('Z', '+00:00'))
                    # If user profile date is more recent (or no appt yet), use it
                    if latest_date is None or u_date > latest_date:
                        latest_date = u_date
                except:
                    pass

            next_date = "Available Now"
            if latest_date:
                # 60 Days Rule (User requested 60 days)
                eligible_date = latest_date + datetime.timedelta(days=60)
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                
                # Make eligible_date offset-aware if it isn't
                if eligible_date.tzinfo is None:
                    eligible_date = eligible_date.replace(tzinfo=datetime.timezone.utc)
                if now_utc.tzinfo is None:
                    now_utc = now_utc.replace(tzinfo=datetime.timezone.utc)

                if eligible_date > now_utc:
                    next_date = eligible_date.strftime("%d %b %Y")
        except Exception as e:
            print(f"Error calculating next date: {e}")
            pass

        return Response({
            "livesSaved": lives_saved,
            "bloodUnits": donations,
            "nextDonationDate": next_date
        })

class DonationHistoryView(APIView):
    def get(self, request):
        db = get_db()
        user_id = request.query_params.get('userId')
        if not user_id:
             return Response({"error": "userId required"}, status=400)
             
        # Fetch ALL appointments for history/bookings tab
        cursor = db.appointments.find({"donorId": user_id}).sort("date", -1)
        history = [serialize_doc(doc) for doc in cursor]
        return Response(history)
        
    def post(self, request):
        db = get_db()
        data = request.data
        if 'date' not in data:
            data['date'] = datetime.datetime.now().isoformat()
        if 'status' not in data:
            data['status'] = 'Pending'
        
        # Ensure 'type' is set for clarity
        if 'reason' in data:
            data['type'] = data['reason'] # e.g. "Voluntary Donation"
        elif 'type' not in data:
            data['type'] = 'Voluntary Donation'

        # Validate Donor
        donor_id = data.get('donorId')
        if not donor_id:
            return Response({"error": "donorId required"}, status=400)
            
        # Validate Hospital (if selected)
        if data.get('hospitalId'):
            hospital = db.users.find_one({"_id": ObjectId(data.get('hospitalId')), "role": "hospital"})
            if not hospital:
                 return Response({"error": "Invalid hospital selected"}, status=400)

        # 60-Day Eligibility Check
        try:
            # Check last completed donation or appointment
            last_appt = db.appointments.find_one(
                {"donorId": donor_id, "status": "Completed"},
                sort=[("date", -1)]
            )
            donor_user = db.users.find_one({"_id": ObjectId(donor_id)})
            
            last_date = None
            if last_appt:
                last_date = datetime.datetime.fromisoformat(last_appt['date'].replace('Z', '+00:00'))
            
            if donor_user and donor_user.get('lastDonationDate'):
                try:
                    last_donation_str = donor_user['lastDonationDate']
                    if 'T' in last_donation_str:
                         u_date = datetime.datetime.fromisoformat(last_donation_str.replace('Z', '+00:00'))
                    else:
                         u_date = datetime.datetime.strptime(last_donation_str, "%Y-%m-%d")
                         u_date = u_date.replace(tzinfo=datetime.timezone.utc)
                         
                    if last_date is None or u_date > last_date:
                        last_date = u_date
                except Exception as e:
                    print(f"Error parsing user lastDonationDate: {e}")
            
            if last_date:
                if last_date.tzinfo is None:
                    last_date = last_date.replace(tzinfo=datetime.timezone.utc)
                
                # Check 60 days
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                if (now_utc - last_date).days < 60:
                     return Response({"error": "You are not eligible to donate yet (60-day cooling period)."}, status=400)
        except Exception as e:
            print(f"Eligibility check error: {e}")
            # Fail safe or allow? Allow for now but log.
            pass

        # Insert into appointments (Single Source of Truth)
        res = db.appointments.insert_one(data)
        return Response({"success": True, "id": str(res.inserted_id)})

class BloodInventoryView(APIView):
    def get(self, request):
        db = get_db()
        user_id = request.query_params.get('userId')
        if not user_id:
             return Response({"error": "userId required"}, status=400)
             
        inventory = db.inventory.find_one({"hospitalId": user_id})
        if not inventory:
            default_stock = {
                "A+": 0, "A-": 0, "B+": 0, "B-": 0, 
                "AB+": 0, "AB-": 0, "O+": 0, "O-": 0
            }
            return Response(default_stock)
            
        return Response(serialize_doc(inventory))

    def post(self, request):
        db = get_db()
        data = request.data
        user_id = data.get('hospitalId')
        
        # Check if this is a "Stock Entry" (incremental) or a Manual Update (set)
        # Assuming H3 Stock Entry feature uses this.
        
        if data.get('mode') == 'incremental':
            # Handle incremental updates (Stock Entry Log)
             group = data.get('bloodGroup')
             units = int(data.get('units', 0))
             if group and units:
                 db.inventory.update_one(
                    {"hospitalId": user_id},
                    {"$inc": {group: units}},
                    upsert=True
                 )
                 # Log the entry
                 log_entry = {
                     "hospitalId": user_id,
                     "bloodGroup": group,
                     "units": units,
                     "type": "Stock Entry",
                     "date": datetime.datetime.now().isoformat(),
                     "source": data.get('source', 'Manual Entry'),
                     "expiry": data.get('expiry')
                 }
                 db.stock_logs.insert_one(log_entry)
        else:
            # Full update
            db.inventory.update_one(
                {"hospitalId": user_id},
                {"$set": data},
                upsert=True
            )
        
        return Response({"success": True})

class SaveFCMTokenView(APIView):
    def post(self, request):
        db = get_db()
        user_id = request.data.get('userId')
        token = request.data.get('token')
        
        if not user_id or not token:
            return Response({"error": "userId and token required"}, status=400)
            
        # Update user with FCM token
        db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"fcmToken": token}}
        )
        return Response({"success": True})

class HospitalRequestsView(APIView):
    def get(self, request):
        db = get_db()
        user_id = request.query_params.get('userId')
        
        # 1. OUTGOING (Requests I sent)
        outgoing_query = {"requesterId": user_id}
        my_requests_cursor = db.requests.find(outgoing_query).sort("date", -1)
        
        # 2. INCOMING (Requests sent TO me)
        # Only show requests specifically targeting this hospital
        incoming_query = {
            "hospitalId": user_id, 
            "requesterId": {"$ne": user_id} 
        }
        
        incoming_cursor = db.requests.find(incoming_query).sort("date", -1)
        incoming_list = list(incoming_cursor)

        requests = []
        
        # Process My Requests
        for req in my_requests_cursor:
            req['isOutgoing'] = True
            if req.get('acceptedBy'):
                donor = db.users.find_one({"_id": ObjectId(req['acceptedBy'])})
                req['donorName'] = donor.get('name') if donor else "Unknown Donor"
            
            requests.append(serialize_doc(req))
            
        # Process Incoming Requests
        for req in incoming_list:
            req['isOutgoing'] = False
            
            # If accepted by someone else, hide it (unless I accepted it)
            if req.get('acceptedBy') and req.get('acceptedBy') != user_id:
                continue 

            # Fetch Requester Name
            requester_id = req.get('requesterId') or req.get('hospitalId')
            if requester_id:
                requester = db.users.find_one({"_id": ObjectId(requester_id)})
                req['hospitalName'] = requester.get('name') if requester else "Unknown Hospital"
                req['location'] = requester.get('location') if requester else "Unknown"
            
            requests.append(serialize_doc(req))
            
        return Response(requests)

    def post(self, request):
        db = get_db()
        data = request.data
        data['date'] = datetime.datetime.now().isoformat()
        data['status'] = 'Active'
        
        # Calculate Expiration Time
        req_time = data.get('requiredTime')
        if req_time:
            now = datetime.datetime.now()
            delta = datetime.timedelta(hours=24) 
            
            if '30 mins' in req_time:
                delta = datetime.timedelta(minutes=30)
            elif '1 Hour' in req_time:
                delta = datetime.timedelta(hours=1)
            elif '2 Hours' in req_time:
                delta = datetime.timedelta(hours=2)
            elif '4 Hours' in req_time:
                delta = datetime.timedelta(hours=4)
            elif 'Today' in req_time:
                params = now.replace(hour=23, minute=59, second=59)
                delta = params - now
            
            data['expiresAt'] = (now + delta).isoformat()
        
        if 'units' in data:
            data['units'] = int(data['units'])
            
        res = db.requests.insert_one(data)
        
        # If this is an Emergency Alert, create Notifications for Donors immediately
        if data.get('type') == 'EMERGENCY_ALERT' or data.get('type') == 'P2P':
             limit_date = datetime.datetime.now() - datetime.timedelta(days=60)
             
             query_filter = {
                 "role": "donor", 
                 "bloodGroup": data.get('bloodGroup'),
                 # "fcmToken": {"$exists": True}, # Optional: Find all for DB notifications?
                 "$or": [
                    {"lastDonationDate": {"$exists": False}}, 
                    {"lastDonationDate": None},
                    {"lastDonationDate": {"$lt": limit_date.isoformat()}} 
                 ]
             }
             
             # City Filter for P2P/Emergency
             cities = data.get('cities')
             if cities and isinstance(cities, list):
                 # Create regex to match ANY of the target cities
                 city_regexs = [re.compile(f"{c}", re.IGNORECASE) for c in cities]
                 query_filter['location'] = {"$in": city_regexs}
             elif data.get('location'): # Fallback for single location
                  query_filter['location'] = {"$regex": data.get('location'), "$options": "i"}

             donors = db.users.find(query_filter)
             
             req_id = str(res.inserted_id)
             notif_title = "Emergency Blood Request!" if data.get('type') == 'EMERGENCY_ALERT' else "Urgent Blood Needed!"
             
             for d in donors:
                 # 1. Send Push Notification
                 token = d.get('fcmToken')
                 if token:
                     try:
                        message = messaging.Message(
                            notification=messaging.Notification(
                                title=notif_title,
                                body=f"{data.get('units')} units of {data.get('bloodGroup')} needed at {data.get('hospitalName', 'Hospital')}!"
                            ),
                            token=token,
                        )
                        messaging.send(message)
                     except Exception as e:
                         print(f"Error sending FCM: {e}")
                 
                 # 2. Create In-App Notification (Optional but good for history)
                 db.notifications.insert_one({
                    "userId": str(d['_id']),
                    "message": f"{data.get('units')} units of {data.get('bloodGroup')} needed at {data.get('hospitalName')} in {data.get('city', 'your area')}.",
                    "type": "URGENT_REQUEST",
                    "requestId": req_id,
                    "status": "UNREAD",
                    "timestamp": datetime.datetime.now().isoformat()
                 })

        return Response({"success": True, "id": str(res.inserted_id)})

    def put(self, request):
        db = get_db()
        data = request.data
        req_id = data.get('id')
        new_status = data.get('status')
        responder_id = data.get('hospitalId') 
        
        if not req_id or not new_status:
            return Response({"error": "id and status are required"}, status=400)
            
        dataset = {"status": new_status}
        
        if data.get('responseMessage'):
            dataset['responseMessage'] = data.get('responseMessage')
        
        if new_status == 'Accepted':
            if not responder_id:
                return Response({"error": "hospitalId required for acceptance"}, status=400)
            dataset['acceptedBy'] = responder_id
            
            # NOTIFICATION: Notify the Requester that their request was Accepted
            req_info = db.requests.find_one({"_id": ObjectId(req_id)})
            if req_info:
                # Requester ID logic
                reqr_id = req_info.get('requesterId') # Should be correct requester
                if not reqr_id and req_info.get('hospitalId') and not req_info.get('isBroadcast'): 
                     # Fallback if hospitalId was used as requester in older logic, 
                     # but we aligned on requesterId. 
                     reqr_id = req_info.get('hospitalId')

                if reqr_id:
                     # Fetch Responder Name
                     responder = db.users.find_one({"_id": ObjectId(responder_id)})
                     resp_name = responder.get('name', 'A Responder') if responder else 'A Responder'
                     
                     db.notifications.insert_one({
                        "userId": reqr_id, # Notify the one who ASKED for blood
                        "message": f"{resp_name} has accepted your request for {req_info.get('bloodGroup')} blood under {req_info.get('patientName', 'Patient')}.",
                        "type": "REQUEST_ACCEPTED",
                        "relatedRequestId": req_id,
                        "status": "UNREAD",
                        "timestamp": datetime.datetime.now().isoformat()
                     })
            
        if new_status == 'Completed':
            dataset["completedAt"] = datetime.datetime.now().isoformat()
            
        db.requests.update_one(
            {"_id": ObjectId(req_id)},
            {"$set": dataset}
        )
        
        if new_status == 'Completed':
            req = db.requests.find_one({"_id": ObjectId(req_id)})
            if req:
                req_type = req.get('type')
                units = int(req.get('units', 1))
                bg = req.get('bloodGroup')
                
                # Unified Logic: Requester gets stock, AcceptedBy (Donor/Hospital) gives stock
                donor_id = req.get('acceptedBy')
                requester_id = req.get('requesterId')

                # Fetch Donor Details
                donor_name = "Unknown Donor"
                if donor_id:
                    donor_user = db.users.find_one({"_id": ObjectId(donor_id)})
                    if donor_user:
                        donor_name = donor_user.get('name')

                if requester_id and bg:
                    # 1. Update Inventory
                    db.inventory.update_one(
                        {"hospitalId": requester_id},
                        {"$inc": {bg: units}}, 
                        upsert=True
                    )
                    
                    # 2. Create Blood Batch Automatically
                    expiry_date = (datetime.datetime.now() + datetime.timedelta(days=42)).isoformat()
                    batch_data = {
                        "hospitalId": requester_id,
                        "bloodGroup": bg,
                        "componentType": "Whole Blood",
                        "units": units,
                        "collectedDate": datetime.datetime.now().isoformat(),
                        "expiryDate": expiry_date,
                        "sourceType": "Donation",
                        "sourceName": donor_name,
                        "location": req.get('location') or "Hospital",
                        "status": "Active",
                        "createdAt": datetime.datetime.now().isoformat()
                    }
                    db.blood_batches.insert_one(batch_data)
                    
                # 3. Handle Donor Stats & History
                if donor_id:
                     if donor_user and donor_user.get('role') == 'donor':
                         history_record = {
                            "donorId": donor_id,
                            "hospitalId": requester_id,
                            "hospitalName": req.get('hospitalName') or 'P2P Donation',
                            "date": datetime.datetime.now().isoformat(),
                            "units": units,
                            "bloodGroup": bg,
                            "type": "P2P Donation" if req_type == 'P2P' else "Emergency Donation", 
                            "status": "Completed"
                         }
                         db.appointments.insert_one(history_record)
                         
                         db.users.update_one(
                             {"_id": ObjectId(donor_id)},
                             {
                                 "$set": {"lastDonationDate": datetime.datetime.now().isoformat()},
                                 "$inc": {"donationCount": units}
                             }
                         )
                     elif donor_id:
                         # Stock Transfer (Hospital to Hospital) - Reduce sender inventory
                          db.inventory.update_one(
                            {"hospitalId": donor_id},
                            {"$inc": {bg: -units}},
                            upsert=True
                        )
                          
                          # Auto-Create Batch for the RECEIVING Hospital (requester_id)
                          # Since they received stock from another hospital
                          sender_hospital = db.users.find_one({"_id": ObjectId(donor_id)})
                          source_name = sender_hospital.get('name') if sender_hospital else "Unknown Hospital"
                          
                          expiry_date = (datetime.datetime.now() + datetime.timedelta(days=42)).isoformat()
                          batch_data = {
                            "hospitalId": requester_id,
                            "bloodGroup": bg,
                            "componentType": "Whole Blood",
                            "units": units,
                            "collectedDate": datetime.datetime.now().isoformat(),
                            "expiryDate": expiry_date,
                            "sourceType": "Transfer", 
                            "sourceName": source_name,
                            "location": req.get('location') or "Hospital",
                            "status": "Active",
                            "createdAt": datetime.datetime.now().isoformat()
                        }
                          db.blood_batches.insert_one(batch_data)

        return Response({"success": True})

    def delete(self, request):
        db = get_db()
        req_id = request.query_params.get('id')
        if not req_id:
             return Response({"error": "id parameter required"}, status=400)
        
        # Verify ownership (optional but recommended)
        # user_id = request.query_params.get('userId')
        
        result = db.requests.delete_one({"_id": ObjectId(req_id)})
        if result.deleted_count > 0:
             return Response({"success": True})
        return Response({"error": "Request not found"}, status=404)

class HospitalSearchView(APIView):
    def get(self, request):
        db = get_db()
        blood_group = request.query_params.get('bloodGroup')
        user_lat = request.query_params.get('lat')
        user_lng = request.query_params.get('lng')
        
        if not blood_group:
             return Response({"error": "bloodGroup required"}, status=400)

        inventory_query = {blood_group: {"$gt": 0}}
        inventories = list(db.inventory.find(inventory_query))
        
        results = []
        for inv in inventories:
            hospital_id = inv.get('hospitalId')
            units = inv.get(blood_group)
            
            if hospital_id:
                try:
                    hospital = db.users.find_one({"_id": ObjectId(hospital_id)})
                    if hospital:
                        dist_text = "Unknown Distance"
                        dist_val = 999999
                        
                        if user_lat and user_lng and hospital.get('coordinates'):
                            try:
                                h_lat = float(hospital['coordinates']['latitude'])
                                h_lng = float(hospital['coordinates']['longitude'])
                                u_lat = float(user_lat)
                                u_lng = float(user_lng)
                                
                                dist = calculate_distance(u_lat, u_lng, h_lat, h_lng)
                                dist_val = dist
                                dist_text = f"{dist:.1f} km"
                            except:
                                pass
                        
                        results.append({
                            "id": str(hospital['_id']),
                            "name": hospital.get('name'),
                            "location": hospital.get('location', 'Unknown'),
                            "phone": hospital.get('phone', 'N/A'),
                            "units": units,
                            "distance": dist_text,
                            "sort_dist": dist_val
                        })
                except:
                    continue 

        results.sort(key=lambda x: x['sort_dist'])
        return Response(results)

class ActiveRequestsView(APIView):
    def get(self, request):
        db = get_db()
        user_id = request.query_params.get('userId')
        
        filter_query = {
            "status": {"$in": ["Pending", "Active"]},
        }

        # Filtering Logic (City & Blood Group & Eligibility)
        if user_id:
            try:
                user = db.users.find_one({"_id": ObjectId(user_id)})
                if user:
                    # 1. Eligibility Check (60 Days Rule)
                    last_donation_str = user.get('lastDonationDate')
                    is_eligible = True
                    if last_donation_str:
                        try:
                            # Handle typical formats: ISO with 'T' or simple Date 'YYYY-MM-DD'
                            if 'T' in last_donation_str:
                                last_date = datetime.datetime.fromisoformat(last_donation_str.replace('Z', '+00:00'))
                            else:
                                # Assume YYYY-MM-DD
                                last_date = datetime.datetime.strptime(last_donation_str, "%Y-%m-%d")
                                last_date = last_date.replace(tzinfo=datetime.timezone.utc) # Make aware

                            # Ensure we compare apples to apples (UTC)
                            if last_date.tzinfo is None:
                                 last_date = last_date.replace(tzinfo=datetime.timezone.utc)
                                 
                            now_utc = datetime.datetime.now(datetime.timezone.utc)
                            sixty_days_ago = now_utc - datetime.timedelta(days=60)
                            
                            if last_date > sixty_days_ago:
                                # Donated recently, not eligible
                                is_eligible = False 
                        except Exception as e:
                            print(f"Eligibility Date Parse Error: {e} for {last_donation_str}")
                            pass
                    
                    if not is_eligible:
                         return Response({"message": "You are not eligible to donate yet (Cooling Period).", "requests": []})

                    # 2. City Filter (Request Location must match User Location)
                    # Simple string match for now, could be improved with regex
                    user_city = user.get('location', '').split(',')[0].strip() # Assuming "City, State"
                    if user_city:
                         # Filter requests where location matches user's city OR city is in target 'cities' list
                         filter_query['$or'] = [
                            {"location": {"$regex": user_city, "$options": "i"}},
                            {"cities": {"$regex": user_city, "$options": "i"}}, # For array of strings or string
                            {"city": {"$regex": user_city, "$options": "i"}}    # Fallback for string field
                         ]
                    
                    # 3. Blood Group Compatibility
                    # Define compatible donor mapping
                    compatibility = {
                        "A+": ["A+", "AB+"],
                        "O+": ["O+", "A+", "B+", "AB+"],
                        "B+": ["B+", "AB+"],
                        "AB+": ["AB+"],
                        "A-": ["A+", "A-", "AB+", "AB-"],
                        "O-": ["A+", "A-", "B+", "B-", "AB+", "AB-"],
                        "B-": ["B+", "B-", "AB+", "AB-"],
                        "AB-": ["AB+", "AB-"]
                    }
                    
                    # If I am User (Donor), I can DONATE to requests needing my blood type
                    # So Find Requests where Request.bloodGroup is in My.compatibility?
                    # Wait, no.
                    # Requester needs X. Donor has Y.
                    # Donor Y can give to X if Y is compatible with X.
                    # Standard Table:
                    # Donor O- -> All
                    # Donor O+ -> O+, A+, B+, AB+
                    
                    # So we filter requests where the Request.bloodGroup is one that the User can donate to.
                    user_bg = user.get('bloodGroup')
                    if user_bg and user_bg in compatibility:
                         can_donate_to = compatibility[user_bg]
                         filter_query['bloodGroup'] = {"$in": can_donate_to}
                         
            except Exception as e:
                print(f"Error in ActiveRequests filters: {e}")

        # Exclude own requests if userId provided
        if user_id:
             # Logic: Show (Standard Filter AND Pending) OR (Accepted By Me AND Status=Accepted)
             # But MongoDB queries are easier if we build two branches
             
             base_criteria = filter_query.copy() # Contains Location, Blood Group, Eligibility
             base_criteria['status'] = {"$in": ["Pending", "Active"]}
             base_criteria['requesterId'] = {"$ne": user_id}
             # Exclude if I ignored it
             base_criteria['ignoredBy'] = {"$ne": user_id}
             
             # Accepted by me criteria
             accepted_criteria = {
                 "acceptedBy": user_id,
                 "status": "Accepted" # completed are hidden
             }
             
             final_query = {"$or": [base_criteria, accepted_criteria]}
             
             cursor = db.requests.find(final_query).sort("date", -1)
        else:
            # Fallback for anonymous or other uses
            filter_query['status'] = "Pending"
            cursor = db.requests.find(filter_query).sort("date", -1)
        
        requests = []
        for req in cursor:
            # Manual Filter: Explicitly exclude if requesterId matches user_id (String vs ObjectId safety)
            # Only if NOT accepted by me (because if accepted by me, I want to see it)
            is_own_request = False
            if user_id and req.get('requesterId'):
                if str(req.get('requesterId')) == str(user_id):
                     is_own_request = True
            
            # If it's my own request AND I haven't accepted it (which is impossible for own request), hide it.
            # But wait, if query used $or, we might have matched "acceptedBy": me.
            # If I accepted it, I should see it.
            # If I created it, I should NOT see it.
            if is_own_request:
                 continue

            # If P2P, requester is User. If Hospital Req, requester is Hospital.
            requester_id = req.get('requesterId') or req.get('hospitalId')
            
            # Populate fallback names if missing
            if not req.get('hospitalName') or not req.get('location'):
                if requester_id:
                     u = db.users.find_one({"_id": ObjectId(requester_id)})
                     if u:
                         if not req.get('hospitalName'):
                             req['hospitalName'] = u.get('name')
                         if not req.get('location'):
                             req['location'] = u.get('location')

            requests.append(serialize_doc(req))
            
        return Response(requests)

class HospitalListView(APIView):
    def get(self, request):
        db = get_db()
        cursor = db.users.find({"role": "hospital"})
        hospitals = []
        for h in cursor:
            hospitals.append({
                "id": str(h['_id']),
                "name": h.get('name')
            })
        return Response(hospitals)

class HospitalAppointmentsView(APIView):
    def get(self, request):
        db = get_db()
        user_id = request.query_params.get('userId')
        if not user_id:
            return Response({"error": "userId required"}, status=400)
            
        try:
            hospital = db.users.find_one({"_id": ObjectId(user_id)})
        except Exception:
            return Response({"error": "Invalid User ID format"}, status=400)

        if not hospital:
            return Response({"error": "Hospital not found"}, status=404)
            
        cursor = db.appointments.find({
            "$or": [
                {"hospitalId": user_id},
                {"center": hospital.get('name')}
            ]
        }).sort("date", -1)
        
        appointments = []
        for doc in cursor:
            # Lookup Donor Name if not present
            if not doc.get('donorName') and doc.get('donorId'):
                donor = db.users.find_one({"_id": ObjectId(doc.get('donorId'))})
                if donor:
                    doc['donorName'] = donor.get('name')
            
            appointments.append(serialize_doc(doc))
            
        return Response(appointments)

    def post(self, request):
        db = get_db()
        data = request.data
        appt_id = data.get('id')
        new_status = data.get('status')
        hospital_id = data.get('hospitalId')
        
        if not appt_id or not new_status:
            return Response({"error": "id and status required"}, status=400)
            
        update_data = {"status": new_status}
        if request.data.get('reason'):
            update_data['rejectionReason'] = request.data.get('reason')
            
        db.appointments.update_one(
            {"_id": ObjectId(appt_id)},
            {"$set": update_data}
        )
        
        if new_status == 'Completed' and hospital_id:
            appt = db.appointments.find_one({"_id": ObjectId(appt_id)})
            if appt:
                donor_id = appt.get('donorId')
                donor = db.users.find_one({"_id": ObjectId(donor_id)})
                bg = donor.get('bloodGroup') if donor else appt.get('bloodGroup')
                units = int(appt.get('units', 1))
                
                # 1. Update Inventory
                if bg:
                    db.inventory.update_one(
                        {"hospitalId": hospital_id},
                        {"$inc": {bg: units}},
                        upsert=True
                    )
                    
                    # 2. Create Blood Batch (New Feature)
                    expiry_date = (datetime.datetime.now() + datetime.timedelta(days=42)).isoformat()
                    batch_data = {
                        "hospitalId": hospital_id,
                        "bloodGroup": bg,
                        "componentType": "Whole Blood",
                        "units": units,
                        "collectedDate": datetime.datetime.now().isoformat(),
                        "expiryDate": expiry_date,
                        "sourceType": "Voluntary", 
                        "sourceName": donor.get('name', 'Voluntary Donor') if donor else 'Voluntary Donor',
                        "location": "Hospital Camp",
                        "status": "Active",
                        "createdAt": datetime.datetime.now().isoformat()
                    }
                    db.blood_batches.insert_one(batch_data)

                # 3. Update Donor Stats
                if donor_id:
                     db.users.update_one(
                        {"_id": ObjectId(donor_id)},
                        {"$set": {"lastDonationDate": datetime.datetime.now().isoformat()}}
                     )
        
        return Response({"success": True})

class AdminStatsView(APIView):
    def get(self, request):
        db = get_db()
        total_donors = db.users.count_documents({"role": "donor"})
        total_hospitals = db.users.count_documents({"role": "hospital"})
        active_requests = db.requests.count_documents({"status": "Accepted"}) 
        emergency_alerts = db.requests.count_documents({"type": "EMERGENCY_ALERT", "status": "Active"})
        return Response({
            "totalDonors": total_donors,
            "totalHospitals": total_hospitals,
            "activeRequests": active_requests,
            "emergencyAlerts": emergency_alerts
        })

class AdminDonorSearchView(APIView):
    def get(self, request):
        db = get_db()
        blood_group = request.query_params.get('bloodGroup')
        query = {"role": "donor"}
        if blood_group:
            query["bloodGroup"] = blood_group
        eligible_only = request.query_params.get('eligibleOnly')
        cursor = db.users.find(query)
        donors = []
        now = datetime.datetime.now(datetime.timezone.utc)
        for doc in cursor:
            is_eligible = True
            last_date_str = doc.get('lastDonationDate')
            if last_date_str:
                try:
                    if last_date_str.endswith('Z'):
                         last_date_str = last_date_str[:-1]
                    last_date = datetime.datetime.fromisoformat(last_date_str)
                    if last_date.tzinfo is None:
                        last_date = last_date.replace(tzinfo=datetime.timezone.utc)
                    diff = now - last_date
                    if diff.days < 60:
                        is_eligible = False
                except:
                    pass
            doc['isEligible'] = is_eligible
            doc['status'] = 'Active' if is_eligible else 'Cooling Period'
            if eligible_only == 'true' and not is_eligible:
                continue
            donors.append(serialize_doc(doc))
        return Response(donors)

class UserManagementView(APIView):
    def get(self, request):
        db = get_db()
        role = request.query_params.get('role')
        if not role:
             return Response({"error": "role required"}, status=400)
        cursor = db.users.find({"role": role})
        users = [serialize_doc(doc) for doc in cursor]
        return Response(users)
        
    def delete(self, request):
        db = get_db()
        user_id = request.query_params.get('id')
        if not user_id:
             return Response({"error": "id required"}, status=400)
        try:
            db.users.delete_one({"_id": ObjectId(user_id)})
            return Response({"success": True})
        except Exception as e:
            return Response({"error": str(e)}, status=500)

class AdminAlertsView(APIView):
    def get(self, request):
        db = get_db()
        cursor = db.requests.find({
            "type": "EMERGENCY_ALERT", 
            "status": {"$in": ["Active", "Accepted"]}
        }).sort("date", -1)
        return Response([serialize_doc(doc) for doc in cursor])

class NotificationView(APIView):
    def get(self, request):
        db = get_db()
        user_id = request.query_params.get('userId')
        if not user_id:
            return Response({"error": "userId required"}, status=400)
        cursor = db.notifications.find({"userId": user_id}).sort("timestamp", -1)
        return Response([serialize_doc(n) for n in cursor])

    def post(self, request):
        db = get_db()
        data = request.data.get('notifications')
        if not data or not isinstance(data, list):
             return Response({"error": "Invalid data format"}, status=400)
        db.notifications.insert_many(data)
        return Response({"success": True, "count": len(data)})

    def put(self, request):
        db = get_db()
        notif_id = request.data.get('id')
        status = request.data.get('status')
        result = db.notifications.find_one_and_update(
            {"_id": ObjectId(notif_id)},
            {"$set": {"status": status}},
            return_document=True
        )
        if status == 'ACCEPTED' and result and result.get('relatedRequestId'):
            req_id = result.get('relatedRequestId')
            recipient_id = result.get('recipientId')
            db.requests.update_one(
                {"_id": ObjectId(req_id)},
                {"$set": {
                    "status": "Accepted",
                    "acceptedBy": recipient_id,
                    "acceptedAt": datetime.datetime.now().isoformat()
                }}
            )
            db.notifications.delete_many({
                "relatedRequestId": req_id,
                "_id": {"$ne": ObjectId(notif_id)}
            })
        return Response({"success": True})

class AlertResponseView(APIView):
    def post(self, request):
        db = get_db()
        data = request.data
        alert_id = data.get('alertId')
        donor_id = data.get('donorId')
        status_val = data.get('status')
        location = data.get('location') # Coordinates or Address
        
        if not alert_id or not donor_id:
            return Response({"error": "Data missing"}, status=400)
            
        # Update Request Status to 'Accepted' immediately
        # Also store who accepted it and their location
        donor = db.users.find_one({"_id": ObjectId(donor_id)})
        
        update_data = {
            "status": "Accepted",
            "acceptedBy": donor_id,
            "acceptedAt": datetime.datetime.now().isoformat(),
            "responderName": donor.get('name') if donor else "Unknown",
            "responderPhone": donor.get('phone') if donor else "N/A",
            "responderLocation": location
        }
        
        db.requests.update_one(
            {"_id": ObjectId(alert_id)},
            {"$set": update_data}
        )
        
        # We could also create a notification for the Requester here if needed
        
        return Response({"success": True})

class MyRequestsView(APIView):
    def get(self, request):
        db = get_db()
        user_id = request.query_params.get('userId')
        if not user_id:
             return Response({"error": "userId required"}, status=400)
             
        cursor = db.requests.find({"requesterId": user_id}).sort("date", -1)
        my_reqs = [serialize_doc(doc) for doc in cursor]
        return Response(my_reqs)

class GlobalInventoryView(APIView):
    def get(self, request):
         db = get_db()
         cursor = db.inventory.find({})
         # Aggregate
         total = {"A+": 0, "A-": 0, "B+": 0, "B-": 0, "AB+": 0, "AB-": 0, "O+": 0, "O-": 0}
         for inv in cursor:
             for key in total:
                 total[key] += inv.get(key, 0)
         return Response(total)

class ProfileUpdateView(APIView):
    def post(self, request):
        db = get_db()
        user_id = request.data.get('userId')
        data = request.data.get('data')
        db.users.update_one({"_id": ObjectId(user_id)}, {"$set": data})
        return Response({"success": True})

class AdminDonationHistoryView(APIView):
    def get(self, request):
        db = get_db()
        cursor = db.appointments.find({"status": "Completed"}).sort("date", -1)
        return Response([serialize_doc(doc) for doc in cursor])

class AdminAnalyticsView(APIView):
    def get(self, request):
        # Determine analytics
        return Response({"success": True}) # minimal for now

class ForgotPasswordView(APIView):
    def post(self, request):
        # Mock implementation
        return Response({"success": True})

# ==========================================
# NEW FEATURES IMPLEMENTATION
# ==========================================

class HospitalDonorListView(APIView):
    """
    H7: Hospital Viewing Donors (replaces Admin functionality)
    """
    def get(self, request):
        db = get_db()
        blood_group = request.query_params.get('bloodGroup')
        
        # Handle multiple cities (param can be multiple 'city' keys or comma-separated)
        cities = request.query_params.getlist('city')
        if not cities and request.query_params.get('city'):
             cities = request.query_params.get('city').split(',')
             
        query = {"role": "donor"}
        
        if blood_group:
            query["bloodGroup"] = blood_group
            
        if cities:
            # Case-insensitive match for cities
            city_regexes = [re.compile(f"^{c}$", re.IGNORECASE) for c in cities]
            query["location"] = {"$in": city_regexes}

        cursor = db.users.find(query)
        donors = []
        
        for d in cursor:
            # Calculate Eligibility dynamically
            is_eligible = True
            last_date_str = d.get('lastDonationDate')
            if last_date_str:
                try:
                    last_date = datetime.datetime.fromisoformat(last_date_str.replace('Z', '+00:00'))
                    # Ensure timezone awareness
                    now = datetime.datetime.now(datetime.timezone.utc)
                    if last_date.tzinfo is None:
                        last_date = last_date.replace(tzinfo=datetime.timezone.utc)
                        
                    diff = now - last_date
                    if diff.days < 60:
                        is_eligible = False
                except Exception as e:
                    print(f"Date parse error: {e}")
                    pass
            
            # Strict Filter: Only return eligible donors
            if is_eligible:
                d['eligibility'] = 'Eligible'
                donors.append(serialize_doc(d))
                
        return Response(donors)

class HospitalReportsView(APIView):
    """
    H9: Hospital Reports
    """
    def get(self, request):
        db = get_db()
        user_id = request.query_params.get('userId') # Note: Endpoint might need this param
        
        # Mock Aggregation for now, or actual DB calls
        # 1. Total Units Dispatched
        dispatched = db.dispatches.count_documents({}) # Filter by hospitalId if needed
        # 2. Total Units Collected (Stock entries)
        collected = db.stock_logs.count_documents({"type": "Stock Entry"})
        # 3. Requests Fulfilled
        fulfilled = db.requests.count_documents({"status": "Completed"})
        
        report_data = {
            "dispatched": dispatched,
            "collected": collected,
            "fulfilled": fulfilled,
            # Real logs from Stock Logs
            "logs": [serialize_doc(d) for d in db.stock_logs.find().sort("date", -1).limit(10)]
        }
        return Response(report_data)

class HospitalDispatchView(APIView):
    """
    H5: Dispatch Blood
    """
    def post(self, request):
        db = get_db()
        data = request.data
        data['date'] = datetime.datetime.now().isoformat()
        data['status'] = 'Dispatched'
        
        res = db.dispatches.insert_one(data)
        
        # Decrement Inventory logic if needed
        # Assuming dispatch consumes stock
        if data.get('hospitalId') and data.get('units') and data.get('bloodGroup'):
            db.inventory.update_one(
                {"hospitalId": data.get('hospitalId')},
                {"$inc": {data.get('bloodGroup'): -int(data.get('units'))}}
            )
            
        return Response({"success": True, "id": str(res.inserted_id)})

class HospitalReceiveView(APIView):
    """
    H6: Receive Blood Confirmation
    """
    def post(self, request):
        db = get_db()
        data = request.data
        # Update dispatch status
        dispatch_id = data.get('dispatchId')
        if dispatch_id:
            db.dispatches.update_one(
                {"_id": ObjectId(dispatch_id)},
                {"$set": {"status": "Received", "receivedAt": datetime.datetime.now().isoformat()}}
            )
            
        # Increment Inventory
        if data.get('hospitalId') and data.get('units') and data.get('bloodGroup'):
            db.inventory.update_one(
                {"hospitalId": data.get('hospitalId')},
                {"$inc": {data.get('bloodGroup'): int(data.get('units'))}},
                upsert=True
            )
            
            # Log Stock Entry
            db.stock_logs.insert_one({
                "hospitalId": data.get('hospitalId'),
                "bloodGroup": data.get('bloodGroup'),
                "units": int(data.get('units')),
                "type": "Stock Entry",
                "source": "Received Dispatch",
                "date": datetime.datetime.now().isoformat()
            })
            
        return Response({"success": True})

class DonorP2PRequestView(APIView):
    """
    D5: Donor P2P Request
    """
    def post(self, request):
        db = get_db()
        data = request.data
        data['date'] = datetime.datetime.now().isoformat()
        data['status'] = 'Pending'
        data['type'] = 'P2P' # Explicit type
        
        # Ensure we capture requesterId (The Donor)
        # Should be passed in data
        
        res = db.requests.insert_one(data)
        
        # BROADCAST NOTIFICATIONS
        # Find donors in the same city, excluding the requester
        target_city = data.get('city')
        requester_id = data.get('requesterId')
        
        if target_city:
            # Case-insensitive city match attempt (or exact match depending on data quality)
            # Assuming 'location' or 'city' field in User model. 
            # In RegisterView we saw 'location' field. Let's assume it stores city or address containing city.
            # For simplicity, we use regex or exact match if location field holds City.
            
            potential_donors = db.users.find({
                "role": "donor", 
                "location": {"$regex": target_city, "$options": "i"},
                "_id": {"$ne": ObjectId(requester_id) if requester_id else None}
            })
            
            notifs = []
            for donor in potential_donors:
                notifs.append({
                    "userId": str(donor['_id']),
                    "message": f"Urgent: {data.get('bloodGroup')} needed at {data.get('hospitalName')} in {target_city}.",
                    "type": "EMERGENCY_ALERT",
                    "relatedRequestId": str(res.inserted_id),
                    "status": "UNREAD",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "expiresAt": (datetime.datetime.now() + datetime.timedelta(hours=24)).isoformat()
                })
            
            if notifs:
                db.notifications.insert_many(notifs)

        return Response({"success": True, "id": str(res.inserted_id)})

class ActiveLocationsView(APIView):
    """
    Get unique locations where donors are registered.
    """
    def get(self, request):
        db = get_db()
        # Find distinct locations for users with role='donor'
        locations = db.users.find({"role": "donor"}).distinct("location")
        # Filter out nulls or empty strings just in case
        valid_locations = [loc for loc in locations if loc]
        return Response(valid_locations)

class CompleteRequestView(APIView):
    """
    Mark P2P request as completed and record donation history for the responder.
    """
    def post(self, request):
        db = get_db()
        req_id = request.data.get('requestId')
        
        if not req_id:
            return Response({"error": "requestId required"}, status=400)

        # 1. Update Request Status
        req = db.requests.find_one_and_update(
            {"_id": ObjectId(req_id)},
            {"$set": {"status": "Completed"}},
            return_document=True
        )
        
        if not req:
            return Response({"error": "Request not found"}, status=404)
            
        # 2. Add to Donor's History (if a responder was assigned)
        # We look for 'acceptedBy' which stores the donor's ID
        donor_id = req.get('acceptedBy')
        if donor_id:
            history_entry = {
                "donorId": donor_id,
                "date": datetime.datetime.now().isoformat(),
                "hospitalName": req.get('hospitalName'), # Or "P2P Donation"
                "units": req.get('units', 1),
                "type": "P2P Donation",
                "status": "Completed", # Explicitly completed
                "requestId": req_id
            }
            db.appointments.insert_one(history_entry)
            
            db.appointments.insert_one(history_entry)
            
            # 3. Update Donor Stats
            db.users.update_one(
                {"_id": ObjectId(donor_id)},
                {
                    "$set": {"lastDonationDate": datetime.datetime.now().isoformat()},
                    "$inc": {"donationCount": int(req.get('units', 1))}
                }
            )
            
        return Response({"success": True})

class BloodBatchView(APIView):
    """
    Manage individual blood batches (cards).
    GET: List all active batches for a hospital.
    POST: Create a new batch (and increment global inventory).
    """
    def get(self, request):
        db = get_db()
        hospital_id = request.query_params.get('hospitalId')
        if not hospital_id:
            return Response({"error": "hospitalId required"}, status=400)
            
        # Find active batches (units > 0)
        cursor = db.blood_batches.find({"hospitalId": hospital_id, "units": {"$gt": 0}}).sort("collectedDate", -1)
        batches = [serialize_doc(doc) for doc in cursor]
        return Response(batches)

    def post(self, request):
        try:
            db = get_db()
            data = request.data
            hospital_id = data.get('hospitalId')
            
            print(f"DEBUG: Batch Create Payload: {data}")
            
            if not hospital_id:
                print("DEBUG: Missing hospitalId")
                return Response({"error": "hospitalId required"}, status=400)
                
            try:
                units = int(data.get('units', 0))
            except (ValueError, TypeError):
                print("DEBUG: Invalid units format")
                return Response({"error": "Invalid units format"}, status=400)
                
            if units <= 0:
                 print("DEBUG: Units must be positive")
                 return Response({"error": "Units must be > 0"}, status=400)

            # 1. Create Batch
            batch = {
                "hospitalId": hospital_id,
                "bloodGroup": data.get('bloodGroup'),
                "componentType": data.get('componentType'), # e.g., Whole Blood, Platelets
                "units": units,
                "collectedDate": data.get('collectedDate'),
                "expiryDate": data.get('expiryDate'),
                "sourceType": data.get('sourceType'),
                "sourceName": data.get('sourceName'),
                "location": data.get('location'),
                "status": "Active",
                "createdAt": datetime.datetime.now().isoformat()
            }
            res = db.blood_batches.insert_one(batch)
            
            # 2. Update Global Inventory (Increment)
            group = data.get('bloodGroup')
            
            if group:
                db.inventory.update_one(
                    {"hospitalId": hospital_id},
                    {"$inc": {group: units}},
                    upsert=True
                )
            
            return Response({"success": True, "id": str(res.inserted_id)})
        except Exception as e:
            print(f"ERROR in BloodBatchView: {e}")
            import traceback
            traceback.print_exc()
            return Response({"error": str(e)}, status=500)
        


class BatchActionView(APIView):
    """
    Handle actions on a batch (e.g., Use Unit).
    """
    def post(self, request):
        db = get_db()
        batch_id = request.data.get('batchId')
        action = request.data.get('action') # 'use_unit'
        quantity = int(request.data.get('quantity', 1))
        
        if not batch_id:
             return Response({"error": "batchId required"}, status=400)
             
        batch = db.blood_batches.find_one({"_id": ObjectId(batch_id)})
        if not batch:
            return Response({"error": "Batch not found"}, status=404)
            
        if action == 'use_unit':
            if batch['units'] < quantity:
                return Response({"error": "Not enough units in batch"}, status=400)
                
            # 1. Decrement Batch
            updated_batch = db.blood_batches.find_one_and_update(
                {"_id": ObjectId(batch_id)},
                {"$inc": {"units": -quantity}},
                return_document=True
            )
            
            # If units reach 0, mark as exhausted? Optional, kept simple as units check > 0 in GET
            
            # 2. Decrement Global Inventory
            hospital_id = batch['hospitalId']
            group = batch['bloodGroup']
            
            db.inventory.update_one(
                {"hospitalId": hospital_id},
                {"$inc": {group: -quantity}}
            )
            
            return Response({"success": True, "remaining": updated_batch['units']})
            
        return Response({"error": "Invalid action"}, status=400)

# ==========================================
#  MISSING VIEWS IMPLEMENTATION
# ==========================================

class AlertResponseView(APIView):
    """
    Handle Donor Response to Emergency/P2P Request.
    """
    def post(self, request):
        db = get_db()
        data = request.data
        req_id = data.get('requestId')
        responder_id = data.get('userId') # Donor ID
        status = data.get('status') # 'Accepted' or 'Rejected'
        msg = data.get('message')
        
        if not req_id or not responder_id:
            return Response({"error": "Request ID and User ID required"}, status=400)
            
        # Update Request
        update_fields = {"status": status}
        if status == 'Accepted':
            update_fields["acceptedBy"] = responder_id
            update_fields["responseMessage"] = msg
            
        req = db.requests.find_one_and_update(
            {"_id": ObjectId(req_id)},
            {"$set": update_fields},
            return_document=True
        )
        
        if not req:
             return Response({"error": "Request not found"}, status=404)

        # Notify Requester (Hospital or Donor) if Accepted
        if status == 'Accepted':
            requester_id = req.get('requesterId')
            # Fallback for Hospital-created requests where requesterId might be null/different in old schema
            if not requester_id and req.get('hospitalId') and not req.get('isBroadcast'):
                 requester_id = req.get('hospitalId') # If direct P2P? Rare.
                 
            if requester_id:
                responder = db.users.find_one({"_id": ObjectId(responder_id)})
                resp_name = responder.get('name', 'A Donor') if responder else 'A Donor'
                
                notif_text = f"{resp_name} accepted your request!"
                if msg:
                    notif_text += f" Message: {msg}"
                
                db.notifications.insert_one({
                    "userId": requester_id,
                    "message": notif_text,
                    "type": "REQUEST_ACCEPTED",
                    "relatedRequestId": req_id,
                    "status": "UNREAD",
                    "timestamp": datetime.datetime.now().isoformat()
                })

        return Response({"success": True})

class IgnoreRequestView(APIView):
    def post(self, request):
        db = get_db()
        data = request.data
        req_id = data.get('requestId')
        user_id = data.get('userId')
        
        if not req_id or not user_id:
             return Response({"error": "Missing params"}, status=400)
             
        db.requests.update_one(
            {"_id": ObjectId(req_id)},
            {"$addToSet": {"ignoredBy": user_id}}
        )
        return Response({"success": True})

class DonorCountView(APIView):
    def get(self, request):
        db = get_db()
        cities = request.query_params.getlist('city')
        # Also support comma separated if single param
        if len(cities) == 1 and ',' in cities[0]:
             cities = [c.strip() for c in cities[0].split(',')]
             
        if not cities:
             return Response({"count": 0})
        
        # 60 Days Rule: Eligible if lastDonationDate is None OR > 60 days ago
        sixty_days_ago = datetime.datetime.now() - datetime.timedelta(days=60)
        
        # Build City Regex (Match ANY of the selected cities)
        city_regex = "|".join([str(c) for c in cities])
        
        # Blood Group Filter
        req_blood_group = request.query_params.get('bloodGroup')
        filter_query = {
            "role": "donor",
            "location": {"$regex": city_regex, "$options": "i"},
            "$or": [
                {"lastDonationDate": None},
                {"lastDonationDate": {"$eq": ""}},
                {"lastDonationDate": {"$lt": sixty_days_ago.isoformat()}} 
            ]
        }
        
        if req_blood_group:
             # Strict Filtering: Only exact match
             # "O+ na O+ donors aah mattum filter pnnau"
             filter_query['bloodGroup'] = req_blood_group

        count = db.users.count_documents(filter_query)
        return Response({"count": count})

class ActiveLocationsView(APIView):
    def get(self, request):
        db = get_db()
        locations = db.users.distinct("location", {"role": "donor"})
        cities = set()
        for loc in locations:
            if loc:
                parts = loc.split(',')
                if len(parts) > 0:
                    cities.add(parts[0].strip())
        return Response(list(cities))

class DonorP2PRequestView(APIView):
    def post(self, request):
        db = get_db()
        data = request.data
        
        requester_id = data.get('requesterId')
        cities = data.get('cities') # Now expecting a list
        
        # Legacy support for single 'city'
        if not cities and data.get('city'):
             cities = [data.get('city')]
        
        if not requester_id or not cities:
            return Response({"error": "Requester ID and City(s) required"}, status=400)
            
        req_blood_group = data.get('bloodGroup', '').strip()
        if not req_blood_group:
             return Response({"error": "Blood Group is required for P2P requests"}, status=400)

        # 1. Create Request
        new_req = {
            "requesterId": requester_id,
            "patientName": data.get('patientName'),
            "patientNumber": data.get('patientNumber'),
            "attenderName": data.get('attenderName'),
            "attenderNumber": data.get('attenderNumber'),
            "bloodGroup": req_blood_group,
            "units": data.get('units'),
            "urgency": data.get('urgency'),
            "hospitalName": data.get('hospitalName'),
            "location": data.get('location'), 
            "city": ", ".join(cities), # Store as string for display
            "cities": cities, # Store raw list
            "status": "Pending",
            "date": datetime.datetime.now().isoformat(),
            "type": "P2P"
        }
        res = db.requests.insert_one(new_req)
        req_id = str(res.inserted_id)
        
        # 2. Notification Logic
        # Match ANY city
        city_regex = "|".join([str(c) for c in cities])
        
        query_filter = {
            "role": "donor",
            "_id": {"$ne": ObjectId(requester_id)},
            "location": {"$regex": city_regex, "$options": "i"}
        }
        
        # Strict Filtering: Only exact match as per user request
        if req_blood_group:
             query_filter['bloodGroup'] = req_blood_group
        
        target_donors = db.users.find(query_filter)
        
        donors_list = list(target_donors)
        notif_msg = f"Urgent: {data.get('bloodGroup')} needed in {'/'.join(cities)}!"
        
        notifications_to_insert = []
        fcm_tokens = []
        
        for donor in donors_list:
            # Check Eligibility (60 days)
            is_eligible = True
            last_date_str = donor.get('lastDonationDate')
            if last_date_str:
                try:
                    # Parse ISO format or Date Only
                    if 'T' in last_date_str:
                        last_date = datetime.datetime.fromisoformat(last_date_str.replace('Z', '+00:00'))
                    else:
                        last_date = datetime.datetime.strptime(last_date_str, "%Y-%m-%d")
                        
                    # Ensure timezone awareness for comparison
                    now = datetime.datetime.now(datetime.timezone.utc)
                    if last_date.tzinfo is None:
                        last_date = last_date.replace(tzinfo=datetime.timezone.utc)
                        
                    diff = now - last_date
                    if diff.days < 60:
                        is_eligible = False
                except Exception as e:
                    print(f"Date parse error for donor {donor.get('_id')}: {e}")
                    pass
            
            if not is_eligible:
                continue

            notifications_to_insert.append({
                "userId": str(donor['_id']),
                "message": notif_msg,
                "type": "URGENT_REQUEST",
                "requestId": req_id,
                "status": "UNREAD",
                "timestamp": datetime.datetime.now().isoformat()
            })
            if donor.get('fcmToken'):
                 fcm_tokens.append(donor.get('fcmToken'))

        if notifications_to_insert:
            db.notifications.insert_many(notifications_to_insert)
            notification_count = len(notifications_to_insert)

            # Send FCM Notifications
            if fcm_tokens:
                try:
                    message = messaging.MulticastMessage(
                        notification=messaging.Notification(
                            title="Urgent: Blood Needed!",
                            body=notif_msg,
                        ),
                        data={
                            "type": "URGENT_REQUEST",
                            "requestId": req_id
                        },
                        tokens=fcm_tokens,
                    )
                    response = messaging.send_each_for_multicast(message)
                    print(f"FCM Sent: {response.success_count} success, {response.failure_count} failures")
                except Exception as e:
                    print(f"FCM Send Error: {e}")
            
        return Response({
            "success": True, 
            "requestId": req_id, 
            "notifiedCount": notification_count
        })

# Placeholders for Hospital Views to prevent Import Errors
class HospitalDonorListView(APIView):
    def get(self, request):
        db = get_db()
        blood_group = request.query_params.get('bloodGroup', '').strip()
        requested_cities = request.query_params.get('city', '')
        
        if not blood_group:
             return Response({"error": "Blood Group is required"}, status=400)

        # Build Query
        query = {
            "role": "donor",
            "bloodGroup": blood_group # Strict Match
        }
        
        # City Filter
        if requested_cities:
            # Handle comma-separated list or single city
            city_list = [c.strip() for c in requested_cities.split(',') if c.strip()]
            if city_list:
                city_regex = "|".join([re.escape(c) for c in city_list])
                query["location"] = {"$regex": city_regex, "$options": "i"}

        donors = db.users.find(query)
        eligible_donors = []
        
        for d in donors:
             # Check Eligibility (60 days)
             last_date_str = d.get('lastDonationDate')
             is_eligible = True
             if last_date_str:
                try:
                    # Handle typical formats: ISO with 'T' or simple Date 'YYYY-MM-DD'
                    if 'T' in last_date_str:
                        last_date = datetime.datetime.fromisoformat(last_date_str.replace('Z', '+00:00'))
                    else:
                        # Assume YYYY-MM-DD
                        last_date = datetime.datetime.strptime(last_date_str, "%Y-%m-%d")
                        last_date = last_date.replace(tzinfo=datetime.timezone.utc) # Make aware

                    # Ensure we compare apples to apples (UTC)
                    if last_date.tzinfo is None:
                            last_date = last_date.replace(tzinfo=datetime.timezone.utc)
                            
                    now_utc = datetime.datetime.now(datetime.timezone.utc)
                    sixty_days_ago = now_utc - datetime.timedelta(days=60)
                    
                    if last_date > sixty_days_ago:
                        # Donated recently, not eligible
                        is_eligible = False 
                except Exception as e:
                    print(f"Date parse error for user {d.get('_id')}: {e}")
                    # Safety Fallback: If we can't verify the date, assume ineligible if it exists? 
                    # Or assume user entered garbage and is eligible? 
                    # Let's keep it lenient for now but consistent.
                    pass
            
             if is_eligible:
                 eligible_donors.append({
                     "id": str(d['_id']),
                     "name": d.get('name', 'Anonymous'),
                     "phone": d.get('phone', 'N/A'), # Requested by user
                     "bloodGroup": d.get('bloodGroup'),
                     "location": d.get('location'),
                     "lastDonationDate": d.get('lastDonationDate')
                 })
                 
        return Response(eligible_donors)

class HospitalReportsView(APIView):
    def get(self, request):
         return Response({})

class HospitalDispatchView(APIView):
    def post(self, request):
         return Response({"success": True})

class HospitalReceiveView(APIView):
    def post(self, request):
         return Response({"success": True})

class MyRequestsView(APIView):
     def get(self, request):
        db = get_db()
        user_id = request.query_params.get('userId')
        print(f"DEBUG: MyRequestsView called with userId={user_id}")
        if not user_id:
            return Response([])
        requests = db.requests.find({"requesterId": user_id}).sort("date", -1)
        res = []
        for r in requests:
            r['id'] = str(r['_id'])
            del r['_id']
            res.append(r)
        print(f"DEBUG: Found {len(res)} requests for {user_id}")
        return Response(res)

class CompleteRequestView(APIView):
    def post(self, request):
        db = get_db()
        req_id = request.data.get('requestId')
        
        if not req_id:
             return Response({"error": "Request ID required"}, status=400)
             
        # 1. Update Request Status to Completed
        req = db.requests.find_one_and_update(
            {"_id": ObjectId(req_id)},
            {"$set": {"status": "Completed"}},
            return_document=True
        )
        
        if not req:
             return Response({"error": "Request not found"}, status=404)
        
        # 2. Update Responder (Donor) Stats
        responder_id = req.get('acceptedBy')
        
        if responder_id:
            # A. Update User Stats
            current_date = datetime.datetime.now().isoformat()
            db.users.update_one(
                {"_id": ObjectId(responder_id)},
                {
                    "$set": {"lastDonationDate": current_date},
                    "$inc": {"donationCount": 1}
                }
            )
            
            # B. Add to History (Standardized to Appointments Collection)
            history_entry = {
                "donorId": responder_id, # Must match 'donorId' in appointments schema
                "date": current_date,
                "type": "P2P Donation",
                "units": int(req.get('units', 1)),
                "center": req.get('hospitalName') or req.get('location') or "P2P Location", # mapped to 'center' in history view
                "bloodGroup": req.get('bloodGroup'),
                "status": "Completed", # Important for stats count
                "requestId": req_id
            }
            # Use appointments collection as the Single Source of Truth
            db.appointments.insert_one(history_entry)

        return Response({"success": True})

class HospitalSearchView(APIView):
    """
    Search for other hospitals with specific blood stock.
    GET params: bloodGroup, lat, lng (optional)
    """
    def get(self, request):
        db = get_db()
        blood_group = request.query_params.get('bloodGroup')
        
        if not blood_group:
             return Response({"error": "Blood Group required"}, status=400)
             
        # Find Inventory documents where [bloodGroup] > 0
        query = {
             blood_group: {"$gt": 0}
        }
        
        cursor = db.inventory.find(query)
        
        results = []
        for inv in cursor:
            hospital_id = inv.get('hospitalId')
            if not hospital_id:
                continue
                
            hospital = db.users.find_one({"_id": ObjectId(hospital_id)})
            if not hospital:
                continue
            
            results.append({
                "id": str(hospital['_id']),
                "name": hospital.get('name'),
                "location": hospital.get('location'),
                "units": inv.get(blood_group),
                "distance": "5 km" # Placeholder
            })
            
        return Response(results)
