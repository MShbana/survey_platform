from django.contrib import admin

from .models import FieldResponse, SurveyResponse


class FieldResponseInline(admin.TabularInline):
    model = FieldResponse
    extra = 0
    readonly_fields = ("survey_response", "field", "value")
    can_delete = False


@admin.register(SurveyResponse)
class SurveyResponseAdmin(admin.ModelAdmin):
    list_display = ("survey", "user", "submitted_at")
    list_filter = ("survey",)
    list_select_related = ("survey", "user")
    readonly_fields = ("survey", "user", "submitted_at")
    inlines = [FieldResponseInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
