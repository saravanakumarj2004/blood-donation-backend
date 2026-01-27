from rest_framework.views import APIView
from django.core.mail import send_mail
import threading
from rest_framework.response import Response
from rest_framework import status
from .db import get_db
from bson import ObjectId
import datetime
import math
import jwt
import os
from django.conf import settings

# Firebase Imports
import firebase_admin
from firebase_admin import credentials, messaging

# Initialize Firebase App (Lazy Singleton)
try:
    if not firebase_admin._apps:
        cred_path = os.getenv('FIREBASE_CREDENTIALS', 'serviceAccountKey.json')
        if os.path.exists(cred_path):
             cred = credentials.Certificate(cred_path)
             firebase_admin.initialize_app(cred)
        else:
             print("Warning: Firebase Credentials not found. Push Notifications will not send.")
except Exception as e:
    print(f"Firebase Init Error: {e}")

# Push Notification Helper
def send_push_multicast(tokens, title, body, data=None):
    if not tokens or not firebase_admin._apps:
        return
    try:
        message = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            data=data or {},
            tokens=tokens,
        )
        messaging.send_multicast(message)
    except Exception as e:
        print(f"Push Error: {e}")

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

def serialize_doc(doc):
    if not doc:
        return None
    doc['id'] = str(doc['_id'])
    del doc['_id']
    if 'password' in doc:
        del doc['password']
    return doc

def consume_batches_fifo(db, hospital_id, blood_group, units_needed):
    """
    Deduct units from batches using FIFO (First-In, First-Out) strategy.
    Returns actual units consumed.
    """
    consumed = 0
    try:
        # Fetch batches sorted by date (Oldest first)
        batches = db.batches.find({
            "hospitalId": hospital_id, 
            "bloodGroup": blood_group,
            "units": {"$gt": 0}
        }).sort("collectedDate", 1)
        
        for batch in batches:
            if consumed >= units_needed:
                break
                
            available = batch.get('units', 0)
            to_take = min(available, units_needed - consumed)
            
            # Atomic update for safety
            db.batches.update_one(
                {"_id": batch['_id']},
                {"$inc": {"units": -to_take}}
            )
            
            consumed += to_take
            
    except Exception as e:
        print(f"Batch Consumption Error: {e}")
        
    return consumed

class RegisterView(APIView):
    def post(self, request):
        db = get_db()
        data = request.data
        
        email = data.get('email', '').strip().lower()
        data['email'] = email # Ensure stored lowercase
        role = data.get('role')
        
        # Check existing
        existing = db.users.find_one({"email": email})
        if existing:
             return Response({"message": "Email already exists"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate Age (18+)
        # Validation
        required = ['name', 'email', 'password', 'role']
        for field in required:
            if not data.get(field):
                return Response({"error": f"{field} is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Prevent Admin Registration
        if data.get('role') == 'admin':
            return Response({"error": "Admin registration is restricted"}, status=status.HTTP_403_FORBIDDEN)
            
        # Age Validation (18+)
        if data.get('dob'):
             try:
                 dob = datetime.datetime.fromisoformat(data['dob'].replace('Z', ''))
                 age = (datetime.datetime.now() - dob).days // 365
                 if age < 18:
                     return Response({"error": "Must be 18+ to register"}, status=status.HTTP_400_BAD_REQUEST)
             except:
                 pass

        if db.users.find_one({"email": data['email']}):
            return Response({"error": "Email already exists"}, status=status.HTTP_409_CONFLICT)
            
        # Hash Password (Simple Logic for Demo - Production use Django Auth)
        from django.contrib.auth.hashers import make_password
        data['password'] = make_password(data['password'])
        
        data['createdAt'] = datetime.datetime.now().isoformat()
        
        # New: Initialize empty profile fields for Donor
        if data['role'] == 'donor':
            data.setdefault('isAvailable', True)
            data.setdefault('bloodGroup', None)
            data.setdefault('location', "")
            data.setdefault('fcmToken', "") # Store FCM Token
            
        result = db.users.insert_one(data)
        
        return Response({
            "success": True, 
            "message": "User registered successfully",
            "userId": str(result.inserted_id)
        }, status=status.HTTP_201_CREATED)

from rest_framework.permissions import AllowAny

class LoginView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        try:
            db = get_db()
            if db is None:
                print("CRITICAL: Database connection failed (db is None)")
                return Response({"error": "Database Service Unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

            email = request.data.get('email')
            password = request.data.get('password')
            fcm_token = request.data.get('fcmToken') # Capture Token on Login
            
            user = db.users.find_one({"email": email})
            
            if not user:
                return Response({"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)
                
            from django.contrib.auth.hashers import check_password
            # Support both hashed and legacy headers
            try:
                is_valid = check_password(password, user['password'])
            except:
                is_valid = (password == user['password'])
                
            if not is_valid:
                if password != user['password']: # Fallback
                    return Response({"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)

            # Update FCM Token & Last Login
            update_data = {"lastLogin": datetime.datetime.now().isoformat()}
            if fcm_token:
                update_data["fcmToken"] = fcm_token
                
            db.users.update_one({"_id": user['_id']}, {"$set": update_data})

            # JWT Token Generation
            payload = {
                "id": str(user['_id']),
                "role": user['role'],
                "exp": datetime.datetime.utcnow() + datetime.timedelta(days=1),
                "iat": datetime.datetime.utcnow()
            }
            token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')
            
            # Ensure token is string (PyJWT 2.0+ returns string, 1.7 returns bytes)
            if isinstance(token, bytes):
                token = token.decode('utf-8')
            
            response_data = serialize_doc(user)
            response_data['token'] = token
            response_data['success'] = True # Explicitly add success flag for Frontend compatibility
            
            return Response(response_data)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"LOGIN ERROR: {str(e)}")
            return Response({"error": f"Internal Server Error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
        
        # 1. Eligibility Check (Backend Logic Migration)
        donor_id = data.get('donorId')
        if donor_id:
            try:
                user = db.users.find_one({"_id": ObjectId(donor_id)})
                if user and user.get('lastDonationDate'):
                    last_date_str = user.get('lastDonationDate')
                    if last_date_str.endswith('Z'):
                        last_date_str = last_date_str[:-1]
                        
                    last_date = datetime.datetime.fromisoformat(last_date_str)
                    
                    # FORCE NAIVE
                    if last_date.tzinfo is not None:
                        last_date = last_date.replace(tzinfo=None)
                        
                    # Check against TARGET DATE (Booking Date) or Now if not set
                    booking_date_str = data.get('date')
                    target_date = datetime.datetime.now()
                    if booking_date_str:
                         try:
                             if booking_date_str.endswith('Z'): booking_date_str = booking_date_str[:-1]
                             target_date = datetime.datetime.fromisoformat(booking_date_str)
                             if target_date.tzinfo is not None: target_date = target_date.replace(tzinfo=None)
                         except:
                             pass
                    
                    days_diff = (target_date - last_date).days
                    
                    if days_diff < 60:
                        eligible_date = last_date + datetime.timedelta(days=60)
                        date_str = eligible_date.strftime("%d %b %Y")
                        return Response(
                            {"error": f"You are not eligible for this date. Earliest available: {date_str}."}, 
                            status=status.HTTP_400_BAD_REQUEST
                        )
            except Exception as e:
                print(f"Eligibility Check Error: {e}")
                pass
                
            # 2. Check for Existing Active Appointments (Double-Booking Prevention)
            existing_appt = db.appointments.find_one({
                "donorId": donor_id,
                "status": {"$in": ["Pending", "Scheduled"]}
            })
            
            if existing_appt:
                existing_date = existing_appt.get('date', '').split('T')[0]
                return Response(
                    {"error": f"You already have an active appointment scheduled for {existing_date}. Please complete or cancel it first."},
                    status=status.HTTP_409_CONFLICT
                )

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

    def put(self, request):
        db = get_db()
        data = request.data
        appt_id = data.get('id')
        new_status = data.get('status')
        # rejectionReason optional
        
        if not appt_id or not new_status:
            return Response({"error": "Missing id or status"}, status=400)

        appt = db.appointments.find_one({"_id": ObjectId(appt_id)})
        if not appt:
            return Response({"error": "Appointment not found"}, status=404)

        # INTEGRITY CHECK: Terminal State Locking
        current_status = appt.get('status')
        if current_status in ['Completed', 'Cancelled'] and new_status != current_status:
             return Response({"error": f"Cannot modify a {current_status} appointment."}, status=status.HTTP_400_BAD_REQUEST)
             
        # SECURITY: Donors can ONLY Cancel. They cannot mark Completed.
        if new_status == 'Completed':
             return Response({"error": "Only hospitals can mark appointments as Completed."}, status=status.HTTP_403_FORBIDDEN)

        if new_status == 'Cancelled':
             # Allow Cancellation
             db.appointments.update_one(
                 {"_id": ObjectId(appt_id)},
                 {"$set": {"status": "Cancelled", "cancelReason": data.get('reason', 'Donor Cancelled')}}
             )
             return Response({"success": True})
             
        return Response({"error": "Invalid Status Update"}, status=400)



class BloodInventoryView(APIView):
    def get(self, request):
        db = get_db()
        user_id = request.query_params.get('userId')
        if not user_id:
             return Response({"error": "userId required"}, status=400)
             
        inventory = db.inventory.find_one({"hospitalId": user_id}) or {}
        
        # Lazy Sync: Check for expired batches and update inventory
        try:
            now_iso = datetime.datetime.now().isoformat()
            
            # Find active batches that have expired
            expired_batches = list(db.batches.find({
                "hospitalId": user_id, 
                "units": {"$gt": 0},
                "expiryDate": {"$lt": now_iso}
            }))
            
            if expired_batches:
                for batch in expired_batches:
                    qty = batch.get('units', 0)
                    bg = batch.get('bloodGroup')
                    
                    if qty > 0 and bg:
                        # Decrement Inventory
                        db.inventory.update_one(
                            {"hospitalId": user_id},
                            {"$inc": {bg: -qty}}
                        )
                        # Mark Batch as Expired (Units 0)
                        db.batches.update_one(
                            {"_id": batch['_id']},
                            {"$set": {"units": 0, "status": "Expired"}}
                        )
                        print(f"Expired Batch {batch['_id']}: Removed {qty} units of {bg}")
                
                # Re-fetch inventory after updates
                inventory = db.inventory.find_one({"hospitalId": user_id}) or {}
        except Exception as e:
            print(f"Batch Expiry Sync Error: {e}")

        # Logic: Determine Status on Backend
        items = []
        for bg in ['A+', 'A-', 'B+', 'B-', 'O+', 'O-', 'AB+', 'AB-']:
            count = inventory.get(bg, 0)
            status_label = "Good"
            if count < 5:
                status_label = "Critical"
            elif count < 10:
                status_label = "Low"
                
            items.append({
                "type": bg,
                "total": max(0, count), # Ensure no negative
                "status": status_label
            })
            
        return Response(items)

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
    def get(self, request):
        db = get_db()
    def get(self, request):
        db = get_db()
        user_id = request.query_params.get('userId')
        filter_type = request.query_params.get('filter', 'all') # all, sent, received
        search_term = request.query_params.get('search', '')
        
        # Base Lists
        my_requests = []
        incoming_requests = []

        # 1. Fetch Outgoing (If needed)
        if filter_type in ['all', 'sent']:
            outgoing_query = {
                "$or": [
                    {"requesterId": user_id},
                    {"hospitalId": user_id, "type": {"$ne": "P2P"}} 
                ]
            }
            if search_term:
                # Basic search on status or bloodGroup first, complicated for dynamic names without join.
                # For simplicity/performance in Mongo without $lookup aggregation pipeline, we will fetch and filter in python if needed, 
                # OR implement basic regex on fields we have.
                outgoing_query["$or"] = outgoing_query["$or"] + [] # Append search queries if simple fields
                pass 
                
            my_requests = list(db.requests.find(outgoing_query).sort("date", -1))

        # 2. Fetch Incoming (If needed)
        if filter_type in ['all', 'received']:
             incoming_query = {
                "$or": [
                    {"hospitalId": user_id, "type": "P2P"}, 
                    {"type": "EMERGENCY_ALERT", "requesterId": {"$ne": user_id}} 
                ]
            }
            # Add basic filtering if possible
             incoming_requests = list(db.requests.find(incoming_query).sort("date", -1))
        
        # Combine
        combined = []
        
        # Process Outgoing
        for req in my_requests:
            req['isOutgoing'] = True
            if req.get('acceptedBy'):
                donor = db.users.find_one({"_id": ObjectId(req['acceptedBy'])})
                req['donorName'] = donor.get('name') if donor else "Unknown Donor"
            combined.append(req)
            
        # Process Incoming
        for req in incoming_requests:
            req['isOutgoing'] = False
            # Hide if accepted by others (Logic moved from earlier)
            if req.get('acceptedBy') and req.get('acceptedBy') != user_id:
                continue 
            requester_id = req.get('requesterId') or req.get('hospitalId')
            if requester_id:
                requester = db.users.find_one({"_id": ObjectId(requester_id)})
                req['hospitalName'] = requester.get('name') if requester else "Unknown Hospital"
                req['location'] = requester.get('location') if requester else "Unknown"
            combined.append(req)

        # 3. Apply Search Filter (Python Side for joins consistency, unless we use aggregates)
        # Moving logic to backend means backend does this.
        final_results = []
        if search_term:
            term = search_term.lower()
            for req in combined:
                # Search across computed fields
                party_name = (req.get('hospitalName') or req.get('requesterName') or '').lower()
                bg = (req.get('bloodGroup') or '').lower()
                stat = (req.get('status') or '').lower()
                
                if term in party_name or term in bg or term in stat:
                    final_results.append(serialize_doc(req))
        else:
            final_results = [serialize_doc(req) for req in combined]
            
        return Response(final_results)

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
        else:
             # Default to 24 hours if not specified
             data['expiresAt'] = (datetime.datetime.now() + datetime.timedelta(hours=24)).isoformat()
        
        # Ensure units is integer
        if 'units' in data:
            try:
                data['units'] = int(data['units'])
                if data['units'] <= 0:
                    return Response({"error": "Units must be greater than 0"}, status=status.HTTP_400_BAD_REQUEST)
            except ValueError:
                 return Response({"error": "Units must be a number"}, status=status.HTTP_400_BAD_REQUEST)
        else:
             return Response({"error": "Units required"}, status=status.HTTP_400_BAD_REQUEST)

        if 'bloodGroup' not in data:
             return Response({"error": "Blood Group required"}, status=status.HTTP_400_BAD_REQUEST)

        # START: Backend Logic for P2P Integrity
        if data.get('type') == 'P2P':
            target_id = data.get('hospitalId') # In P2P, this is the Target Donor
            requester_id = data.get('requesterId')
            
            if not target_id:
                return Response({"error": "Target Donor (hospitalId) request for P2P"}, status=status.HTTP_400_BAD_REQUEST)
            
            if target_id == requester_id:
                 return Response({"error": "Cannot request blood from yourself"}, status=status.HTTP_400_BAD_REQUEST)
                 
            # Verify Target is a Hospital
            target_hospital = db.users.find_one({"_id": ObjectId(target_id), "role": "hospital"})
            if not target_hospital:
                 return Response({"error": "Target recipient is not a valid hospital"}, status=status.HTTP_400_BAD_REQUEST)
                 
        # END: Backend Logic

        if data.get('type') == 'EMERGENCY_ALERT':
             # Find all eligible donors with matching blood group
             query = {
                 "role": "donor",
                 "bloodGroup": data.get('bloodGroup')
             }
             # Filter by Cities if provided
             if data.get('cities'):
                 query['location'] = {"$in": data.get('cities')}
                 
             donors = list(db.users.find(query))
        
        # 3. Create Request (ONCE)
        res = db.requests.insert_one(data)
        
        if data.get('type') == 'P2P' and data.get('hospitalId'):
            # Notify Target Hospital
            db.notifications.insert_one({
                "recipientId": data.get('hospitalId'),
                "type": "P2P_REQUEST",
                "title": "New Blood Request",
                "message": f"{data.get('requesterName', 'A Hospital')} requested {data.get('units')} units of {data.get('bloodGroup')}.",
                "relatedRequestId": str(res.inserted_id),
                "timestamp": datetime.datetime.now().isoformat(),
                "status": "UNREAD"
            })
            
        elif data.get('type') == 'EMERGENCY_ALERT':
             # Send Push to Donors
             tokens = [d['fcmToken'] for d in donors if d.get('fcmToken')]
             if tokens:
                 send_push_multicast(
                     tokens, 
                     "Emergency Blood Needed!", 
                     f"Urgent: {data.get('bloodGroup')} blood needed at {data.get('hospitalName', 'a nearby hospital')}.",
                     {
                         "type": "EMERGENCY_ALERT", 
                         "requestId": str(res.inserted_id) # Payload needed for App
                     }
                 )
                 
             # Create notifications in DB for history
             notifs = []
             for d in donors:
                 notifs.append({
                     "recipientId": str(d['_id']),
                     "type": "EMERGENCY_ALERT",
                     "title": "Emergency Blood Needed!",
                     "message": f"Urgent: {data.get('bloodGroup')} blood needed.",
                     "relatedRequestId": str(res.inserted_id),
                     "timestamp": datetime.datetime.now().isoformat(),
                     "status": "UNREAD"
                 })
             if notifs:
                 db.notifications.insert_many(notifs)

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
            
        # Fetch Request First
        req = db.requests.find_one({"_id": ObjectId(req_id)})
        if not req:
             return Response({"error": "Request not found"}, status=404)
             
        # GUARD: Immutability check
        if req.get('status') == 'Completed':
             return Response({"error": "Cannot modify a completed request"}, status=status.HTTP_409_CONFLICT)

        # Update Request
        dataset = {"status": new_status}
        
        # Save optional response message
        if data.get('responseMessage'):
            dataset['responseMessage'] = data.get('responseMessage')
        
        if new_status == 'Accepted':
            # 1. EXPIRY CHECK
            if req.get('expiresAt'):
                try:
                    exp_date = datetime.datetime.fromisoformat(req['expiresAt'].replace('Z', ''))
                    if exp_date < datetime.datetime.now():
                         # Auto-expire it instead of just erroring?
                         db.requests.update_one({"_id": ObjectId(req_id)}, {"$set": {"status": "Expired"}})
                         return Response({"error": "This request has expired."}, status=400)
                except:
                    pass

            if not responder_id:
                return Response({"error": "hospitalId required for acceptance"}, status=400)
            
            # CONCURRENCY CHECK: Prevent Double Acceptance
            if req.get('acceptedBy') and req.get('acceptedBy') != responder_id:
                 return Response({"error": "Request already accepted by another hospital"}, status=status.HTTP_409_CONFLICT)
                 
            dataset['acceptedBy'] = responder_id
            dataset['acceptedAt'] = datetime.datetime.now().isoformat()
            
            # NOTIFY REQUESTER (Hospital)
            requester_id = req.get('requesterId')
            if requester_id:
                requester = db.users.find_one({"_id": ObjectId(requester_id)})
                if requester:
                    responder = db.users.find_one({"_id": ObjectId(responder_id)})
                    resp_name = responder.get('name') if responder else "A Hospital"
                    
                    title = "Request Accepted"
                    body = f"{resp_name} has accepted your request for {req.get('units')} units."
                    
                    # DB Notification
                    db.notifications.insert_one({
                        "recipientId": str(requester['_id']),
                        "title": title,
                        "message": body,
                        "type": "REQUEST_ACCEPTED",
                        "relatedRequestId": req_id,
                        "status": "UNREAD",
                        "timestamp": datetime.datetime.now().isoformat()
                    })
                    
                    # FCM Push
                    if requester.get('fcmToken'):
                        send_push_multicast([requester['fcmToken']], title, body, {"type": "REQUEST_ACCEPTED", "requestId": req_id})

            # CRITICAL: If StockTransfer or P2P, Decrement Responder's Inventory immediately on Acceptance
            # This prevents double-booking (promising same stock to multiple people)
            if req.get('type') in ['P2P', 'StockTransfer']:
                bg = req.get('bloodGroup')
                units = int(req.get('units', 1))
                
                # Check Responder Stock
                responder_inv = db.inventory.find_one({"hospitalId": responder_id})
                current_stock = int(responder_inv.get(bg, 0)) if responder_inv else 0
                
                if current_stock < units:
                     return Response({"error": f"Insufficient {bg} stock ({current_stock} available)."}, status=400)
                
                # Decrement Inventory (Aggregate)
                db.inventory.update_one(
                    {"hospitalId": responder_id},
                    {"$inc": {bg: -units}}
                )
                
                # CRITICAL: Also Consume Batches (Physical Stock) to match Inventory
                # This prevents "Double Spending" of the same blood units
                consume_batches_fifo(db, responder_id, bg, units)

        if new_status == 'Cancelled' and current_status == 'Accepted':
             # REFUND LOGIC: If it was a StockTransfer/P2P that was accepted, the responder lost stock. Refund it.
             if req.get('type') in ['P2P', 'StockTransfer'] and req.get('acceptedBy'):
                 responder_id = req.get('acceptedBy')
                 bg = req.get('bloodGroup')
                 units = int(req.get('units', 1))
                 
                 if responder_id and bg:
                     db.inventory.update_one(
                         {"hospitalId": responder_id},
                         {"$inc": {bg: units}}
                     )
                     print(f"Refunded {units} units of {bg} to {responder_id}")

             # CLEANUP: Remove pending notifications so donors don't see dead alerts
             db.notifications.delete_many({"relatedRequestId": req_id})

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

                # Fetch Source/Donor Name for consistent records
                source_name = "External Source"
                if donor_id:
                     donor_obj = db.users.find_one({"_id": ObjectId(donor_id)})
                     if donor_obj:
                         source_name = donor_obj.get('name', 'Unknown')

                # 1. Increment Stock for Requester (They received it)
                if requester_id and bg:
                    db.inventory.update_one(
                        {"hospitalId": requester_id},
                        {"$inc": {bg: units}}, 
                        upsert=True
                    )
                    # AUTO-CREATE BATCH for Requester
                    try:
                        batch_data = {
                            "hospitalId": requester_id,
                            "bloodGroup": bg,
                            "componentType": "Whole Blood",
                            "units": units,
                            "collectedDate": datetime.datetime.now().isoformat(),
                            "expiryDate": (datetime.datetime.now() + datetime.timedelta(days=35)).isoformat(),
                            "sourceType": "Transfer" if req_type == 'P2P' else "Donation",
                            "sourceName": source_name,
                            "location": "Incoming Setup", 
                            "createdAt": datetime.datetime.now().isoformat(),
                            "status": "Active"
                        }
                        db.batches.insert_one(batch_data)
                    except Exception as e:
                        print(f"Failed to auto-create batch: {e}")
                    
                # 2. Decrement Logic moved to 'Accepted' block for StockTransfer.
                # For standard donors, no inventory to decrement.
                pass
                
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
        requester_id = request.query_params.get('userId') # To exclude self
        try:
             min_units = int(request.query_params.get('units', 1))
        except:
             min_units = 1
        
        if not blood_group:
             return Response({"error": "bloodGroup required"}, status=400)

        # 1. Find inventories with stock >= Requested Units (Logic Verification)
        # Frontend previously filtered this. Now Backend does it.
        inventory_query = {blood_group: {"$gte": min_units}}
        
        # Optimization: We could also filter by hospitalId != requester_id here if we query users...
        # But inventory links to hospitalId.
        if requester_id:
             inventory_query["hospitalId"] = {"$ne": requester_id}

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
        user_id = request.query_params.get('userId')
        
        # 1. Get User to check Blood Group (Strict Match) & Ignored List
        user = None
        ignored_ids = set()
        if user_id:
            try:
                user = db.users.find_one({"_id": ObjectId(user_id)})
                if user and user.get('ignoredRequests'):
                     ignored_ids = set(user['ignoredRequests'])
            except:
                pass
            
        params = {"status": "Active"}
        
        requests = list(db.requests.find(params).sort("timestamp", -1))
        
        valid_requests = []
        now = datetime.datetime.now(datetime.timezone.utc)
        
        for r in requests:
            # 0. Check Ignored
            if str(r['_id']) in ignored_ids:
                continue
            # Check Expiry if exists
            if r.get('expiresAt'):
                 try:
                     # Handle formats (ISO with/without Z)
                     exp_str = str(r['expiresAt']).replace('Z', '')
                     exp_date = datetime.datetime.fromisoformat(exp_str)
                     if exp_date.tzinfo is None: exp_date = exp_date.replace(tzinfo=datetime.timezone.utc)
                     
                     if exp_date < now:
                         continue # Expired
                 except:
                     pass # If bad date, ignore expiry check or safe fail
            
            # Logic:
            # 1. If I accepted it, always show it (even if expired/different group?) - Active requests shouldn't be accepted by me unless incomplete?
            # Actually, if I accepted it, status is 'Accepted', so params={"status": "Active"} won't find it.
            # So this view ONLY shows 'Active' new requests.
            # 'Accepted' requests are in 'MyRequests' view usually.
            
            # 2. Strict Blood Group Match
            if user and user.get('bloodGroup'):
                if r.get('bloodGroup') != user['bloodGroup']:
                    continue

            # Populate Hospital Name
            requester_id = r.get('requesterId') or r.get('hospitalId')
            if requester_id:
                 try:
                    hospital = db.users.find_one({"_id": ObjectId(requester_id)})
                    r['hospitalName'] = hospital.get('name') if hospital else "Unknown Hospital"
                    r['location'] = hospital.get('location') if hospital else "Unknown Location"
                 except:
                    r['hospitalName'] = "Unknown Hospital"
            
            valid_requests.append(serialize_doc(r))
            
        return Response(valid_requests)

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
            
        # Fetch Existing Appointment
        appt = db.appointments.find_one({"_id": ObjectId(appt_id)})
        if not appt:
             return Response({"error": "Appointment not found"}, status=404)
             
        # GUARD: Immutability check
        if appt.get('status') == 'Completed':
             return Response({"error": "Cannot modify a completed appointment"}, status=status.HTTP_409_CONFLICT)

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
                    # 1. Update Inventory Count
                    db.inventory.update_one(
                        {"hospitalId": hospital_id},
                        {"$inc": {bg: units}},
                        upsert=True
                    )
                    
                    # 2. AUTO-CREATE BATCH (Physical Stock)
                    try:
                        batch_data = {
                            "hospitalId": hospital_id,
                            "bloodGroup": bg,
                            "componentType": "Whole Blood", # Default from donation
                            "units": units,
                            "collectedDate": datetime.datetime.now().isoformat(),
                            "expiryDate": (datetime.datetime.now() + datetime.timedelta(days=35)).isoformat(), # Default 35 days
                            "sourceType": "Donation",
                            "sourceName": donor.get('name') if donor else "Walk-in Donor",
                            "location": "In-House",
                            "createdAt": datetime.datetime.now().isoformat(),
                            "status": "Active"
                        }
                        db.batches.insert_one(batch_data)
                    except Exception as e:
                        print(f"Failed to auto-create batch for appointment: {e}")

                # Update Donor's Last Donation Date (Cached on User Profile)
                if donor_id:
                     db.users.update_one(
                        {"_id": ObjectId(donor_id)},
                        {"$set": {"lastDonationDate": datetime.datetime.now().isoformat()}}
                     )
        
        return Response({"success": True})
                    


# Admin-related views removed - admin role no longer exists in the application

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
        """Create notifications (System sending to users)"""
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
            original_req = db.requests.find_one({"_id": ObjectId(req_id)})
            
            if original_req:
                # SAFETY CHECK: Only accept valid, active requests
                if original_req.get('status') != 'Active':
                     return Response({"error": "Request is no longer active"}, status=status.HTTP_409_CONFLICT)
                
                # Double Check AcceptedBy
                if original_req.get('acceptedBy'):
                     return Response({"error": "Request already accepted"}, status=status.HTTP_409_CONFLICT)

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
                
                # NOTIFY REQUESTER (Hospital)
                requester_id = original_req.get('requesterId') or original_req.get('hospitalId')
                if requester_id:
                    requester = db.users.find_one({"_id": ObjectId(requester_id)})
                    if requester:
                        # Get Donor Name
                        donor = db.users.find_one({"_id": ObjectId(recipient_id)})
                        donor_name = donor.get('name') if donor else "A Donor"
                        
                        title = "Donor Responded!"
                        body = f"{donor_name} is on their way for your emergency request!"
                        
                        # DB Notification
                        db.notifications.insert_one({
                            "recipientId": str(requester['_id']),
                            "title": title,
                            "message": body,
                            "type": "DONOR_RESPONSE",
                            "relatedRequestId": req_id,
                            "status": "UNREAD",
                            "timestamp": datetime.datetime.now().isoformat()
                        })
                        
                        # FCM Push
                        if requester.get('fcmToken'):
                             send_push_multicast([requester['fcmToken']], title, body, {"type": "DONOR_RESPONSE", "requestId": req_id})
            
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
            # 1. Fetch Request to check current status
            req = db.requests.find_one({"_id": ObjectId(alert_id)})
            if not req:
                 return Response({"error": "Request not found"}, status=404)
            
            # 2. Concurrency Check
            if req.get('acceptedBy') and req.get('acceptedBy') != donor_id:
                 return Response({"error": "This request has already been accepted by another donor."}, status=status.HTTP_409_CONFLICT)

            # 3. Update request status and assign donor
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
            
            # 4. AUTO-BOOK APPOINTMENT
            # If a donor accepts an emergency, book them in immediately as 'Scheduled'.
            try:
                # Fetch Request Details for Hospital Info
                hospital_id = req.get('requesterId') or req.get('hospitalId') # Who needs it
                hospital_name = req.get('hospitalName') or "Emergency Center"
                
                appt_data = {
                    "donorId": donor_id,
                    "hospitalId": hospital_id,
                    "center": hospital_name,
                    "date": datetime.datetime.now().isoformat(), # Scheduled for NOW
                    "bloodGroup": req.get('bloodGroup'),
                    "type": "Emergency Response",
                    "status": "Scheduled",
                    "units": int(req.get('units', 1))
                }
                
                # Check duplication first (optional but safer)
                existing = db.appointments.find_one({
                    "donorId": donor_id, 
                    "status": {"$in": ["Scheduled", "Pending"]},
                    "type": "Emergency Response",
                    "date": {"$gte": (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()}
                })
                
                if not existing:
                    db.appointments.insert_one(appt_data)
                    print(f"Auto-Booked Emergency Appointment for Donor {donor_id}")
            except Exception as e:
                print(f"Auto-Book Error: {e}")
        
        return Response({"success": True})





        

class ActiveLocationsView(APIView):
    def get(self, request):
        db = get_db()
        # Get unique locations from donors
        locations = db.users.find({"role": "donor"}).distinct("location")
        # Filter out None/Empty
        valid_locations = [loc for loc in locations if loc]
        return Response(valid_locations)

class LocationCountView(APIView):
    def get(self, request):
        db = get_db()
        blood_group = request.query_params.get('bloodGroup')
        cities = request.query_params.getlist('city') # Support multiple cities
        
        query = {"role": "donor"}
        if blood_group:
            query["bloodGroup"] = blood_group
        
        if cities:
            # If multiple cities selected
            query["location"] = {"$in": cities}
            
        # Count only Eligible Donors
        all_donors = db.users.find(query)
        eligible_count = 0
        now_naive = datetime.datetime.now() # Local Naive for consistency

        for doc in all_donors:
            if 'lastDonationDate' not in doc:
                eligible_count += 1
                continue
                
            last_date_str = doc['lastDonationDate']
            try:
                if last_date_str.endswith('Z'): last_date_str = last_date_str[:-1]
                last_date = datetime.datetime.fromisoformat(last_date_str)
                # Strip TZ to compare naive-to-naive
                if last_date.tzinfo is not None: last_date = last_date.replace(tzinfo=None)
                
                if (now_naive - last_date).days >= 60:
                     eligible_count += 1
            except:
                # If date parse fails, assume eligible (fail open for counting)
                eligible_count += 1
                
        return Response({"count": eligible_count})

class HospitalDonorSearchView(APIView):
    def get(self, request):
        db = get_db()
        blood_group = request.query_params.get('bloodGroup')
        cities = request.query_params.getlist('city')
        
        query = {"role": "donor"}
        
        # 1. Strict Server-Side Filtering
        if blood_group:
            query["bloodGroup"] = blood_group
        if cities:
            query["location"] = {"$in": cities}
            
        # 2. Eligibility Check (Optional but good for P2P)
        # We return all, but flag them. Or filter?
        # User wants "eligible donors". Let's filter by 60 days rule here too?
        # Usually P2P allows messaging anyone, but let's stick to "Eligible" for "Emergency Call"
        
        cursor = db.users.find(query)
        donors = []
        now = datetime.datetime.now(datetime.timezone.utc)
        
        for doc in cursor:
            # Calculate Eligibility
            is_eligible = True
            last_date_str = doc.get('lastDonationDate')
            if last_date_str:
                try:
                    # Robust parsing for ISO format
                    if last_date_str.endswith('Z'): last_date_str = last_date_str[:-1]
                    last_date = datetime.datetime.fromisoformat(last_date_str)
                    
                    # Ensure last_date is Naive for simple comparison with datetime.now()
                    if last_date.tzinfo is not None:
                        last_date = last_date.replace(tzinfo=None)
                    
                    now_naive = datetime.datetime.now() # Local Naive
                    
                    if (now_naive - last_date).days < 60:
                        is_eligible = False
                except Exception as e:
                    # print(f"Date Parse Error: {e}")
                    pass
            
            # Only return eligible donors for Emergency Call
            if is_eligible:
                # Calculate Distance (Mock or Real)
                # For now just return data, frontend calculates sort? 
                # User asked to move logic. Distance calc is complex without user lat/lng passed.
                # If lat/lng passed, we calc.
                dist_text = "Unknown"
                
                # Check for Active Appointment (Booked?)
                is_booked = db.appointments.find_one({
                    "donorId": str(doc['_id']),
                    "status": {"$in": ["Pending", "Scheduled"]}
                })
                
                if not is_booked:
                    donors.append(serialize_doc(doc))
                
        return Response(donors)



# AdminAnalyticsView Removed (Cleanup)

class ProfileUpdateView(APIView):
    def process_update(self, request, partial=False):
        db = get_db()
        user_id = request.data.get('userId')
        data = request.data.get('data', {})
        
        # If payload is flat (not nested in data object), support that too for PATCH convenience
        if not data and not user_id:
             # Try simple flattening? 
             # Let's stick to existing protocol: { userId: "...", data: { ... } }
             pass

        if not user_id:
             return Response({"error": "userId required"}, status=400)
             
        update_fields = {}
        
        # Handle Password Update with Hashing
        if 'password' in data and data['password']:
            pwd = data['password']
            if len(pwd) < 6:
                 return Response({"error": "Password must be at least 6 characters"}, status=400)
                 
            from django.contrib.auth.hashers import make_password
            update_fields['password'] = make_password(pwd)
            
        # Handle other fields (Gender, Name, Bio, etc.)
        allowed_fields = [
            'name', 'phone', 'location', 'gender', 'bloodGroup', 
            'bio', 'occupation', 'dob', 'isAvailable'
        ]
        
        for field in allowed_fields:
            if field in data:
                # Unique Check for Phone
                if field == 'phone' and data['phone']:
                     existing = db.users.find_one({"phone": data['phone'], "_id": {"$ne": ObjectId(user_id)}})
                     if existing:
                          return Response({"error": "Phone number already in use"}, status=400)
                
                # Verify Date Format (Basic)
                if field == 'dob' and data['dob']:
                    # Optional: validate or sanitize
                    pass

                update_fields[field] = data[field]
                
        if update_fields:
            db.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": update_fields}
            )
            return Response({"success": True})
        
        if not partial and not update_fields:
             return Response({"error": "No fields to update"}, status=400)
             
        return Response({"success": True, "message": "No changes detected"})

    def post(self, request):
        """Update User Profile (Legacy/Full)"""
        return self.process_update(request, partial=True)

    def patch(self, request):
        """Partial Update User Profile"""
        return self.process_update(request, partial=True)
            
    def delete(self, request):
        """Allow user to self-delete account"""
        db = get_db()
        user_id = request.query_params.get('userId')
        if not user_id:
             return Response({"error": "userId required"}, status=400)
             
        # Optional: Archive instead of delete? For now, hard delete as per privacy.
        result = db.users.delete_one({"_id": ObjectId(user_id)})
        
        # CASCADE CLEANUP:
        if result.deleted_count > 0:
            # 1. Cancel Active Requests by this user
            db.requests.update_many(
                {"requesterId": user_id, "status": "Active"},
                {"$set": {"status": "Cancelled", "cancelReason": "User Deleted Account"}}
            )
            # 2. Cancel Pending Appointments
            db.appointments.update_many(
                {"donorId": user_id, "status": "Pending"},
                {"$set": {"status": "Cancelled"}}
            )
            # 3. Delete Notifications
            db.notifications.delete_many({"recipientId": user_id})
            
            # 4. Hospital Specific Cleanup (If Hospital)
            # Remove Inventory & Batches
            db.inventory.delete_many({"hospitalId": user_id})
            db.batches.delete_many({"hospitalId": user_id})
            
            # Cancel Appointments where they are the Host
            db.appointments.update_many(
                {"hospitalId": user_id, "status": {"$in": ["Pending", "Scheduled"]}},
                {"$set": {"status": "Cancelled", "rejectionReason": "Hospital Closed"}}
            )
            
            # Cancel Requests where they are the Host (hospitalId)
            db.requests.update_many(
                 {"hospitalId": user_id, "status": "Active"},
                 {"$set": {"status": "Cancelled", "cancelReason": "Hospital Closed"}}
            )

        return Response({"success": True, "deleted": result.deleted_count})

class BatchView(APIView):
    def get(self, request):
        db = get_db()
        hospital_id = request.query_params.get('hospitalId')
        if not hospital_id:
            return Response({"error": "hospitalId required"}, status=400)
            
        batches = list(db.batches.find({"hospitalId": hospital_id, "units": {"$gt": 0}}))
        return Response([serialize_doc(b) for b in batches])

    def post(self, request):
        db = get_db()
        data = request.data
        hospital_id = data.get('hospitalId')
        bg = data.get('bloodGroup')
        units = int(data.get('units', 0))
        
        if not hospital_id or not bg or units <= 0:
            return Response({"error": "Invalid Data"}, status=400)
            
        # 1. Create Batch
        data['createdAt'] = datetime.datetime.now().isoformat()
        data['units'] = units # CRITICAL: Ensure stored as INT for querying
        
        # Ensure Expiry
        if 'expiryDate' not in data:
             data['expiryDate'] = (datetime.datetime.now() + datetime.timedelta(days=35)).isoformat()
             
        res = db.batches.insert_one(data)
        
        # 2. Sync with Inventory (Aggregated)
        db.inventory.update_one(
            {"hospitalId": hospital_id},
            {"$inc": {bg: units}},
            upsert=True
        )
        
        return Response({"success": True, "id": str(res.inserted_id)})

class BatchActionView(APIView):
    def post(self, request):
        db = get_db()
        batch_id = request.data.get('batchId')
        action = request.data.get('action')
        qty = int(request.data.get('quantity', 1))
        
        hospital_id = request.data.get('hospitalId')
        
        if not batch_id or not hospital_id or action not in ['use_unit', 'discard_unit']:
             return Response({"error": "Invalid Action or Missing IDs"}, status=400)
             
        # ATOMIC UPDATE: Decrement only if units >= qty AND Owner matches
        # Using find_one_and_update ensures no race condition
        updated_batch = db.batches.find_one_and_update(
            {"_id": ObjectId(batch_id), "hospitalId": hospital_id, "units": {"$gte": qty}},
            {"$inc": {"units": -qty}},
            return_document=True
        )

        if not updated_batch:
             return Response({"error": "Not enough units or batch not found"}, status=400)
             
        new_units = updated_batch['units']

        # 3. Decrement Inventory (Sync)
        # Inventory is an aggregate, so we just decrement. Even if it goes negative (shouldn't),
        # it reflects the batch operation.
        hospital_id = updated_batch.get('hospitalId')
        bg = updated_batch.get('bloodGroup')
        
        if hospital_id and bg:
             db.inventory.update_one(
                {"hospitalId": hospital_id},
                {"$inc": {bg: -qty}}
             )
        
        # Check Depletion
        if new_units == 0:
            db.batches.update_one(
                {"_id": ObjectId(batch_id)},
                {"$set": {"status": "Depleted"}}
            )
             
        return Response({"success": True, "remaining": new_units})
        


class HospitalReportsView(APIView):
    def get(self, request):
        db = get_db()
        hospital_id = request.query_params.get('hospitalId')
        
        if not hospital_id:
            return Response({"error": "hospitalId required"}, status=400)
            
        # 1. Total Units Collected (From Batches)
        pipeline_collected = [
            {"$match": {"hospitalId": hospital_id}},
            {"$group": {"_id": None, "total": {"$sum": "$units"}}}
        ]
        res_collected = list(db.batches.aggregate(pipeline_collected))
        total_collected = res_collected[0]['total'] if res_collected else 0
        
        # 2. Total Units Dispatched (From Completed Outgoing Requests)
        # Note: This is a simplification. Real dispatch might track specific batch usage.
        # But we can look at "Requests Fulfilled" by this hospital.
        pipeline_dispatched = [
            {"$match": {
                "hospitalId": hospital_id, # As Responder/Source
                "type": {"$in": ["P2P", "StockTransfer", "EMERGENCY_ALERT"]}, # Outgoing types
                "status": "Completed"
            }},
            {"$group": {"_id": None, "total": {"$sum": "$units"}}}
        ]
        # Note: In P2P, if 'hospitalId' is the TARGET (Donor), then they dispatched it.
        # But wait, in P2P creation: 'hospitalId' is target donor. 'requesterId' is source.
        # So if I am 'hospitalId', I received the request and fulfilled it.
        # If I am 'requesterId', I asked for it.
        
        # Fixing Logic:
        # Dispatched = requests where I was the 'acceptedBy' (Donor) OR 'hospitalId' (Target in P2P).
        
        # Let's count 'Batches Used' instead? 
        # Actually simplest is to count requests where I am the provider.
        
        # A simpler proxy for "Dispatched" is counting how many units are NOT present compared to batches created?
        # No, "Dispatched" usually means "Sent out".
        
        # Let's query requests where acceptedBy == hospitalId and status == Completed
        pipeline_dispatched = [
            {"$match": {
                "acceptedBy": hospital_id, 
                "status": "Completed"
            }},
            {"$group": {"_id": None, "total": {"$sum": "$units"}}}
        ]
        res_dispatched = list(db.requests.aggregate(pipeline_dispatched))
        total_dispatched = res_dispatched[0]['total'] if res_dispatched else 0

        # 3. Batches Expiring Soon (7 Days)
        now = datetime.datetime.now()
        next_week = (now + datetime.timedelta(days=7)).isoformat()
        now_iso = now.isoformat()
        
        expiring_soon = db.batches.count_documents({
            "hospitalId": hospital_id,
            "units": {"$gt": 0},
            "expiryDate": {"$gt": now_iso, "$lt": next_week}
        })

        # 4. Emergency Requests Fulfilled
        emergency_count = db.requests.count_documents({
            "acceptedBy": hospital_id,
            "type": "EMERGENCY_ALERT",
            "status": {"$in": ["Accepted", "Completed"]}
        })

        report_data = {
            "total_units_collected": total_collected,
            "total_units_dispatched": total_dispatched,
            "batches_expiring_soon": expiring_soon,
            "emergency_requests_fulfilled": emergency_count
        }
        return Response(report_data)

class BloodDispatchView(APIView):
    def post(self, request):
        db = get_db()
        data = request.data
        
        # Support requestId lookup
        req_id = data.get('reqId') or data.get('requestId')
        
        target_id = data.get('targetId')
        units = data.get('units')
        bg = data.get('bloodGroup')
        sender_id = data.get('hospitalId')
        
        # If Request ID provided, fetch details from it
        if req_id:
            req = db.requests.find_one({"_id": ObjectId(req_id)})
            if not req:
                 return Response({"error": "Request not found"}, status=404)
            
            # Auto-fill missing data from Request
            if not target_id: target_id = req.get('requesterId')
            if not units: units = int(req.get('units', 0))
            if not bg: bg = req.get('bloodGroup')
            
            # Update Request Status
            db.requests.update_one(
                {"_id": ObjectId(req_id)},
                {"$set": {
                    "status": "Dispatched",
                    "dispatchDetails": {
                        "mode": data.get('transportMode'),
                        "tracker": data.get('trackingId'),
                        "date": data.get('dispatchDate')
                    }
                }}
            )

        # Validation
        if not sender_id or not target_id or not units or not bg:
             return Response({"error": "Missing dispatch details (targetId, units, bloodGroup required if no reqId)"}, status=400)
             
        # 1. Decrement Sender Inventory
        db.inventory.update_one(
            {"hospitalId": sender_id},
            {"$inc": {bg: -int(units)}}
        )
        # Sync Batches (consume FIFO)
        consume_batches_fifo(db, sender_id, bg, int(units))
        
        # 2. Notify Receiver
        sender_doc = db.users.find_one({"_id": ObjectId(sender_id)})
        sender_name = sender_doc.get('name', 'Partner Hospital') if sender_doc else 'Partner Hospital'
        
        db.notifications.insert_one({
             "recipientId": target_id,
             "type": "BLOOD_DISPATCHED",
             "title": "Blood Dispatched",
             "message": f"{units} units of {bg} are on the way from {sender_name}.",
             "reqId": req_id,
             "status": "UNREAD",
             "timestamp": datetime.datetime.now().isoformat()
        })
        
        return Response({"success": True, "message": "Blood dispatched successfully"})

class BloodReceiveView(APIView):
    def post(self, request):
        db = get_db()
        data = request.data
        
        # Logic: Receiver adds to inventory
        if not data.get('hospitalId') or not data.get('units'):
             return Response({"error": "Missing acceptance details"}, status=400)
             
        receiver_id = data.get('hospitalId')
        units = int(data.get('units'))
        bg = data.get('bloodGroup')
        
        # 1. Increment Receiver Inventory
        db.inventory.update_one(
            {"hospitalId": receiver_id},
            {"$inc": {bg: units}},
            upsert=True
        )
        
        return Response({"success": True, "message": "Blood received into inventory"})

class ForgotPasswordView(APIView):
    def post(self, request):
        email = request.data.get('email')
        if not email:
            return Response({"error": "Email required"}, status=400)
            
        # Async Email Sending
        def send_async_email(user_email, user_name):
            try:
                 reset_link = "https://blood-donation-frontend-dyrt.onrender.com/reset-password" # Using Render URL
                 send_mail(
                    subject="Blood Donation App - Password Reset",
                    message=f"Hello {user_name},\n\nWe received a request to reset your password.\n\nSince this is a demo environment, please contact the administrator or use the app's secure reset flow if available.\n\nIf you did not request this, please ignore this email.",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user_email],
                    fail_silently=False,
                )
                 print(f"Reset email sent to {user_email}")
            except Exception as e:
                print(f"Email Sending Error: {e}")

        db = get_db()
        # Case Insensitive Search
        user = db.users.find_one({"email": {"$regex": f"^{email}$", "$options": "i"}})
        
        if not user:
            # Explicitly tell user if email doesn't exist (Requested by User)
            return Response({"error": "No account found with this email address."}, status=404)

        # Synchronous Debugging Mode: Send directly to catch error
        try:
             reset_link = "https://blood-donation-frontend-dyrt.onrender.com/reset-password" 
             
             send_mail(
                subject="Blood Donation App - Password Reset",
                message=f"Hello {user.get('name', 'User')},\n\nWe received a request to reset your password.\n\nSince this is a demo environment, please contact the administrator or use the app's secure reset flow if available.\n\nIf you did not request this, please ignore this email.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )
             return Response({"success": True, "message": "Password reset link sent to your email."})
        except Exception as e:
            # RETURN THE ACTUAL ERROR TO THE USER FOR DEBUGGING
            return Response({"error": f"Email Configuration Error: {str(e)}"}, status=500)

class DonorIgnoreRequestView(APIView):
    def post(self, request):
        db = get_db()
        user_id = request.data.get('userId')
        req_id = request.data.get('requestId')
        
        if not user_id or not req_id:
             return Response({"error": "Missing params"}, status=400)
             
        # Add to ignored list in User Profile
        db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$addToSet": {"ignoredRequests": req_id}}
        )
        
        return Response({"success": True})

class DonorP2PView(APIView):
    def get(self, request):
        """Get My Requests (requests created by this donor)"""
        db = get_db()
        user_id = request.query_params.get('userId')
        if not user_id:
             return Response({"error": "userId required"}, status=400)
             
        # Find requests where requesterId is this user
        requests = list(db.requests.find({"requesterId": user_id}).sort("timestamp", -1))
        return Response([serialize_doc(r) for r in requests])

    def post(self, request):
        """Create P2P Request"""
        db = get_db()
        data = request.data
        
        # Check if this is a 'complete' action or 'create'
        if 'requestId' in data and request.path.endswith('complete/'):
             return self.complete_request(request)

        # Create Logic
        data['createdAt'] = datetime.datetime.now().isoformat()
        data['status'] = 'Active' # Fix: Set to Active so it appears in feeds
        data['type'] = 'P2P_REQUEST'
        
        # 1. Calculate Expiration
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
                params = now.replace(hour=23, minute=59, second=59)
                delta = params - now
            
            data['expiresAt'] = (now + delta).isoformat()

        res = db.requests.insert_one(data)
        
        # 2. Notify Potential Donors
        # Find donors in target cities with matching blood group
        try:
            query = {
                "role": "donor",
                "bloodGroup": data.get('bloodGroup'),
                "_id": {"$ne": ObjectId(data.get('requesterId'))} # Don't notify self
            }
            
            cities = data.get('cities') # Fix: Extract list
            if not cities and data.get('city'): # Fallback to string split
                cities = [c.strip() for c in data.get('city').split(',')]

            if cities:
                query['location'] = {"$in": cities}
                
            potential_donors = list(db.users.find(query))
            donors = []
            
            # Filter Ineligible (60-day Rule) - Strict for Notification Spam Prevention
            now_naive = datetime.datetime.now() 
            for doc in potential_donors:
                is_eligible = True
                if 'lastDonationDate' in doc:
                    try:
                        lds = doc['lastDonationDate']
                        if lds.endswith('Z'): lds = lds[:-1]
                        ld = datetime.datetime.fromisoformat(lds)
                        if ld.tzinfo is not None: ld = ld.replace(tzinfo=None)
                        
                        if (now_naive - ld).days < 60:
                            is_eligible = False
                    except:
                        pass # Ignore parse errors, treat as eligible
                
                if is_eligible:
                    donors.append(doc)
            
            # Send Push
            tokens = [d['fcmToken'] for d in donors if d.get('fcmToken')]
            if tokens:
                send_push_multicast(
                    tokens, 
                    "Urgent Blood Request", 
                    f"A peer needs {data.get('bloodGroup')} blood in {data.get('location', 'your area')}.",
                    {
                        "type": "P2P_REQUEST", 
                        "requestId": str(res.inserted_id)
                    }
                )
                
            # Create In-App Notifications
            notifs = []
            for d in donors:
                notifs.append({
                    "recipientId": str(d['_id']),
                    "type": "P2P_REQUEST",
                    "title": "Peer Request",
                    "message": f"Urgent: {data.get('bloodGroup')} needed.",
                    "relatedRequestId": str(res.inserted_id),
                    "timestamp": datetime.datetime.now().isoformat(),
                    "status": "UNREAD"
                })
            if notifs:
                db.notifications.insert_many(notifs)
                
        except Exception as e:
            print(f"P2P Notify Error: {e}")
        
        return Response({"success": True, "id": str(res.inserted_id)})

    def complete_request(self, request):
        db = get_db()
        req_id = request.data.get('requestId')
        # Mark as completed
        db.requests.update_one(
             {"_id": ObjectId(req_id)},
             {"$set": {"status": "Completed", "completedAt": datetime.datetime.now().isoformat()}}
        )
        return Response({"success": True})

class DonorProfileView(APIView):
    def get(self, request):
        db = get_db()
        user_id = request.query_params.get('userId')
        if not user_id:
             return Response({"error": "userId required"}, status=400)
             
        user = db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
             return Response({"error": "User not found"}, status=404)
             
        return Response(serialize_doc(user))

class FCMTokenView(APIView):
    def post(self, request):
        db = get_db()
        user_id = request.data.get('userId')
        token = request.data.get('token')
        
        if not user_id or not token:
             return Response({"error": "userId and token required"}, status=400)
             
        db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"fcmToken": token}}
        )
        return Response({"success": True})
