
from csv import writer
from datetime import datetime
from mimetypes import guess_type
from os.path import join

from django.conf import settings
from django.conf.urls.defaults import patterns, url
from django.contrib import admin
from django.core.files.storage import FileSystemStorage
from django.core.urlresolvers import reverse
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.defaultfilters import slugify
from django.utils.translation import ugettext_lazy as _

from tendenci.core.perms.admin import TendenciBaseModelAdmin

from tendenci.apps.forms_builder.forms.models import Form, Field, FormEntry, FieldEntry, Pricing
from tendenci.apps.forms_builder.forms.settings import UPLOAD_ROOT
from tendenci.apps.forms_builder.forms.forms import FormAdminForm, FormForField, PricingForm

fs = FileSystemStorage(location=UPLOAD_ROOT)


class PricingAdminForm(PricingForm):
    class Meta:
        model = Pricing
        exclude = ('billing_period',
                   'billing_frequency',
                   'num_days',
                   'due_sore',
                  )


class PricingAdmin(admin.StackedInline):
    model = Pricing
    form = PricingAdminForm
    extra = 0


class FieldAdminForm(FormForField):
    class Meta:
        model = Field


class FieldAdmin(admin.TabularInline):
    model = Field
    form = FieldAdminForm
    extra = 0
    ordering = ("position",)
    template = "forms/admin/tabular.html"


class FormAdmin(TendenciBaseModelAdmin):

    form = FormAdminForm

    inlines = (PricingAdmin, FieldAdmin,)
    list_display = ("title", "id", "intro", "email_from", "email_copies",
        "admin_link_export", "admin_link_view")
    list_display_links = ("title",)
    search_fields = ("title", "intro", "response", "email_from",
        "email_copies")
    prepopulated_fields = {'slug': ['title']}
    fieldsets = (
        (None, {"fields": ("title", "slug", "intro", "response", "completion_url", "template", "create_user")}),
        (_("Email"), {"fields": ('subject_template', "email_from", "email_copies", "send_email", "email_text")}),
        ('Permissions', {'fields': ('allow_anonymous_view',)}),
        ('Advanced Permissions', {'classes': ('collapse',), 'fields': (
            'user_perms',
            'member_perms',
            'group_perms',
        )}),
        ('Publishing Status', {'fields': (
            'status',
            'status_detail'
        )}),
        ("Predefined Fields", {"fields": (("first_name", "last_name", "email", "url", "group_subscription"), ("address", "city", "state", "zipcode", "country", "phone", "comments"), ("company_name", "company_address", "company_city", "company_state", "company_zipcode", "company_country", "company_phone", "position_title")), 'classes': ('predefined-fields',)}),
        (_("Payment"), {"fields": ("custom_payment", 'recurring_payment', "payment_methods")}),
    )

    class Media:
        js = (
            '%sjs/jquery-1.6.2.min.js' % settings.STATIC_URL,
            'https://ajax.googleapis.com/ajax/libs/jqueryui/1.8.18/jquery-ui.min.js',
            '%sjs/admin/form-fields-inline-ordering.js' % settings.STATIC_URL,
            '%sjs/admin/form-field-dynamic-hiding.js' % settings.STATIC_URL,
        )
        css = {'all': ['%scss/admin/dynamic-inlines-with-sort.css' % settings.STATIC_URL], }

    def get_urls(self):
        """
        Add the export view to urls.
        """
        urls = super(FormAdmin, self).get_urls()
        extra_urls = patterns("",
            url("^export/(?P<form_id>\d+)/$",
                self.admin_site.admin_view(self.export_view),
                name="forms_form_export"),
            url("^file/(?P<field_entry_id>\d+)/$",
                self.admin_site.admin_view(self.file_view),
                name="forms_form_file"),
        )
        return extra_urls + urls

    def export_view(self, request, form_id):
        """
        Output a CSV file to the browser containing the entries for the form.
        """
        form = get_object_or_404(Form, id=form_id)
        response = HttpResponse(mimetype="text/csv")
        csvname = "%s-%s.csv" % (form.slug, slugify(datetime.now().ctime()))
        response["Content-Disposition"] = "attachment; filename=%s" % csvname
        w = writer(response)

        dt_format = '%Y-%m-%d %H:%M:%S'
        form_fields = [f for f in form.fields.order_by('position') if f.field_function != 'group_subscription']
        columns = [f.position for f in form_fields]

        price_columns = [
            # EntryForm.entry_time verbose name
            unicode(FormEntry._meta.get_field('entry_time').verbose_name),
            'Pricing',
            'Price',
            'Payment Method',
        ]

        # header row
        w.writerow([f.label for f in form_fields] + price_columns)

        # the rest of the rows
        for e in form.entries.order_by('pk'):
            row = [''] * len(columns)
            for f in e.entry_fields():

                # replace value with URL
                if f.get('field') and f['field'].field_type == 'FileField':
                    url = reverse('form_files', args=[f['field_entry'].pk])
                    f['value'] = request.build_absolute_uri(url)

                # insert value into matching column position
                # fields match via position in list
                row[columns.index(f['position'])] = f['value']

            # extra [price] columns -----------------------------
            row.append(e.entry_time.strftime(dt_format))

            if e.pricing:
                row.append(e.pricing.label)
                row.append(e.pricing.price)
            else:
                row.append('')
                row.append('')

            row.append(e.payment_method)
            # ---------------------------------------------------

            w.writerow(row)

        return response

    def file_view(self, request, field_entry_id):
        """
        Output the file for the requested field entry.
        """
        field_entry = get_object_or_404(FieldEntry, id=field_entry_id)
        path = join(fs.location, field_entry.value)
        response = HttpResponse(mimetype=guess_type(path)[0])
        f = open(path, "r+b")
        response["Content-Disposition"] = "attachment; filename=%s" % f.name
        response.write(f.read())
        f.close()
        return response

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            instance.object_id = instance.form.pk
            instance.save()

admin.site.register(Form, FormAdmin)
