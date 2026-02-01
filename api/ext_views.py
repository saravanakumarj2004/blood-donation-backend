
# ==========================================
#  MISSING VIEWS IMPLEMENTATION
# ==========================================

class DonorCountView(APIView):
    def get(self, request):
        db = get_db()
        city = request.query_params.get('city')
        if not city:
             return Response({"count": 0})
        
        # Count donors in this city
        # Case insensitive regex match
        count = db.users.count_documents({
            "role": "donor",
            "location": {"$regex": city, "$options": "i"}
        })
        return Response({"count": count})

class ActiveLocationsView(APIView):
    def get(self, request):
        db = get_db()
        # distinct locations from donors
        locations = db.users.distinct("location", {"role": "donor"})
        
        cities = set()
        for loc in locations:
            if loc:
                # Naive split by comma to get City
                parts = loc.split(',')
                if len(parts) > 0:
                    cities.add(parts[0].strip())
        
        return Response(list(cities))

class DonorP2PRequestView(APIView):
    def post(self, request):
        db = get_db()
        data = request.data
        
        requester_id = data.get('requesterId')
        city = data.get('city')
        
        if not requester_id or not city:
            return Response({"error": "Requester ID and City required"}, status=400)

        # 1. Create Request
        new_req = {
            "requesterId": requester_id,
            "patientName": data.get('patientName'),
            "patientNumber": data.get('patientNumber'),
            "attenderName": data.get('attenderName'),
            "attenderNumber": data.get('attenderNumber'),
            "bloodGroup": data.get('bloodGroup'),
            "units": data.get('units'),
            "urgency": data.get('urgency'),
            "hospitalName": data.get('hospitalName'),
            "location": data.get('location'), # Hospital Address
            "city": city, # Target broadcast city
            "status": "Pending",
            "date": datetime.datetime.now().isoformat(),
            "type": "P2P"
        }
        res = db.requests.insert_one(new_req)
        req_id = str(res.inserted_id)
        
        # 2. Find Target Donors for Notification
        # Donors in the same city, excluding requester
        target_donors = db.users.find({
            "role": "donor",
            "_id": {"$ne": ObjectId(requester_id)},
            "location": {"$regex": city, "$options": "i"}
        })
        
        donors_list = list(target_donors)
        notification_count = 0
        
        # 3. Create Notifications in DB (CRITICAL for Bell Icon/Popup polling)
        notif_msg = f"Urgent: {data.get('bloodGroup')} needed in {city}!"
        
        notifications_to_insert = []
        fcm_tokens = []
        
        for donor in donors_list:
            # DB Notification
            notifications_to_insert.append({
                "userId": str(donor['_id']),
                "message": notif_msg,
                "type": "URGENT_REQUEST",
                "requestId": req_id,
                "status": "UNREAD",
                "timestamp": datetime.datetime.now().isoformat()
            })
            
            # Collect FCM Token
            if donor.get('fcmToken'):
                 fcm_tokens.append(donor.get('fcmToken'))

        if notifications_to_insert:
            db.notifications.insert_many(notifications_to_insert)
            notification_count = len(notifications_to_insert)
            
        # 4. Try FCM Broadcast (Fire & Forget)
        if fcm_tokens:
            try:
                # Requires firebase_admin setup
                from firebase_admin import messaging
                msg = messaging.MulticastMessage(
                    notification=messaging.Notification(
                        title="Emergency Blood Request",
                        body=notif_msg
                    ),
                    data={"requestId": req_id, "type": "URGENT_REQUEST"},
                    tokens=fcm_tokens
                )
                # Use correct Firebase Admin SDK method
                response = messaging.send_each_for_multicast(msg)
                print(f"FCM Broadcast: {response.success_count}/{len(fcm_tokens)} sent successfully")
            except Exception as e:
                print(f"FCM Error: {e}")
                import traceback
                traceback.print_exc()

        return Response({
            "success": True, 
            "requestId": req_id, 
            "notifiedCount": notification_count
        })

# Placeholders for Hospital Views to prevent Import Errors
class HospitalDonorListView(APIView):
    def get(self, request):
        return Response([])

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
        if not user_id:
            return Response([])
        requests = db.requests.find({"requesterId": user_id}).sort("date", -1)
        res = []
        for r in requests:
            r['id'] = str(r['_id'])
            del r['_id']
            res.append(r)
        return Response(res)
