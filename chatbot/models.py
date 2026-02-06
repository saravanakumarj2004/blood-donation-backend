from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class ChatConversation(models.Model):
    """Stores a conversation session between user and chatbot"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_conversations')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-updated_at']
    
    def __str__(self):
        return f"Conversation {self.id} - {self.user.username}"


class ChatMessage(models.Model):
    """Individual messages within a conversation"""
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]
    
    conversation = models.ForeignKey(ChatConversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    tokens_used = models.IntegerField(default=0)
    function_call = models.JSONField(null=True, blank=True)  # Store function calls
    
    class Meta:
        ordering = ['timestamp']
    
    def __str__(self):
        return f"{self.role}: {self.content[:50]}"


class ChatAnalytics(models.Model):
    """Analytics for chatbot usage and performance"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    query = models.TextField()
    intent = models.CharField(max_length=50, blank=True)
    response_time_ms = models.IntegerField()
    ai_used = models.BooleanField(default=False)
    tokens_used = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Chat Analytics"
    
    def __str__(self):
        return f"{self.user.username} - {self.query[:30]}"


class FAQCategory(models.Model):
    """Categories for FAQ knowledge base"""
    name = models.CharField(max_length=100)
    icon = models.CharField(max_length=50)
    order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['order']
        verbose_name_plural = "FAQ Categories"
    
    def __str__(self):
        return self.name


class FAQItem(models.Model):
    """FAQ questions and answers for chatbot knowledge"""
    category = models.ForeignKey(FAQCategory, on_delete=models.CASCADE, related_name='questions')
    question = models.TextField()
    answer = models.TextField()
    keywords = models.JSONField(default=list)  # List of keywords for matching
    views = models.IntegerField(default=0)
    helpful_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-views']
    
    def __str__(self):
        return self.question[:100]
