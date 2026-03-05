from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Max

from .cache import SurveyCacheService
from .models import ConditionalRule, Field, FieldDependency, Section, Survey
from .services import (
    detect_circular_dependencies_cr,
    detect_circular_dependencies_fd,
    validate_conditional_rule_data,
    validate_field_dependency_data,
    validate_field_options,
    validate_survey_is_draft,
    validate_validation_rules,
)


class SectionInline(admin.TabularInline):
    model = Section
    extra = 0
    show_change_link = True


class FieldInline(admin.TabularInline):
    model = Field
    extra = 0
    show_change_link = True


def _validation_error_to_message(request, exc):
    """Convert a ValidationError to admin error messages."""
    if hasattr(exc, "message_dict"):
        for field, errs in exc.message_dict.items():
            for err in errs:
                messages.error(request, f"{field}: {err}")
    elif hasattr(exc, "messages"):
        for msg in exc.messages:
            messages.error(request, msg)
    else:
        messages.error(request, str(exc))


@admin.register(Survey)
class SurveyAdmin(admin.ModelAdmin):
    list_display = ("title", "created_by", "status", "created_at")
    list_filter = ("status",)
    inlines = [SectionInline]
    ordering = ("-id",)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.status = Survey.SurveyStatus.DRAFT
            super().save_model(request, obj, form, change)
        else:
            if "status" in form.changed_data:
                try:
                    obj.transition_to(form.cleaned_data["status"])
                except ValidationError as exc:
                    _validation_error_to_message(request, exc)
                    return
            else:
                super().save_model(request, obj, form, change)
        SurveyCacheService.invalidate_structure(obj.pk)

    def delete_model(self, request, obj):
        SurveyCacheService.invalidate_structure(obj.pk)
        super().delete_model(request, obj)

    def save_formset(self, request, form, formset, change):
        draft_checked = False
        for inline_form in formset.forms:
            if not inline_form.has_changed():
                continue
            if not draft_checked:
                try:
                    validate_survey_is_draft(form.instance)
                except ValidationError as exc:
                    _validation_error_to_message(request, exc)
                    return
                draft_checked = True

            if formset.model is Field:
                obj = inline_form.instance
                try:
                    validate_field_options(
                        obj.field_type, obj.options
                    )
                    validate_validation_rules(
                        obj.field_type, obj.validation_rules
                    )
                except ValidationError as exc:
                    _validation_error_to_message(request, exc)
                    return

        try:
            formset.save()
        except IntegrityError:
            messages.error(request, "Duplicate order values are not allowed.")
            return
        SurveyCacheService.invalidate_structure(form.instance.pk)


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("title", "survey", "order")
    inlines = [FieldInline]
    ordering = ("-id",)

    def save_model(self, request, obj, form, change):
        try:
            validate_survey_is_draft(obj.survey)
        except ValidationError as exc:
            _validation_error_to_message(request, exc)
            return

        if not obj.order:
            max_order = (
                Section.objects.filter(survey=obj.survey).aggregate(m=Max("order"))["m"]
                or 0
            )
            obj.order = max_order + 1

        try:
            super().save_model(request, obj, form, change)
        except IntegrityError:
            messages.error(request, "A section with this order already exists.")
            return
        SurveyCacheService.invalidate_structure(obj.survey_id)

    def delete_model(self, request, obj):
        try:
            validate_survey_is_draft(obj.survey)
        except ValidationError as exc:
            _validation_error_to_message(request, exc)
            return
        survey_id = obj.survey_id
        super().delete_model(request, obj)
        SurveyCacheService.invalidate_structure(survey_id)

    def save_formset(self, request, form, formset, change):
        draft_checked = False
        for inline_form in formset.forms:
            if not inline_form.has_changed():
                continue
            if not draft_checked:
                try:
                    validate_survey_is_draft(form.instance.survey)
                except ValidationError as exc:
                    _validation_error_to_message(request, exc)
                    return
                draft_checked = True

            if formset.model is Field:
                obj = inline_form.instance
                try:
                    validate_field_options(obj.field_type, obj.options)
                    validate_validation_rules(obj.field_type, obj.validation_rules)
                except ValidationError as exc:
                    _validation_error_to_message(request, exc)
                    return

        try:
            formset.save()
        except IntegrityError:
            messages.error(request, "Duplicate order values are not allowed.")
            return
        SurveyCacheService.invalidate_structure(form.instance.survey_id)


@admin.register(Field)
class FieldAdmin(admin.ModelAdmin):
    list_display = ("label", "section", "field_type", "required", "order")
    ordering = ("-id",)

    def save_model(self, request, obj, form, change):
        try:
            validate_survey_is_draft(obj.section.survey)
            validate_field_options(obj.field_type, obj.options)
            validate_validation_rules(obj.field_type, obj.validation_rules)
        except ValidationError as exc:
            _validation_error_to_message(request, exc)
            return

        if not obj.order:
            max_order = (
                Field.objects.filter(section=obj.section).aggregate(m=Max("order"))["m"]
                or 0
            )
            obj.order = max_order + 1

        try:
            super().save_model(request, obj, form, change)
        except IntegrityError:
            messages.error(request, "A field with this order already exists.")
            return
        SurveyCacheService.invalidate_structure(obj.section.survey_id)

    def delete_model(self, request, obj):
        try:
            validate_survey_is_draft(obj.section.survey)
        except ValidationError as exc:
            _validation_error_to_message(request, exc)
            return
        survey_id = obj.section.survey_id
        super().delete_model(request, obj)
        SurveyCacheService.invalidate_structure(survey_id)


@admin.register(ConditionalRule)
class ConditionalRuleAdmin(admin.ModelAdmin):
    list_display = (
        "survey",
        "depends_on_field",
        "operator",
        "value",
        "target_section",
        "target_field",
    )
    list_filter = ("survey",)
    ordering = ("-id",)


    def save_model(self, request, obj, form, change):
        try:
            validate_survey_is_draft(obj.survey)
        except ValidationError as exc:
            _validation_error_to_message(request, exc)
            return

        data = {
            "target_section": obj.target_section,
            "target_field": obj.target_field,
            "depends_on_field": obj.depends_on_field,
            "operator": obj.operator,
            "value": obj.value,
        }
        try:
            validate_conditional_rule_data(data)
        except ValidationError as exc:
            _validation_error_to_message(request, exc)
            return

        try:
            detect_circular_dependencies_cr(
                depends_on_field=obj.depends_on_field,
                target_field=obj.target_field,
                target_section=obj.target_section,
                exclude_rule_id=obj.pk if change else None,
            )
        except ValidationError as exc:
            _validation_error_to_message(request, exc)
            return

        super().save_model(request, obj, form, change)
        SurveyCacheService.invalidate_structure(obj.survey_id)

    def delete_model(self, request, obj):
        try:
            validate_survey_is_draft(obj.survey)
        except ValidationError as exc:
            _validation_error_to_message(request, exc)
            return
        survey_id = obj.survey_id
        super().delete_model(request, obj)
        SurveyCacheService.invalidate_structure(survey_id)


@admin.register(FieldDependency)
class FieldDependencyAdmin(admin.ModelAdmin):
    list_display = ("survey", "dependent_field", "depends_on_field", "operator", "action")
    list_filter = ("survey",)
    ordering = ("-id",)


    def save_model(self, request, obj, form, change):
        try:
            validate_survey_is_draft(obj.survey)
        except ValidationError as exc:
            _validation_error_to_message(request, exc)
            return

        data = {
            "dependent_field": obj.dependent_field,
            "depends_on_field": obj.depends_on_field,
            "operator": obj.operator,
            "value": obj.value,
            "action": obj.action,
            "action_value": obj.action_value,
        }
        try:
            validate_field_dependency_data(data)
        except ValidationError as exc:
            _validation_error_to_message(request, exc)
            return

        try:
            detect_circular_dependencies_fd(
                depends_on_field=obj.depends_on_field,
                dependent_field=obj.dependent_field,
                exclude_dep_id=obj.pk if change else None,
            )
        except ValidationError as exc:
            _validation_error_to_message(request, exc)
            return

        super().save_model(request, obj, form, change)
        SurveyCacheService.invalidate_structure(obj.survey_id)

    def delete_model(self, request, obj):
        try:
            validate_survey_is_draft(obj.survey)
        except ValidationError as exc:
            _validation_error_to_message(request, exc)
            return
        survey_id = obj.survey_id
        super().delete_model(request, obj)
        SurveyCacheService.invalidate_structure(survey_id)
