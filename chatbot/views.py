from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db import models
from .models import ChatConversation, ChatMessage, ChatAnalytics
from .gemini_service import get_ai_response, build_user_context, parse_function_call
import time
from django.utils import timezone


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def ask_chatbot(request):
    """
    Handle chatbot conversation with AI-powered responses
    
    POST /api/chatbot/ask
    Body: {
        "message": "Can I donate blood?",
        "conversation_id": 123  # optional, for continuing conversation
    }
    """
    start_time = time.time()
    
    user_message = request.data.get('message', '').strip()
    if not user_message:
        return Response(
            {'error': 'Message cannot be empty'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    conversation_id = request.data.get('conversation_id')
    
    try:
        # Get or create conversation
        if conversation_id:
            conversation = ChatConversation.objects.get(
                id=conversation_id,
                user=request.user,
                is_active=True
            )
            conversation.updated_at = timezone.now()
            conversation.save()
        else:
            conversation = ChatConversation.objects.create(user=request.user)
        
        # Get conversation history (last 10 messages)
        history_messages = ChatMessage.objects.filter(
            conversation=conversation
        ).order_by('-timestamp')[:10]
        
        history_formatted = [
            {"role": msg.role, "content": msg.content}
            for msg in reversed(history_messages)
        ]
        
        # Build user context
        user_context = build_user_context(request.user)
        
        # Get AI response
        ai_message = get_ai_response(user_message, user_context, history_formatted)
        
        # Extract content and function call
        message_content = ai_message.get('content', ai_message.get('message', {}).get('content', ''))
        function_call = ai_message.get('function_call')
        tokens_used = ai_message.get('usage', {}).get('total_tokens', 0)
        
        # Save user message
        ChatMessage.objects.create(
            conversation=conversation,
            role='user',
            content=user_message
        )
        
        # Save assistant message
        ChatMessage.objects.create(
            conversation=conversation,
            role='assistant',
            content=message_content,
            tokens_used=tokens_used,
            function_call=function_call
        )
        
        # Parse function call for quick actions
        quick_actions = parse_function_call(function_call) if function_call else []
        
        # Log analytics
        response_time = int((time.time() - start_time) * 1000)
        ChatAnalytics.objects.create(
            user=request.user,
            query=user_message,
            intent='ai_chat',
            response_time_ms=response_time,
            ai_used=True,
            tokens_used=tokens_used
        )
        
        return Response({
            'conversation_id': conversation.id,
            'message': message_content,
            'quick_actions': quick_actions,
            'timestamp': int(time.time() * 1000),
            'tokens_used': tokens_used
        })
    
    except ChatConversation.DoesNotExist:
        return Response(
            {'error': 'Conversation not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        import traceback
        print(f"Chatbot Exception: {str(e)}")
        print(traceback.format_exc())
        return Response(
            {'error': f'Server error: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_chat_history(request):
    """
    Get user's chat conversation history
    
    GET /api/chatbot/history?limit=5
    """
    limit = int(request.GET.get('limit', 5))
    
    conversations = ChatConversation.objects.filter(
        user=request.user,
        is_active=True
    ).order_by('-updated_at')[:limit]
    
    data = []
    for conv in conversations:
        messages = ChatMessage.objects.filter(
            conversation=conv
        ).order_by('timestamp')
        
        data.append({
            'id': conv.id,
            'created_at': conv.created_at.isoformat(),
            'updated_at': conv.updated_at.isoformat(),
            'message_count': messages.count(),
            'messages': [
                {
                    'role': msg.role,
                    'content': msg.content,
                    'timestamp': msg.timestamp.isoformat()
                }
                for msg in messages
            ]
        })
    
    return Response(data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_conversation(request, conversation_id):
    """
    Delete a conversation
    
    DELETE /api/chatbot/conversations/{id}
    """
    try:
        conversation = ChatConversation.objects.get(
            id=conversation_id,
            user=request.user
        )
        conversation.is_active = False
        conversation.save()
        
        return Response({'message': 'Conversation deleted successfully'})
    
    except ChatConversation.DoesNotExist:
        return Response(
            {'error': 'Conversation not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_analytics(request):
    """
    Get chatbot usage analytics for current user
    
    GET /api/chatbot/analytics
    """
    analytics = ChatAnalytics.objects.filter(user=request.user)
    
    total_queries = analytics.count()
    avg_response_time = analytics.aggregate(
        avg_time=models.Avg('response_time_ms')
    )['avg_time'] or 0
    total_tokens = analytics.aggregate(
        total=models.Sum('tokens_used')
    )['total'] or 0
    
    return Response({
        'total_queries': total_queries,
        'avg_response_time_ms': int(avg_response_time),
        'total_tokens_used': total_tokens,
        'ai_usage_rate': analytics.filter(ai_used=True).count() / max(total_queries, 1)
    })
