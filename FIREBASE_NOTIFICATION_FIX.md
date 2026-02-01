# Firebase Push Notification Fix

## Problem
P2P donor notifications were **NOT appearing in the system notification drawer** but were visible inside the app.

### Root Cause
Backend logs showed error:
```
AttributeError: module 'firebase_admin.messaging' has no attribute 'send_multicast'
```

This occurred because:
- Firebase Admin SDK v6+ **deprecated** `send_multicast()`
- The correct method is `send_each_for_multicast()`
- Our code was using the old API, causing push notifications to fail silently

## Solution Implemented

### 1. Updated `api/views.py` (Line 29-45)
**Before:**
```python
messaging.send_multicast(message)
```

**After:**
```python
response = messaging.send_each_for_multicast(message)
print(f"Push sent successfully: {response.success_count} succeeded, {response.failure_count} failed")
return response
```

### 2. Updated `api/ext_views.py` (Line 104-122)
**Before:**
```python
messaging.send_multicast(msg)
```

**After:**
```python
response = messaging.send_each_for_multicast(msg)
print(f"FCM Broadcast: {response.success_count}/{len(fcm_tokens)} sent successfully")
```

### 3. Added Notification Data Payload
```python
data={"requestId": req_id, "type": "URGENT_REQUEST"}
```

This allows the Flutter app to handle notifications properly and navigate to the correct screen.

### 4. Enhanced Error Logging
Added detailed traceback printing to help diagnose future notification issues.

## Expected Result

### Before Fix:
- ❌ Push notifications **failed silently**
- ❌ No system drawer notifications
- ⚠️ Only in-app notifications visible (from database polling)

### After Fix:
- ✅ Push notifications sent successfully
- ✅ Notifications appear in **system drawer**
- ✅ Notifications appear in **app**
- ✅ Tapping notification opens the app with proper context
- ✅ Detailed logging shows success/failure count

## How to Test

1. **Trigger a P2P Request**:
   - User A creates a blood request in the app
   - System broadcasts to donors in the same city

2. **Check Logs** (Render Dashboard):
   ```
   FCM Broadcast: 5/5 sent successfully
   ```

3. **Check User B's Phone**:
   - System notification drawer should show:
     ```
     Emergency Blood Request
     Urgent: O+ needed in Chennai!
     ```
   - Tapping opens the app to the request details

4. **Verify In-App**:
   - Bell icon should show notification count
   - Notification center shows the alert

## Firebase Admin SDK Compatibility

| Version | Method | Status |
|---------|--------|--------|
| < v6.0 | `send_multicast()` | ✅ Works (Deprecated) |
| v6.0+ | `send_each_for_multicast()` | ✅ Current Standard |
| v7.0+ | `send_each_for_multicast()` | ✅ Recommended |

Our fix uses `send_each_for_multicast()` which is **compatible with v6.0 and above**.

## Files Changed
- `api/views.py` - Updated `send_push_multicast()` helper
- `api/ext_views.py` - Updated P2P notification broadcast

## Deployment
✅ Pushed to GitHub
✅ Render will auto-deploy
✅ No mobile app changes needed (backend-only fix)

## Next Steps
Monitor Render logs after deployment to confirm notifications are being sent successfully.
