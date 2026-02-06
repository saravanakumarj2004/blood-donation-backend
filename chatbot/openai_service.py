from openai import OpenAI
from django.conf import settings
from api.models import DonorProfile, DonationHistory
from datetime import datetime, timedelta
import json

# Initialize OpenAI client
client = OpenAI(api_key=settings.OPENAI_API_KEY)

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
- If user wants to book/search, suggest using quick action buttons
- Personalize based on user context when available
- Always be supportive and celebrate their life-saving contributions

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
    """Get AI-powered response from OpenAI GPT-4"""
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(user_context=user_context)}
    ]
    
    if conversation_history:
        messages.extend(conversation_history[-10:])
    
    messages.append({"role": "user", "content": user_message})
    
    functions = [
        {
            "name": "book_appointment",
            "description": "Help user book a blood donation appointment at a hospital",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "find_donors",
            "description": "Help user find blood donors in their area",
            "parameters": {
                "type": "object",
                "properties": {
                    "blood_type": {
                        "type": "string",
                        "description": "The blood type needed",
                        "enum": ["A+", "B+", "O+", "AB+", "A-", "B-", "O-", "AB-"]
                    }
                },
                "required": []
            }
        },
        {
            "name": "check_eligibility",
            "description": "Guide user to check their blood donation eligibility",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    ]
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=200,
            temperature=0.7,
            functions=functions,
            function_call="auto"
        )
        
        message = response.choices[0].message
        return {
            "content": message.content or "",
            "function_call": message.function_call.model_dump() if message.function_call else None,
            "role": "assistant",
            "usage": {"total_tokens": response.usage.total_tokens}
        }
    
    except Exception as e:
        return {
            "content": "I'm having trouble connecting right now. Please try asking again, or use the quick actions below to navigate the app directly.",
            "role": "assistant",
            "function_call": None,
            "usage": {"total_tokens": 0}
        }


def parse_function_call(function_call_data):
    """Parse OpenAI function call and return quick actions"""
    if not function_call_data:
        return []
    
    func_name = function_call_data.get('name')
    
    if func_name == 'book_appointment':
        return ['Book Now', 'View Hospitals']
    
    elif func_name == 'find_donors':
        try:
            args = json.loads(function_call_data.get('arguments', '{}'))
            if args.get('blood_type'):
                return [args['blood_type']]
        except:
            pass
        return ['A+', 'B+', 'O+', 'AB+', 'A-', 'B-', 'O-', 'AB-']
    
    elif func_name == 'check_eligibility':
        return ['Check Eligibility', 'Learn More']
    
    return []
