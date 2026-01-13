from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .db import get_db
from bson import ObjectId
import datetime
import math

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
        
        db.inventory.update_one(
            {"hospitalId": user_id},
            {"$set": data},
            upsert=True
        )
        return Response({"success": True})

class HospitalRequestsView(APIView):

from firebase_admin import messaging
from .firebase_config import initialize_firebase # Init on load

class SaveFCMTokenView(APIView):
    def post(self, request):
        db = get_db()
        user_id = request.data.get('userId')
        token = request.data.get('token')
        
        if not user_id or not token:
            return Response({"error": "userId and token required"}, status=400)
            
        # Update user with FCM token (add to list or replace single)
        # We'll replace for simplicity per device, or use $addToSet for multi-device
        db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"fcmToken": token}}
        )
        return Response({"success": True})

# ... (Existing classes) ...

class HospitalRequestsView(APIView):
    # ... (GET method unchanged) ...
    def get(self, request):
        db = get_db()
        user_id = request.query_params.get('userId')
        
        # 1. OUTGOING: Requests CREATED BY ME
        # "requesterId" is the consistent field for who asked.
        # Fallback to "hospitalId" if requesterId missing (legacy/emergency sometimes) AND type is NOT P2P (because in P2P hospitalId is Target)
        outgoing_query = {
            "$or": [
                {"requesterId": user_id},
                # For older records where maybe only hospitalId was set and it meant "Creator"
                {"hospitalId": user_id, "type": {"$ne": "P2P"}} 
            ]
        }
        my_requests_cursor = db.requests.find(outgoing_query).sort("date", -1)
        
        # 2. INCOMING: Requests I CAN FULFILL
        # A) P2P Requests sent TO ME (hospitalId == user_id AND type == 'P2P')
        # B) Emergency Alerts from OTHERS (requesterId != user_id AND type == 'EMERGENCY_ALERT')
        incoming_query = {
            "$or": [
                {"hospitalId": user_id, "type": "P2P"}, # Directed to me
                {"type": "EMERGENCY_ALERT", "requesterId": {"$ne": user_id}} # Broadcast from others
            ]
            # Removed Status filter to allow History (Completed/Rejected) to be fetched
        }
        
        incoming_cursor = db.requests.find(incoming_query).sort("date", -1)
        incoming_list = list(incoming_cursor)

        requests = []
        
        # Process My Requests (Outgoing)
        for req in my_requests_cursor:
            req['isOutgoing'] = True
            if req.get('acceptedBy'):
                donor = db.users.find_one({"_id": ObjectId(req['acceptedBy'])})
                req['donorName'] = donor.get('name') if donor else "Unknown Donor"
            
            requests.append(serialize_doc(req))
            
        # Process Incoming Requests (Incoming)
        for req in incoming_list:
            req['isOutgoing'] = False
            
            # If accepted by someone else, hide it (unless I accepted it)
            if req.get('acceptedBy') and req.get('acceptedBy') != user_id:
                continue 

            # Fetch Requester Name (Who is asking?)
            # If P2P, requesterId is the source. If Emergency, requesterId/hospitalId is source.
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
        
        # Calculate Expiration Time based on requiredTime
        req_time = data.get('requiredTime')
        if req_time:
            now = datetime.datetime.now()
            delta = datetime.timedelta(hours=24) # Default fallback
            
            if '30 mins' in req_time:
                delta = datetime.timedelta(minutes=30)
            elif '1 Hour' in req_time:
                delta = datetime.timedelta(hours=1)
            elif '2 Hours' in req_time:
                delta = datetime.timedelta(hours=2)
            elif '4 Hours' in req_time:
                delta = datetime.timedelta(hours=4)
            elif 'Today' in req_time:
                # End of day
                params = now.replace(hour=23, minute=59, second=59)
                delta = params - now
            
            data['expiresAt'] = (now + delta).isoformat()
        
        # Ensure units is integer
        if 'units' in data:
            data['units'] = int(data['units'])
            
        res = db.requests.insert_one(data)
        
        # If this is an Emergency Alert, create Notifications for Donors immediately
        if data.get('type') == 'EMERGENCY_ALERT':
             # Find compatible donors (same blood group)
             donors = db.users.find({
                 "role": "donor", 
                 "bloodGroup": data.get('bloodGroup'),
                 "fcmToken": {"$exists": True} # Only send to those with app/token
             })
             
             for d in donors:
                 token = d.get('fcmToken')
                 if token:
                     try:
                        # Construct Messaging
                        message = messaging.Message(
                            notification=messaging.Notification(
                                title="Emergency Blood Request!",
                                body=f"{data.get('units')} units of {data.get('bloodGroup')} needed at {data.get('hospitalName', 'Hospital')}!"
                            ),
                            token=token,
                        )
                        # Send
                        response = messaging.send(message)
                        print('Successfully sent message:', response)
                     except Exception as e:
                         print(f"Error sending FCM: {e}")

        return Response({"success": True, "id": str(res.inserted_id)})

    def put(self, request):
        db = get_db()
        data = request.data
        req_id = data.get('id')
        new_status = data.get('status')
        # ID of the hospital performing the action (Accept/Complete)
        responder_id = data.get('hospitalId') 
        
        if not req_id or not new_status:
            return Response({"error": "id and status are required"}, status=400)
            
        # Update Request
        dataset = {"status": new_status}
        
        # Save optional response message
        if data.get('responseMessage'):
            dataset['responseMessage'] = data.get('responseMessage')
        
        if new_status == 'Accepted':
            if not responder_id:
                return Response({"error": "hospitalId required for acceptance"}, status=400)
            dataset['acceptedBy'] = responder_id
            
        if new_status == 'Completed':
            dataset["completedAt"] = datetime.datetime.now().isoformat()
            
        db.requests.update_one(
            {"_id": ObjectId(req_id)},
            {"$set": dataset}
        )
        
        # If successfully completed, update inventory logic
        if new_status == 'Completed':
            req = db.requests.find_one({"_id": ObjectId(req_id)})
            if req:
                req_type = req.get('type')
                units = int(req.get('units', 1))
                bg = req.get('bloodGroup')
                
                # Determine Who is Who
                if req_type == 'P2P':
                    # P2P: hospitalId is the TARGET (Donor), requesterId is the SOURCE (Need)
                    donor_id = req.get('hospitalId')
                    requester_id = req.get('requesterId')
                else:
                    # Emergency/Broadcast: hospitalId is the SOURCE (Need), acceptedBy is the DONOR
                    donor_id = req.get('acceptedBy')
                    requester_id = req.get('hospitalId')

                # 1. Increment Stock for Requester (They received it)
                if requester_id and bg:
                    db.inventory.update_one(
                        {"hospitalId": requester_id},
                        {"$inc": {bg: units}}, 
                        upsert=True
                    )
                    
                # 2. Decrement Stock for Donor (They gave it)
                if donor_id:
                     db.inventory.update_one(
                        {"hospitalId": donor_id},
                        {"$inc": {bg: -units}}, # Decrease stock
                        upsert=True
                    )
                
                # 3. Add to Donation History (Appointments Collection for consistency)
                # This ensures it appears in Donor's dashboard stats which now uses 'appointments'
                if donor_id:
                     # Check if it's a user (Donor role)
                    donor_user = db.users.find_one({"_id": ObjectId(donor_id)})
                    
                    if donor_user and donor_user.get('role') == 'donor':
                        history_record = {
                            "donorId": donor_id,
                            "hospitalId": requester_id,
                            "hospitalName": req.get('hospitalName') or 'Emergency Request',
                            "date": datetime.datetime.now().isoformat(),
                            "units": units,
                            "bloodGroup": bg,
                            "type": "Emergency Donation", 
                            "status": "Completed"
                        }
                        db.appointments.insert_one(history_record)

        return Response({"success": True})

class HospitalSearchView(APIView):
    def get(self, request):
        db = get_db()
        blood_group = request.query_params.get('bloodGroup')
        user_lat = request.query_params.get('lat')
        user_lng = request.query_params.get('lng')
        
        if not blood_group:
             return Response({"error": "bloodGroup required"}, status=400)

        # 1. Find inventories with stock > 0 for this group
        inventory_query = {blood_group: {"$gt": 0}}
        inventories = list(db.inventory.find(inventory_query))
        
        results = []
        for inv in inventories:
            hospital_id = inv.get('hospitalId')
            units = inv.get(blood_group)
            
            # 2. Get Hospital Details
            if hospital_id:
                try:
                    hospital = db.users.find_one({"_id": ObjectId(hospital_id)})
                    if hospital:
                        # Calculate Distance
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

        # Sort by distance
        results.sort(key=lambda x: x['sort_dist'])
        
        return Response(results)

class ActiveRequestsView(APIView):
    def get(self, request):
        db = get_db()
        # Find all requests that are Pending (Urgent)
        cursor = db.requests.find({"status": "Pending"}).sort("date", -1)
        requests = []
        for req in cursor:
            # Get Hospital Name
            hospital = db.users.find_one({"_id": ObjectId(req['hospitalId'])})
            req['hospitalName'] = hospital.get('name') if hospital else "Unknown Hospital"
            req['location'] = hospital.get('location') if hospital else "Unknown Location"
            
            # Add distance if user location provided (optional enhancement for later)
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
                "name": h.get('name'),
                "location": h.get('location'),
                "phone": h.get('phone')
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
            
        # Match appointments by Hospital ID (Robust) or Center Name (Legacy fallback)
        # Using 'appointments' collection now
        cursor = db.appointments.find({
            "$or": [
                {"hospitalId": user_id},
                {"center": hospital.get('name')}
            ]
        }).sort("date", -1)
        appointments = [serialize_doc(doc) for doc in cursor]
        return Response(appointments)

    def post(self, request):
        db = get_db()
        data = request.data
        appt_id = data.get('id')
        new_status = data.get('status')
        hospital_id = data.get('hospitalId')
        
        if not appt_id or not new_status:
            return Response({"error": "id and status required"}, status=400)
            
        # Update Appointment in 'appointments' collection
        update_data = {"status": new_status}
        
        if request.data.get('reason'):
            update_data['rejectionReason'] = request.data.get('reason')
            
        db.appointments.update_one(
            {"_id": ObjectId(appt_id)},
            {"$set": update_data}
        )
        
        # If successfully completed, update inventory
        if new_status == 'Completed' and hospital_id:
            appt = db.appointments.find_one({"_id": ObjectId(appt_id)})
            if appt:
                donor_id = appt.get('donorId')
                donor = db.users.find_one({"_id": ObjectId(donor_id)})
                
                # Use donor's blood group if available, else from appointment if stored
                bg = donor.get('bloodGroup') if donor else appt.get('bloodGroup')
                units = int(appt.get('units', 1))
                
                if bg:
                    db.inventory.update_one(
                        {"hospitalId": hospital_id},
                        {"$inc": {bg: units}},
                        upsert=True
                    )

                # Update Donor's Last Donation Date (Cached on User Profile)
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
        # User wants "Active Requests" to be "Accepted" ones (In Progress)
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
            
        # Optional: Filter by Eligibility (60 days rule)
        eligible_only = request.query_params.get('eligibleOnly')
        
        cursor = db.users.find(query)
        donors = []
        
        now = datetime.datetime.now(datetime.timezone.utc)
        
        for doc in cursor:
            is_eligible = True
            last_date_str = doc.get('lastDonationDate')
            
            if last_date_str:
                try:
                    # Handle Z suffix and mixed formats
                    if last_date_str.endswith('Z'):
                         last_date_str = last_date_str[:-1]
                    
                    last_date = datetime.datetime.fromisoformat(last_date_str)
                    if last_date.tzinfo is None:
                        last_date = last_date.replace(tzinfo=datetime.timezone.utc)
                        
                    # Calculate difference
                    diff = now - last_date
                    if diff.days < 60:
                        is_eligible = False
                except:
                    pass
            
            doc['isEligible'] = is_eligible
            # Dynamic Status based on eligibility
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
            result = db.users.delete_one({"_id": ObjectId(user_id)})
            if result.deleted_count == 0:
                pass # Fail silently or return success if already gone
                
            return Response({"success": True})
        except Exception as e:
            return Response({"error": str(e)}, status=500)

class AdminAlertsView(APIView):
    def get(self, request):
        db = get_db()
        # Fetch both Active and Accepted alerts so admin sees progress
        cursor = db.requests.find({
            "type": "EMERGENCY_ALERT", 
            "status": {"$in": ["Active", "Accepted"]}
        }).sort("date", -1)
        alerts = [serialize_doc(doc) for doc in cursor]
        return Response(alerts)

class NotificationView(APIView):
    def get(self, request):
        """Fetch notifications for a specific user"""
        db = get_db()
        user_id = request.query_params.get('userId')
        if not user_id:
            return Response({"error": "userId required"}, status=400)
            
        cursor = db.notifications.find({"recipientId": user_id}).sort("timestamp", -1)
        return Response([serialize_doc(n) for n in cursor])

    def post(self, request):
        """Create notifications (Admin sending to Donors)"""
        db = get_db()
        data = request.data.get('notifications') # Expecting list
        
        if not data or not isinstance(data, list):
             return Response({"error": "Invalid data format"}, status=400)
             
        # Insert all
        db.notifications.insert_many(data)
        return Response({"success": True, "count": len(data)})

    def put(self, request):
        """Update notification status (Read/Accepted)"""
        db = get_db()
        notif_id = request.data.get('id')
        status = request.data.get('status')
        
        # 1. Update Notification
        result = db.notifications.find_one_and_update(
            {"_id": ObjectId(notif_id)},
            {"$set": {"status": status}},
            return_document=True
        )
        
        # 2. If Accepted, update the original Request/Alert
        if status == 'ACCEPTED' and result and result.get('relatedRequestId'):
            req_id = result.get('relatedRequestId')
            recipient_id = result.get('recipientId') # The donor
            
            # Check if request is still active/pending
            # We update it to 'Accepted' and assign the donor
            db.requests.update_one(
                {"_id": ObjectId(req_id)},
                {
                    "$set": {
                        "status": "Accepted",
                        "acceptedBy": recipient_id,
                        "acceptedAt": datetime.datetime.now().isoformat()
                    }
                }
            )
            
            # 3. Mutual Exclusion: Delete all other notifications for this request
            # So other donors don't see it anymore
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
        status = data.get('status') # 'Accepted' or 'Declined'
        
        if not alert_id or not donor_id:
            return Response({"error": "Missing data"}, status=400)
            
        if status == 'Accepted':
            # Update request status and assign donor
            db.requests.update_one(
                {"_id": ObjectId(alert_id)},
                {
                    "$set": {
                        "status": "Accepted",
                        "acceptedBy": donor_id,
                        "acceptedAt": datetime.datetime.now().isoformat()
                    }
                }
            )
        
        return Response({"success": True})

class AdminDonorSearchView(APIView):
    def get(self, request):
        db = get_db()
        blood_group = request.query_params.get('bloodGroup')
        
        query = {"role": "donor"}
        if blood_group:
            query["bloodGroup"] = blood_group
            
        # Optional: Filter by Eligibility (60 days rule)
        eligible_only = request.query_params.get('eligibleOnly')
        
        cursor = db.users.find(query)
        donors = []
        
        now = datetime.datetime.now(datetime.timezone.utc)
        
        for doc in cursor:
            is_eligible = True
            last_date_str = doc.get('lastDonationDate')
            
            if last_date_str:
                try:
                    # Handle Z suffix
                    if last_date_str.endswith('Z'):
                         last_date_str = last_date_str[:-1]
                    
                    last_date = datetime.datetime.fromisoformat(last_date_str)
                    if last_date.tzinfo is None:
                        last_date = last_date.replace(tzinfo=datetime.timezone.utc)
                        
                    # Calculate difference
                    diff = now - last_date
                    if diff.days < 60:
                        is_eligible = False
                except:
                    pass
            
            doc['isEligible'] = is_eligible
            
            if eligible_only and not is_eligible:
                continue
                
            donors.append(serialize_doc(doc))
            
        return Response(donors)

class GlobalInventoryView(APIView):
    def get(self, request):
        db = get_db()
        cursor = db.inventory.find({})
        items = []
        for inv in cursor:
            # Map hospitalId to hospital name
            h_name = "Unknown Hospital"
            if inv.get('hospitalId'):
                hospital = db.users.find_one({"_id": ObjectId(inv['hospitalId'])})
                if hospital:
                    h_name = hospital.get('name')
            
            # Iterate all standard keys
            for bg in ['A+', 'A-', 'B+', 'B-', 'O+', 'O-', 'AB+', 'AB-']:
                count = inv.get(bg, 0)
                # We return it if count >= 0 (Frontend aggregates)
                # But to avoid clutter, maybe only > 0? 
                # User complained about "empty values", maybe they want to see 0s too?
                # Reports.jsx aggregates everything.
                if count >= 0:
                   items.append({
                       "id": f"{inv['_id']}_{bg}",
                       "hospital": h_name,
                       "bloodGroup": bg,
                       "units": count,
                       "status": "Good" if count > 20 else "Low" if count > 5 else "Critical"
                   })
                   
        return Response(items)

class ProfileUpdateView(APIView):
    def post(self, request):
        """Update User Profile (Password, Avatar, etc.)"""
        db = get_db()
        user_id = request.data.get('userId')
        data = request.data.get('data', {})
        
        if not user_id:
             return Response({"error": "userId required"}, status=400)
             
        update_fields = {}
        
        # Handle Password Update with Hashing
        if 'password' in data and data['password']:
            from django.contrib.auth.hashers import make_password
            update_fields['password'] = make_password(data['password'])
            
        # Handle other fields (Gender, Name, etc.)
        for field in ['name', 'phone', 'location', 'gender', 'bloodGroup']:
            if field in data:
                update_fields[field] = data[field]
                
        if update_fields:
            db.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": update_fields}
            )
            return Response({"success": True})
        



class AdminDonationHistoryView(APIView):
    def get(self, request):
        db = get_db()
        # Fetch all completed donations/appointments
        donations = list(db.appointments.find({"status": "Completed"}).sort("date", -1))
        
        for d in donations:
            d['id'] = str(d['_id'])
            
            # Lookup Donor Name & Blood Group (if missing in appointment)
            if d.get('donorId'):
                try:
                    donor = db.users.find_one({"_id": ObjectId(d['donorId'])})
                    if donor:
                        d['donorName'] = donor.get('name', "Unknown Donor")
                        if 'bloodGroup' not in d:
                            d['bloodGroup'] = donor.get('bloodGroup', "?")
                    else:
                        d['donorName'] = "Unknown Donor"
                except:
                    d['donorName'] = "Invalid Donor ID"

            # Lookup Hospital Name
            if d.get('hospitalId'):
                try:
                    hospital = db.users.find_one({"_id": ObjectId(d['hospitalId'])})
                    d['hospitalName'] = hospital.get('name', "Unknown Hospital") if hospital else "Unknown Hospital"
                except:
                    d['hospitalName'] = "Invalid Hospital ID"
            else:
                 d['hospitalName'] = "Unknown Hospital"

            del d['_id']
            
        return Response(donations)


class AdminAnalyticsView(APIView):
    def get(self, request):
        db = get_db()
        
        # 1. Donation Trends (Last 6 Months)
        # Using Python processing to avoid aggregation errors with loose date formats
        donations = list(db.appointments.find({"status": "Completed"}))
        monthly_counts = {}
        for d in donations:
            try:
                # Handle ISO format and potential variants
                d_date = d.get('date')
                if not d_date: continue
                # Basic ISO parsing
                if d_date.endswith('Z'):
                    d_date = d_date[:-1]
                dt = datetime.datetime.fromisoformat(d_date)
                key = dt.strftime('%b %Y') # e.g., "Jan 2024"
                monthly_counts[key] = monthly_counts.get(key, 0) + 1
            except Exception as e:
                pass
                
        # Fill last 6 months 
        today = datetime.datetime.now()
        trend_data = []
        for i in range(5, -1, -1):
            date = today - datetime.timedelta(days=i*30)
            key = date.strftime('%b %Y')
            trend_data.append({
                "month": key,
                "count": monthly_counts.get(key, 0)
            })

        # 2. Recent Activities (System Events)
        # Fetch recent Emergency Alerts and New User Registrations
        recent_alerts = list(db.requests.find().sort("timestamp", -1).limit(5))
        
        activities = []
        for alert in recent_alerts:
            activities.append({
                "id": str(alert['_id']),
                "type": "Emergency Alert",
                "desc": f"Alert for {alert.get('units', '?')} units {alert.get('bloodGroup', '?')}",
                "date": alert.get('timestamp')
            })

        # Sort combined activities by date desc
        activities.sort(key=lambda x: x['date'] or '', reverse=True)

        return Response({
            "trends": trend_data,
            "activities": activities
        })
