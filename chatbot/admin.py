from django.contrib import admin
from .models import ChatConversation, ChatMessage, ChatAnalytics, FAQCategory, FAQItem


@admin.register(ChatConversation)
class ChatConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'created_at', 'updated_at', 'is_active')
    list_filter = ('is_active', 'created_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'role', 'content_preview', 'timestamp', 'tokens_used')
    list_filter = ('role', 'timestamp')
    search_fields = ('content', 'conversation__user__username')
    readonly_fields = ('timestamp',)
    
    def content_preview(self, obj):
        return obj.content[:100] + '...' if len(obj.content) > 100 else obj.content
    content_preview.short_description = 'Content'


@admin.register(ChatAnalytics)
class ChatAnalyticsAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'query_preview', 'intent', 'response_time_ms', 'ai_used', 'tokens_used', 'created_at')
    list_filter = ('ai_used', 'intent', 'created_at')
    search_fields = ('user__username', 'query')
    readonly_fields = ('created_at',)
    
    def query_preview(self, obj):
        return obj.query[:50] + '...' if len(obj.query) > 50 else obj.query
    query_preview.short_description = 'Query'


@admin.register(FAQCategory)
class FAQCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'icon', 'order')
    list_editable = ('order',)
    ordering = ('order',)


@admin.register(FAQItem)
class FAQItemAdmin(admin.ModelAdmin):
    list_display = ('question_preview', 'category', 'views', 'helpful_count', 'updated_at')
    list_filter = ('category', 'created_at')
    search_fields = ('question', 'answer', 'keywords')
    readonly_fields = ('views', 'created_at', 'updated_at')
    
    def question_preview(self, obj):
        return obj.question[:100] + '...' if len(obj.question) > 100 else obj.question
    question_preview.short_description = 'Question'
