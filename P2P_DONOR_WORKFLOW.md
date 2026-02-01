# P2P (Peer-to-Peer) Donor Workflow - Complete Guide

## What is P2P Donor Request?

**P2P (Peer-to-Peer) Blood Request** allows any donor in the app to request blood for their family member, friend, or patient. Unlike hospital requests, this is a **donor-driven emergency alert system** where donors help other donors.

---

## Complete Workflow (End-to-End)

### 📱 STEP 1: Donor Creates a Blood Request

**Who:** Any registered donor (User A)  
**Where:** Mobile App → "My Requests" Screen → "Create New Request" button

**User A fills in the form:**
```
- Patient Name: "John Doe"
- Patient Contact: "+91 9876543210"
- Attender Name: "Jane Doe"
- Attender Contact: "+91 9876543211"
- Blood Group: "O+" (dropdown)
- Units Needed: "2"
- Urgency: "Critical" (Critical / Urgent / Moderate)
- Hospital Name: "Apollo Hospital"
- Hospital Address: "123 Main St, Chennai"
- City: "Chennai" (important for targeting)
```

**Submit Button Pressed** → API Call to Backend

---

### 🌐 STEP 2: Backend Processes the Request

**Endpoint:** `POST /api/donor/requests/`  
**Handler:** `DonorP2PView.post()` in `views.py`

#### Backend Actions:

**A. Create Request in Database**
```python
new_request = {
    "requesterId": user_a_id,  # From JWT token
    "patientName": "John Doe",
    "patientNumber": "+91 9876543210",
    "attenderName": "Jane Doe",
    "attenderNumber": "+91 9876543211",
    "bloodGroup": "O+",
    "units": 2,
    "urgency": "Critical",
    "hospitalName": "Apollo Hospital",
    "location": "123 Main St, Chennai",
    "city": "Chennai",
    "status": "Active",
    "type": "P2P",
    "date": "2026-02-01T18:30:00"
}
db.requests.insert_one(new_request)
# Returns request_id: "67a3f2c1..."
```

**B. Find Target Donors**
```python
# Find all donors in the same city, excluding the requester
target_donors = db.users.find({
    "role": "donor",
    "location": {"$regex": "Chennai", "$options": "i"},  # Case-insensitive
    "_id": {"$ne": user_a_id}  # Exclude requester
})
# Result: [User B, User C, User D, User E, ...] (50 donors)
```

**C. Create In-App Notifications**
```python
# Batch insert notifications for ALL target donors
notifications = []
for donor in target_donors:
    notifications.append({
        "userId": donor['_id'],
        "message": "Urgent: O+ needed in Chennai!",
        "type": "URGENT_REQUEST",
        "requestId": request_id,
        "status": "UNREAD",
        "timestamp": "2026-02-01T18:30:00"
    })

db.notifications.insert_many(notifications)
# 50 notifications inserted
```

**D. Send Push Notifications**
```python
fcm_tokens = []
for donor in target_donors:
    if donor.get('fcmToken'):
        fcm_tokens.append(donor['fcmToken'])
# fcm_tokens = ["token1", "token2", ..., "token50"]

# Firebase Cloud Messaging
message = messaging.MulticastMessage(
    notification=messaging.Notification(
        title="Emergency Blood Request",
        body="Urgent: O+ needed in Chennai!"
    ),
    data={
        "requestId": request_id,
        "type": "URGENT_REQUEST"
    },
    tokens=fcm_tokens
)

response = messaging.send_each_for_multicast(message)
# Success: 48/50 sent (2 failed due to invalid tokens)
```

**Backend Response to User A:**
```json
{
  "success": true,
  "requestId": "67a3f2c1...",
  "notifiedCount": 50
}
```

---

### 📲 STEP 3: Target Donors Receive Notifications

**When:** Immediately after backend processes the request

#### A. System Notification Drawer (Android)
```
🔴 Emergency Blood Request
   Urgent: O+ needed in Chennai!
   Tap to view details
```

#### B. In-App Notification
- **Bell Icon** shows red badge with count
- Notification appears in "Notifications" tab
- Auto-updates if app is open (via polling/WebSocket)

---

### 👀 STEP 4: Donor Views the Request

**Who:** Target donor (User B)  
**Action:** Taps notification or opens "Active Requests" screen

**API Call:** `GET /api/donor/active-requests/`  
**Returns:**
```json
[
  {
    "id": "67a3f2c1...",
    "requesterName": "Sarah Kumar",  // User A's name
    "patientName": "John Doe",
    "patientNumber": "+91 9876543210",
    "bloodGroup": "O+",
    "units": "2",
    "urgency": "Critical",
    "hospitalName": "Apollo Hospital",
    "location": "123 Main St, Chennai",
    "city": "Chennai",
    "status": "Active",
    "date": "2026-02-01T18:30:00",
    "type": "P2P"
  }
]
```

**User B sees:**
```
┌─────────────────────────────────────┐
│ 🩸 URGENT BLOOD REQUEST             │
├─────────────────────────────────────┤
│ Patient: John Doe                   │
│ Blood Group: O+ (2 Units)           │
│ Urgency: 🔴 Critical                │
│                                     │
│ Hospital: Apollo Hospital           │
│ Location: 123 Main St, Chennai      │
│                                     │
│ Requester: Sarah Kumar              │
│ Contact: +91 9876543211 (Attender)  │
│                                     │
│ [Call Attender] [Ignore] [Respond] │
└─────────────────────────────────────┘
```

---

### 🤝 STEP 5: Donor Responds to Request

User B has 3 options:

#### **Option 1: Ignore**
```dart
ApiService.ignoreRequest(requestId)
```
- Request removed from User B's view
- No notification sent to User A
- Request remains Active for other donors

#### **Option 2: Call Attender**
```dart
url_launcher.launch('tel:+91 9876543211')
```
- Direct phone call to discuss details
- User B can confirm eligibility, location, etc.

#### **Option 3: Respond (Accept)**
**Current Implementation:** Opens phone dialer to contact attender
**Future Enhancement:** Could track who responded and update status

---

### ✅ STEP 6: Request Completion

**Who:** User A (original requester)  
**When:** After finding a donor and completing donation  
**Action:** Marks request as "Completed"

**API Call:** `POST /api/donor/requests/complete/`
```json
{
  "requestId": "67a3f2c1...",
  "status": "Completed"
}
```

**Backend Updates:**
```python
db.requests.update_one(
    {"_id": ObjectId(request_id)},
    {"$set": {"status": "Completed"}}
)
```

**Result:**
- Request removed from "Active Requests" for all donors
- User A sees it in "My Requests" with status "Completed"
- Notifications cleared/archived

---

## Complete Data Flow Diagram

```
┌──────────────┐
│   User A     │  Creates Request
│   (Donor)    │  "Need O+ blood in Chennai"
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────┐
│         Backend API                   │
│  POST /api/donor/requests/            │
├──────────────────────────────────────┤
│ 1. Insert request in MongoDB          │
│ 2. Find target donors (Chennai, O+)   │
│ 3. Create 50 in-app notifications     │
│ 4. Send 50 push notifications (FCM)   │
└───────┬──────────────────────────────┘
        │
        ├───────────────┬──────────────┬──────────────┐
        ▼               ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│   User B     │ │   User C     │ │   User D     │ │  ... (50)    │
│   (Donor)    │ │   (Donor)    │ │   (Donor)    │ │   (Donors)   │
├──────────────┤ ├──────────────┤ ├──────────────┤ ├──────────────┤
│ 📱 Push      │ │ 📱 Push      │ │ 📱 Push      │ │ 📱 Push      │
│ 🔔 In-App    │ │ 🔔 In-App    │ │ 🔔 In-App    │ │ 🔔 In-App    │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────────────┘
       │                │                │
       │ Views Request  │ Ignores        │ Calls Attender
       ▼                ▼                ▼
┌──────────────────────────────────────────────────┐
│         Active Requests List                      │
│  - Shows all active P2P requests in their city    │
│  - Real-time updates                              │
│  - Action buttons: Call/Ignore/Respond            │
└──────────────────────────────────────────────────┘
       │
       │ User B agrees to donate
       ▼
┌──────────────┐
│ Phone Call   │ ──────────► User A gets help!
│ to Attender  │             Donation arranged
└──────────────┘
       │
       ▼
┌──────────────┐
│   User A     │ Marks request as "Completed"
│ (Requester)  │ POST /api/donor/requests/complete/
└──────────────┘
```

---

## Key Features

### 1. **City-Based Targeting**
- Only donors in the **same city** receive notifications
- Uses regex matching: `location: {"$regex": "Chennai", "$options": "i"}`
- Ensures relevant donors are notified

### 2. **Multi-Channel Notifications**
- **Push Notifications** (System drawer)
- **In-App Notifications** (Database-backed)
- **Bell Icon Badge** (Real-time count)

### 3. **Privacy & Security**
- Requester's personal contact **not shared**
- Only attender contact visible
- JWT authentication required for all actions

### 4. **Donor Filtering**
- Requester **excluded** from receiving their own notification
- Inactive/unavailable donors still notified (they can ignore)

### 5. **Request Lifecycle**
```
Active → Completed/Cancelled
   ↓
  (Can be viewed in "My Requests" history)
```

---

## API Endpoints Used

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/donor/requests/` | POST | Create new P2P request |
| `/api/donor/active-requests/` | GET | Get all active requests in user's city |
| `/api/donor/my-requests/` | GET | Get user's created requests |
| `/api/donor/ignore-request/` | POST | Hide request from user's view |
| `/api/donor/requests/complete/` | POST | Mark request as completed |

---

## Mobile App Screens

### 1. **My Requests Screen**
- Shows requests **created by the user**
- Status indicators: Active/Completed/Cancelled
- "Create New Request" button

### 2. **Active Requests Screen**
- Shows **all active P2P requests** in user's city
- Includes requests from other donors
- Real-time updates
- Filter by blood group (optional)

### 3. **Notification Center**
- Bell icon with badge count
- List of all notifications
- Tap to navigate to request details

---

## Success Indicators

✅ **Request Created:**
- User A sees confirmation: "Request sent to 50 donors in Chennai!"

✅ **Notifications Sent:**
- Backend logs: `FCM Broadcast: 48/50 sent successfully`

✅ **Donors Notified:**
- System notification appears
- In-app bell icon shows badge

✅ **Donor Responds:**
- Calls attender
- Donation arranged offline

✅ **Request Completed:**
- Status updated to "Completed"
- Removed from active requests

---

## Current Limitations & Future Enhancements

### Current Limitations:
1. **No Response Tracking** - We don't know which donors responded
2. **No Auto-Matching** - Requester manually marks as completed
3. **No Distance Filter** - Only city-based, not location-based
4. **No Real-Time Updates** - Uses polling instead of WebSockets

### Planned Enhancements:
1. **Track Responders** - Show who called/responded
2. **Auto-Complete** - When donor confirms via app
3. **Distance-Based** - Show nearest donors first
4. **WebSocket** - Real-time updates without polling
5. **Chat Feature** - In-app messaging between requester and donor

---

## Testing the P2P Flow

### End-to-End Test:

1. **Register 2 Users:**
   - User A: Chennai, O+
   - User B: Chennai, O+

2. **User A: Create Request**
   - Fill form → Submit
   - Check for success message

3. **Check Backend Logs**
   - Render dashboard → View logs
   - Verify: `FCM Broadcast: 1/1 sent successfully`

4. **User B: Check Notification**
   - System drawer should show notification
   - Bell icon should have badge (1)
   - "Active Requests" should show the request

5. **User B: Respond**
   - Tap "Call Attender"
   - Call should initiate

6. **User A: Complete Request**
   - Go to "My Requests"
   - Tap request → Mark as "Completed"
   - Verify status changes

---

## Summary

The P2P donor workflow creates a **community-driven emergency blood network** where donors can help each other. The system leverages:

- **MongoDB** for data storage
- **Firebase Cloud Messaging** for push notifications
- **City-based targeting** for relevant alerts
- **Multi-channel notifications** for maximum reach
- **Privacy-first design** with minimal data sharing

This enables **rapid response** in emergencies while maintaining user privacy and control.
