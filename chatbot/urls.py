from django.urls import path
from . import views

urlpatterns = [
    path('ask', views.ask_chatbot, name='chatbot-ask'),
    path('history', views.get_chat_history, name='chatbot-history'),
    path('conversations/<int:conversation_id>', views.delete_conversation, name='chatbot-delete'),
    path('analytics', views.get_analytics, name='chatbot-analytics'),
]
