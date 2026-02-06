import google.generativeai as genai
from django.conf import settings
from api.models import DonorProfile, DonationHistory
from datetime import datetime, timedelta
import json

# Configure Gemini
genai.configure(api_key=settings.GEMINI_API_KEY)

# Initialize Gemini model
model = genai.GenerativeModel('gemini-1.5-flash')

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

**AVAILABLE APP FEATURES:**
- Book Appointment: Schedule blood donation at hospitals
- Find Donors: Search for donors by blood type and location
- Check Eligibility: Interactive eligibility quiz
- View History: See past donations and track impact

**RESPONSE GUIDELINES:**
- Be warm, encouraging, and professional
- Keep responses under 80 words for mobile readability
- Use emojis sparingly (❤️ 🩸 ✨ only when appropriate)
- If user wants to book/search, suggest "Use the buttons below" instead of describing actions
- Personalize based on user context when available
- Always be supportive and celebrate their life-saving contributions

**ACTION TRIGGERS:**
- If user wants to book appointment, end response with: [ACTION:BOOK]
- If user wants to find donors, end response with: [ACTION:FIND_DONORS]
- If user wants to check eligibility, end response with: [ACTION:ELIGIBILITY]

**TONE:** Friendly professional who celebrates every donor as a hero."""

def build_user_context(user):
    """Build personalized context from user's profile and donation history"""
    try:
        profile = DonorProfile.objects.get(user=user)
        donations = DonationHistory.objects.filter(donor=user).order_by('-date')
        donation_count = donations.count()
        
        context_parts = [
            f"Name: {profile.name}",
            f"Blood Group: {profile.blood_group}",
            f"Total Donations: {donation_count}",
        ]
        
        if donations.exists():
            last_donation = donations.first()
            days_since = (datetime.now().date() - last_donation.date).days
            eligible = days_since >= 56
            next_eligible_date = last_donation.date + timedelta(days=56)
            
            context_parts.append(f"Last Donation: {days_since} days ago ({last_donation.date})")
            context_parts.append(f"Currently Eligible: {'Yes' if eligible else f'No (eligible on {next_eligible_date})'}")
            
            lives_saved = donation_count * 3
            context_parts.append(f"Estimated Lives Saved: {lives_saved}")
        else:
            context_parts.append("Status: First-time donor (no previous donations)")
            context_parts.append("Currently Eligible: Likely yes (pending screening)")
        
        return "\n".join(context_parts)
    
    except DonorProfile.DoesNotExist:
        return "New user - Profile incomplete (encourage profile completion)"
    except Exception:
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
        # Call Gemini API (FREE!)
        response = model.generate_content(
            full_prompt,
            generation_config={
                'temperature': 0.7,
                'max_output_tokens': 200,
                'top_p': 0.9,
            }
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
            "usage": {"total_tokens": 0}  # Gemini free tier doesn't expose token count
        }
    
    except Exception as e:
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
