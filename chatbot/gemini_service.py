from google import genai
from google.genai import types
from django.conf import settings
from api.mongo_db import get_db
from datetime import datetime, timedelta
import json

# Configure Gemini with new API
client = genai.Client(api_key=settings.GEMINI_API_KEY)

SYSTEM_PROMPT = """You are LifeLink Assistant, an AI helper for a blood donation mobile app.

**YOUR ROLE:**
Help users with blood donation questions, guide them through the app, and encourage life-saving donations.

**KNOWLEDGE BASE:**
1. **Eligibility:** Age 18-65, weighing 50kg+, in good health, no infections/antibiotics
2. **Frequency:** Whole blood every 56 days, Platelets every 7 days (max 24/year)
3. **Process:** 10-15 min donation, 45-60 min total visit (includes screening & recovery)
4. **Safety:** 100% safe, sterile single-use equipment, minimal discomfort (brief pinch)
5. **Preparation:** Eat healthy meal, drink water, sleep well, bring ID, avoid fatty foods
6. **Aftercare:** Rest 10-15 min, drink fluids, no heavy lifting (5hrs), keep bandage (4-5hrs), no alcohol (24hrs)
7. **Impact:** 1 donation saves up to 3 lives (accident victims, surgery, cancer patients, blood disorders)
8. **Restrictions:** Wait 6 months after tattoo, 24hrs after last antibiotic dose

**USER CONTEXT:**
{user_context}

**APP WORKFLOW GUIDES:**

1. **Book Appointment:**
   - Tap "Book Appointment" on Dashboard
   - Select hospital from list or search by location
   - Choose available date and time slot
   - Review details and tap "Confirm Booking"
   - Receive confirmation notification

2. **Find Blood Donors:**
   - Tap "Find Donors" on Dashboard
   - Select required blood type (A+, B+, O+, AB+, A-, B-, O-, AB-)
   - Enter location or use current location
   - View donors sorted by proximity
   - Tap "Request Blood" to contact donor

3. **Create Donor Request:**
   - Tap "+" button or "Create Request" on Dashboard
   - Fill in patient details, blood type, units needed
   - Add hospital location and urgency level
   - Set alert zones (cities to notify donors)
   - Submit request to notify nearby donors

4. **Check Eligibility:**
   - Tap "Check Eligibility" from menu or chatbot
   - Answer health screening questions honestly
   - View eligibility result (Yes/No) with explanation
   - If eligible, proceed to book appointment directly

5. **View Donation History:**
   - Go to "History" tab from bottom navigation
   - See all past donations with dates and locations
   - Tap any donation to view digital certificate
   - Tap "Share" to download or share certificate

6. **Edit Profile:**
   - Go to "Profile" tab from bottom navigation
   - Tap "Edit Profile" button in top right
   - Update name, phone, blood group, location
   - Add/update avatar, bio, occupation (optional)
   - Tap "Save Changes" to update

7. **Manage Notifications:**
   - Go to "Profile" → "Settings" (gear icon)
   - Tap "Notification Preferences"
   - Toggle on/off: Blood requests, Appointment reminders, Impact updates
   - Select alert zones (cities for urgent blood request notifications)
   - Save preferences

8. **View Impact Stats:**
   - Go to "Profile" tab
   - Scroll to "Your Impact" section
   - See total donations, lives saved estimate, impact chart
   - View personal milestones and achievements

**RESPONSE GUIDELINES:**
- Be warm, encouraging, and professional
- Keep responses under 100 words for mobile readability
- Use emojis sparingly (❤️ 🩸 ✨ only when appropriate)
- When describing workflows, mention the EXACT screen/button names
- If user wants to perform an action, suggest using the feature and add action trigger
- Personalize based on user context when available
- Always be supportive and celebrate their life-saving contributions

**ACTION TRIGGERS:**
- If user wants to book appointment, end response with: [ACTION:BOOK]
- If user wants to find donors, end response with: [ACTION:FIND_DONORS]
- If user wants to check eligibility, end response with: [ACTION:ELIGIBILITY]

**TONE:** Friendly professional who celebrates every donor as a hero."""

def build_user_context(user):
    """Build personalized context from MongoDB user data"""
    try:
        db = get_db()
        
        # Get user profile from MongoDB
        profile = db.donor_profiles.find_one({"user_id": user.id})
        if not profile:
            return "New user - Profile incomplete (encourage profile completion)"
        
        # Get donation history from MongoDB
        donations = list(db.donation_history.find(
            {"donor_id": user.id}
        ).sort("date", -1))
        
        donation_count = len(donations)
        
        context_parts = [
            f"Name: {profile.get('name', 'User')}",
            f"Blood Group: {profile.get('blood_group', 'Not set')}",
            f"Total Donations: {donation_count}",
        ]
        
        if donations:
            last_donation = donations[0]
            last_date = last_donation.get('date')
            
            if last_date:
                if isinstance(last_date, str):
                    last_date = datetime.fromisoformat(last_date.replace('Z', '+00:00'))
                
                days_since = (datetime.now() - last_date).days
                eligible = days_since >= 56
                next_eligible_date = last_date + timedelta(days=56)
                
                # Format dates outside f-string to avoid backslash issues
                last_date_str = last_date.strftime('%B %d, %Y')
                next_date_str = next_eligible_date.strftime('%B %d, %Y')
                eligibility_status = 'Yes' if eligible else f'No (eligible on {next_date_str})'
                
                context_parts.append(f"Last Donation: {days_since} days ago ({last_date_str})")
                context_parts.append(f"Currently Eligible: {eligibility_status}")
                
                lives_saved = donation_count * 3
                context_parts.append(f"Estimated Lives Saved: {lives_saved}")
        else:
            context_parts.append("Status: First-time donor (no previous donations)")
            context_parts.append("Currently Eligible: Likely yes (pending screening)")
        
        return "\n".join(context_parts)
    
    except Exception as e:
        return "Limited profile data available"


def get_ai_response(user_message, user_context, conversation_history=[]):
    """Get AI-powered response from Google Gemini (FREE!)"""
    
    # Build conversation context
    chat_context = SYSTEM_PROMPT.format(user_context=user_context)
    
    # Add conversation history
    if conversation_history:
        chat_context += "\n\n**PREVIOUS CONVERSATION:**\n"
        for msg in conversation_history[-6:]:  # Last 3 exchanges
            role = "User" if msg['role'] == 'user' else "Assistant"
            chat_context += f"{role}: {msg['content']}\n"
    
    # Build final prompt
    full_prompt = f"{chat_context}\n\nUser: {user_message}\nAssistant:"
    
    try:
        # Call Gemini API with new SDK
        response = client.models.generate_content(
            model='gemini-2.0-flash-exp',
            contents=full_prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=250,
                top_p=0.9,
            )
        )
        
        message_text = response.text.strip()
        
        # Parse action triggers
        function_call = None
        quick_actions = []
        
        if '[ACTION:BOOK]' in message_text:
            message_text = message_text.replace('[ACTION:BOOK]', '').strip()
            function_call = {'name': 'book_appointment'}
            quick_actions = ['Book Now', 'View Hospitals']
        elif '[ACTION:FIND_DONORS]' in message_text:
            message_text = message_text.replace('[ACTION:FIND_DONORS]', '').strip()
            function_call = {'name': 'find_donors'}
            quick_actions = ['A+', 'B+', 'O+', 'AB+', 'A-', 'B-', 'O-', 'AB-']
        elif '[ACTION:ELIGIBILITY]' in message_text:
            message_text = message_text.replace('[ACTION:ELIGIBILITY]', '').strip()
            function_call = {'name': 'check_eligibility'}
            quick_actions = ['Check Eligibility', 'Learn More']
        
        return {
            "content": message_text,
            "function_call": function_call,
            "role": "assistant",
            "usage": {"total_tokens": 0}
        }
    
    except Exception as e:
        print(f"Gemini API Error: {str(e)}")
        return {
            "content": "I'm having trouble connecting right now. Please try asking again, or use the quick actions below to navigate the app directly.",
            "role": "assistant",
            "function_call": None,
            "usage": {"total_tokens": 0}
        }


def parse_function_call(function_call_data):
    """Parse function call and return quick actions"""
    if not function_call_data:
        return []
    
    func_name = function_call_data.get('name')
    
    if func_name == 'book_appointment':
        return ['Book Now', 'View Hospitals']
    elif func_name == 'find_donors':
        return ['A+', 'B+', 'O+', 'AB+', 'A-', 'B-', 'O-', 'AB-']
    elif func_name == 'check_eligibility':
        return ['Check Eligibility', 'Learn More']
    
    return []
