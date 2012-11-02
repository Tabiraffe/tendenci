import sys
from uuid import uuid4
from captcha.fields import CaptchaField
from os.path import join
from datetime import datetime
from hashlib import md5
from haystack.query import SearchQuerySet
from tinymce.widgets import TinyMCE

from django.conf import settings
from django.contrib.auth.models import User, AnonymousUser
from django.forms.fields import CharField, ChoiceField, BooleanField
from django.template.defaultfilters import slugify
from django.forms.widgets import HiddenInput
from django import forms
from django.db.models import Q
from django.utils.translation import ugettext_lazy as _
from django.utils.importlib import import_module
from django.core.files.storage import FileSystemStorage
from django.core.files.storage import default_storage

from tendenci.core.base.fields import SplitDateTimeField
from tendenci.addons.corporate_memberships.models import (CorporateMembership,
    AuthorizedDomain)
from tendenci.apps.user_groups.models import Group
from tendenci.core.perms.forms import TendenciBaseForm
from tendenci.addons.memberships.models import (Membership, MembershipDefault, MembershipType,
    Notice, App, AppEntry, AppField, AppFieldEntry, MembershipImport)
from tendenci.addons.memberships.fields import (TypeExpMethodField, PriceInput,
    NoticeTimeTypeField)
from tendenci.addons.memberships.settings import FIELD_MAX_LENGTH, UPLOAD_ROOT
from tendenci.addons.memberships.utils import csv_to_dict, NoMembershipTypes
from tendenci.addons.memberships.widgets import (CustomRadioSelect, TypeExpMethodWidget,
    NoticeTimeTypeWidget)
from tendenci.addons.memberships.utils import get_notice_token_help_text
from tendenci.apps.notifications.utils import send_welcome_email
from tendenci.addons.educations.models import Education
from tendenci.addons.careers.models import Career
from tendenci.apps.entities.models import Entity


fs = FileSystemStorage(location=UPLOAD_ROOT)

type_exp_method_fields = (
    'period_type', 'period', 'period_unit', 'rolling_option',
    'rolling_option1_day', 'rolling_renew_option', 'rolling_renew_option1_day',
    'rolling_renew_option2_day', 'fixed_option','fixed_option1_day',
    'fixed_option1_month', 'fixed_option1_year', 'fixed_option2_day',
    'fixed_option2_month', 'fixed_option2_can_rollover',
    'fixed_option2_rollover_days'
)

type_exp_method_widgets = (
    forms.Select(),
    forms.TextInput(),
    forms.Select(),
    CustomRadioSelect(),
    forms.TextInput(),
    CustomRadioSelect(),
    forms.TextInput(),
    forms.TextInput(),
    CustomRadioSelect(),
    forms.Select(),
    forms.Select(),
    forms.Select(),
    forms.Select(),
    forms.Select(),
    forms.CheckboxInput(),
    forms.TextInput(),
)

CLASS_AND_WIDGET = {
    'text': ('CharField', None),
    'paragraph-text': ('CharField', 'django.forms.Textarea'),
    'check-box': ('BooleanField', None),
    'choose-from-list': ('ChoiceField', None),
    'multi-select': ('MultipleChoiceField', 'django.forms.CheckboxSelectMultiple'),
    'email-field': ('EmailField', None),
    'file-uploader': ('FileField', None),
    'date': ('DateField', 'django.forms.extras.SelectDateWidget'),
    'date-time': ('DateTimeField', None),
    'membership-type': ('ChoiceField', 'django.forms.RadioSelect'),
    'payment-method': ('ChoiceField', None),
    'first-name': ('CharField', None),
    'last-name': ('CharField', None),
    'email': ('EmailField', None),
    'header': ('CharField', 'tendenci.addons.memberships.widgets.Header'),
    'description': ('CharField', 'tendenci.addons.memberships.widgets.Description'),
    'horizontal-rule': ('CharField', 'tendenci.addons.memberships.widgets.Description'),
    'corporate_membership_id': ('ChoiceField', None),
}

def get_suggestions(entry):
    """
        Generate list of suggestions [people]
        Use the authenticated user that filled out the application
        Use the fn, ln, em mentioned within the application
    """
    user_set = {}

    if entry.user:
        auth_fn = entry.user.first_name
        auth_ln = entry.user.last_name
        auth_un = entry.user.username
        auth_em = entry.user.email
        user_set[entry.user.pk] = '%s %s %s %s' % (auth_fn, auth_ln, auth_un, auth_em)

    if entry.first_name and entry.last_name:
        mentioned_fn = entry.first_name
        mentioned_ln = entry.last_name
        mentioned_em = entry.email
    else:
        mentioned_fn, mentioned_ln, mentioned_em = None, None, None

    sqs = SearchQuerySet()

#    full_name_q = Q(content='%s %s' % (mentioned_fn, mentioned_ln))
    email_q = Q(content=mentioned_em)
#    q = reduce(operator.or_, [full_name_q, email_q])
    sqs = sqs.filter(email_q)

    sqs_users = [sq.object.user for sq in sqs]

    for u in sqs_users:
        user_set[u.pk] = '%s %s %s %s' % (u.first_name, u.last_name, u.username, u.email)

    user_set[0] = 'Create new user'

    return user_set.items()


class MemberApproveForm(forms.Form):

    users = forms.ChoiceField(
        label='Connect this membership with',
        choices=[],
        widget=forms.RadioSelect,
        )

    def get_suggestions(self, entry):
        """
            Generate list of suggestions [people]
            Use the authenticated user that filled out the application
            Use the fn, ln, em mentioned within the application
        """
        user_set = {}

        if entry.user:
            auth_fn = entry.user.first_name
            auth_ln = entry.user.last_name
            auth_un = entry.user.username
            auth_em = entry.user.email
            user_set[entry.user.pk] = '%s %s %s %s' % (auth_fn, auth_ln, auth_un, auth_em)

        if entry.first_name and entry.last_name:
            mentioned_fn = entry.first_name
            mentioned_ln = entry.last_name
            mentioned_em = entry.email
        else:
            mentioned_fn, mentioned_ln, mentioned_em = None, None, None

        sqs = SearchQuerySet()

        if mentioned_em:
            email_q = Q(content=mentioned_em)
            sqs = sqs.filter(email_q)
            sqs_users = [sq.object.user for sq in sqs]
        else:
            sqs_users = []

        for u in sqs_users:
            user_set[u.pk] = '%s %s %s %s' % (u.first_name, u.last_name, u.username, u.email)
            self.fields['users'].initial = u.pk

        user_set[0] = 'Create new user'

        return user_set.items()

    def __init__(self, entry, *args, **kwargs):
        super(MemberApproveForm, self).__init__(*args, **kwargs)
        suggested_users = []
        self.entry = entry

        suggested_users = entry.suggested_users(email=entry.email)
        suggested_users.append((0, 'Create new user'))
        self.fields['users'].choices = suggested_users
        self.fields['users'].initial = 0

        if self.entry.is_renewal:
            self.fields['users'] = CharField(
                label='',
                initial=entry.user.pk,
                widget=HiddenInput
            )


class MembershipTypeForm(forms.ModelForm):
    type_exp_method = TypeExpMethodField(label='Period Type')
    description = forms.CharField(label=_('Notes'), max_length=500, required=False,
                               widget=forms.Textarea(attrs={'rows':'3'}))
    price = forms.DecimalField(decimal_places=2, widget=PriceInput(), 
                               help_text="Set 0 for free membership.")
    renewal_price = forms.DecimalField(decimal_places=2, widget=PriceInput(), required=False, 
                               help_text="Set 0 for free membership.")
    admin_fee = forms.DecimalField(decimal_places=2, required=False,
                                   widget=PriceInput(),
                                   help_text="Admin fee for the first time processing")
    status_detail = forms.ChoiceField(
        choices=(('active', 'Active'), ('inactive', 'Inactive'))
    )

    class Meta:
        model = MembershipType
        fields = (
                  #'app',
                  'name',
                  'price',
                  'admin_fee',
                  'description',
                  #'group',
                  #'period_type',
                  'type_exp_method',
                  'renewal_price',
                  'allow_renewal',
                  'renewal',
                  'never_expires',
                  #'c_period',
                  #'c_expiration_method',
                  #'corporate_membership_only',
                  #'corporate_membership_type_id',
                  'require_approval',
                  'admin_only',
                  'renewal_require_approval',
                  'renewal_period_start',
                  'renewal_period_end',
                  'expiration_grace_period',
                  'order',
                  'status',
                  'status_detail',
                  )

    def __init__(self, *args, **kwargs): 
        super(MembershipTypeForm, self).__init__(*args, **kwargs)
        
        self.type_exp_method_fields = type_exp_method_fields
        
        initial_list = []
        if self.instance.pk:
            for field in self.type_exp_method_fields:
                field_value = getattr(self.instance, field)
                if field == 'fixed_option2_can_rollover' and (not field_value):
                    field_value = ''
                else:
                    if not field_value:
                        field_value = ''
                initial_list.append(str(field_value))
            self.fields['type_exp_method'].initial = ','.join(initial_list)
  
        else:
            self.fields['type_exp_method'].initial = "rolling,1,years,0,1,0,1,1,0,1,1,,1,1,,1"
        
        # a field position dictionary - so we can retrieve data later
        fields_pos_d = {}
        for i, field in enumerate(self.type_exp_method_fields):   
            fields_pos_d[field] = (i, type_exp_method_widgets[i])
        
        self.fields['type_exp_method'].widget = TypeExpMethodWidget(attrs={'id':'type_exp_method'},
                                                                    fields_pos_d=fields_pos_d) 
        
    def clean_type_exp_method(self):
        value = self.cleaned_data['type_exp_method']
        
        # if never expires is checked, no need to check further
        if self.cleaned_data['never_expires']:
            return value
        
        data_list = value.split(',')
        d = dict(zip(self.type_exp_method_fields, data_list))
        if d['period_type'] == 'rolling':
            if d['period']:
                try:
                    d['period'] = int(d['period'])
                except:
                    raise forms.ValidationError(_("Period must be a numeric number."))
            else:
                raise forms.ValidationError(_("Period is a required field."))
            try:
                d['rolling_option'] = int(d['rolling_option'])
            except:
                raise forms.ValidationError(_("Please select a expiration option for join."))
            if d['rolling_option'] not in [0, 1]:
                raise forms.ValidationError(_("Please select a expiration option for join."))
            if d['rolling_option'] == 1:
                try:
                    d['rolling_option1_day'] = int(d['rolling_option1_day'])
                except:
                    raise forms.ValidationError(_("The day(s) field in option 2 of Expires On must be a numeric number."))
            # renew expiration
            try:
                d['rolling_renew_option'] = int(d['rolling_renew_option'])
            except:
                raise forms.ValidationError(_("Please select a expiration option for renewal."))
            if d['rolling_renew_option'] not in [0, 1, 2]:
                raise forms.ValidationError(_("Please select a expiration option for renewal."))
            if d['rolling_renew_option'] == 1:
                try:
                    d['rolling_renew_option1_day'] = int(d['rolling_renew_option1_day'])
                except:
                    raise forms.ValidationError(_("The day(s) field in option 2 of Renew Expires On must be a numeric number."))
            if d['rolling_renew_option'] == 2:
                try:
                    d['rolling_renew_option2_day'] = int(d['rolling_renew_option2_day'])
                except:
                    raise forms.ValidationError(_("The day(s) field in option 3 of Renew Expires On must be a numeric number."))
        
        else: # d['period_type'] == 'fixed'
            try:
                d['fixed_option'] = int(d['fixed_option'])
            except:
                raise forms.ValidationError(_("Please select an option for fixed period."))
            if d['fixed_option'] not in [0, 1]:
                raise forms.ValidationError(_("Please select an option for fixed period."))
            if d['fixed_option'] == 0:
                try:
                    d['fixed_option1_day'] = int(d['fixed_option1_day'])
                except:
                    raise forms.ValidationError(_("The day(s) field in the option 1 of Expires On must be a numeric number."))
            if d['fixed_option'] == 1:
                try:
                    d['fixed_option2_day'] = int(d['fixed_option2_day'])
                except:
                    raise forms.ValidationError(_("The day(s) field in the option 2 of Expires On must be a numeric number."))
                
            if d.has_key('fixed_option2_can_rollover') and d['fixed_option2_can_rollover']:
                try:
                    d['fixed_option2_rollover_days'] = int(d['fixed_option2_rollover_days'])
                except:
                    raise forms.ValidationError(_("The grace period day(s) for optoin 2 must be a numeric number."))
        
        return value
    
    def save(self, *args, **kwargs):
        return super(MembershipTypeForm, self).save(*args, **kwargs)


class MembershipDefaultUploadForm(forms.ModelForm):
    interactive = forms.HiddenInput()

    class Meta:
        model = MembershipImport
        fields = (
                'key',
                'override',
                'interactive',
                'upload_file',
                  )

    def __init__(self, *args, **kwargs): 
        super(MembershipDefaultUploadForm, self).__init__(*args, **kwargs)
        self.fields['interactive'].initial = 1
        self.fields['interactive'].widget = forms.HiddenInput()

    def clean_upload_file(self):
        key = self.cleaned_data['key']
        upload_file = self.cleaned_data['upload_file']
        if not key:
            raise forms.ValidationError('Please specify the key to identify duplicates')

        file_content = upload_file.read()
        upload_file.seek(0)
        header_line_index = file_content.find('\n')
        header_list = ((file_content[:header_line_index]
                            ).strip('\r')).split(',')
        key_list = key.split(',')
        for item in key_list:
            if not item in header_list:
                raise forms.ValidationError(
                            """
                            'Field "%s" used to identify the duplicates 
                            should be included in the .csv file.'
                            """ % item)

        return upload_file


class NoticeForm(forms.ModelForm):
    notice_time_type = NoticeTimeTypeField(label='When to Send',
                                          widget=NoticeTimeTypeWidget)
    email_content = forms.CharField(widget=TinyMCE(attrs={'style':'width:70%'}, 
        mce_attrs={'storme_app_label':Notice._meta.app_label, 
        'storme_model':Notice._meta.module_name.lower()}), help_text="Click here to view available tokens")    
    class Meta:
        model = Notice
        fields = (
                  'notice_name',
                  'notice_time_type',
                  'membership_type',
                  'subject',
                  'content_type',
                  'sender',
                  'sender_display',
                  'email_content',
                  'status',
                  'status_detail',
                  )

    def __init__(self, *args, **kwargs): 
        super(NoticeForm, self).__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['email_content'].widget.mce_attrs['app_instance_id'] = self.instance.pk
        else:
            self.fields['email_content'].widget.mce_attrs['app_instance_id'] = 0
        
        initial_list = []
        if self.instance.pk:
            initial_list.append(str(self.instance.num_days))
            initial_list.append(str(self.instance.notice_time))
            initial_list.append(str(self.instance.notice_type))
        
        self.fields['notice_time_type'].initial = initial_list
        
        self.fields['email_content'].help_text = get_notice_token_help_text(self.instance)
        
    def clean_notice_time_type(self):
        value = self.cleaned_data['notice_time_type']
        
        data_list = value.split(',')
        d = dict(zip(['num_days', 'notice_time', 'notice_type'], data_list))
        
        try:
            d['num_days'] = int(d['num_days'])
        except:
            raise forms.ValidationError(_("Num days must be a numeric number."))
        return value
            
    
class AppCorpPreForm(forms.Form):
    corporate_membership_id = forms.ChoiceField(label=_('Join Under the Corporation:'))
    secret_code = forms.CharField(label=_('Enter the Secret Code'), max_length=50)
    email = forms.EmailField(label=_('Verify Your Email Address'), max_length=100,
                             help_text="""Your email address will help us to identify your corporate.
                                         You will receive an email to the address you entered for us
                                         to verify your email address. 
                                         Please follow the instruction
                                         in the email to continue signing up for the membership.
                                          """)
    
    def __init__(self, *args, **kwargs):
        super(AppCorpPreForm, self).__init__(*args, **kwargs)
        self.auth_method = ''
        self.corporate_membership_id = 0
    
    def clean_secret_code(self):
        secret_code = self.cleaned_data['secret_code']
        corporate_memberships = CorporateMembership.objects.filter(secret_code=secret_code, 
                                                                   status=1,
                                                                   status_detail='active')
        if not corporate_memberships:
            raise forms.ValidationError(_("Invalid Secret Code."))
        
        self.corporate_membership_id = corporate_memberships[0].id
        return secret_code
        
    def clean_email(self):
        email = self.cleaned_data['email']
        if email:
            email_domain = (email.split('@')[1]).strip()
            auth_domains = AuthorizedDomain.objects.filter(name=email_domain)
            if not auth_domains:
                raise forms.ValidationError(_("Sorry but we're not able to find your corporation."))
            self.corporate_membership_id = auth_domains[0].corporate_membership.id 
        return email 

class AppForm(TendenciBaseForm):

    description = forms.CharField(required=False,
        widget=TinyMCE(attrs={'style':'width:100%'}, 
        mce_attrs={'storme_app_label':App._meta.app_label, 
        'storme_model':App._meta.module_name.lower()}))

    confirmation_text = forms.CharField(required=False,
        widget=TinyMCE(attrs={'style':'width:100%'}, 
        mce_attrs={'storme_app_label':App._meta.app_label, 
        'storme_model':App._meta.module_name.lower()}))

    status_detail = forms.ChoiceField(
        choices=(
            ('draft', 'Draft'),
            ('published', 'Published')
        ),
        initial='published'
    )

    class Meta:
        model = App
        fields = (
            'name',
            'slug',
            'description',
            'confirmation_text',
            'notes',
            'membership_types',
            'payment_methods',
            'use_for_corp',
            'use_captcha',
            'allow_anonymous_view',
            'user_perms',
            'member_perms',
            'group_perms',
            'status_detail', 
            )

    def __init__(self, *args, **kwargs): 
        super(AppForm, self).__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['description'].widget.mce_attrs['app_instance_id'] = self.instance.pk
        else:
            self.fields['description'].widget.mce_attrs['app_instance_id'] = 0

        if self.instance.pk:
            self.fields['confirmation_text'].widget.mce_attrs['app_instance_id'] = self.instance.pk
        else:
            self.fields['confirmation_text'].widget.mce_attrs['app_instance_id'] = 0


class AppFieldForm(forms.ModelForm):
    class Meta:
        model = AppField

    def __init__(self, *args, **kwargs):
        super(AppFieldForm, self).__init__(*args, **kwargs)

        # remove "admin only" option from membership type and payment method
        if self.instance.field_type in ['membership-type','payment-method']:
            self.fields['admin_only'] = BooleanField(widget=HiddenInput, required=False)

        # remove field_type options
        choices_dict = dict(self.fields['field_type'].choices)
        del choices_dict['membership-type']
        del choices_dict['payment-method']
        self.fields['field_type'].choices = choices_dict.items()

        # use hidden widget for membership-type
        if self.instance.field_type == 'membership-type':
            self.fields['field_type'] = CharField(label="Type", widget=HiddenInput)

        # user hidden widget for payment-method
        if self.instance.field_type == 'payment-method':
            self.fields['field_type'] = CharField(label="Type", widget=HiddenInput)
            
    
    def clean_function_params(self):
        function_params = self.cleaned_data['function_params']
        clean_params = ''
        for val in function_params.split(','):
            clean_params = val.strip() + ',' + clean_params
        return clean_params[0:len(clean_params)-1]
        
    def clean(self):
        cleaned_data = self.cleaned_data
        field_function = cleaned_data.get("field_function")
        function_params = cleaned_data.get("function_params")
        field_type = cleaned_data.get("field_type")
        
        if field_function == "Group":
            if field_type != "check-box":
                raise forms.ValidationError("This field's function requires Checkbox as a field type")
            if not function_params:
                raise forms.ValidationError("This field's function requires at least 1 group specified.")
            else:
                for val in function_params.split(','):
                    try:
                        Group.objects.get(name=val)
                    except Group.DoesNotExist:
                        raise forms.ValidationError("The group \"%s\" does not exist" % (val))
        
        return cleaned_data



class EntryEditForm(TendenciBaseForm):
    STATUS_CHOICES = (
        ('active','Active'),
        ('inactive','Inactive'),
    )
    
    SALUTATION_CHOICES = (
        ('Mr.', 'Mr.'),
        ('Mrs.', 'Mrs.'),
        ('Ms.', 'Ms.'),
        ('Miss', 'Miss'),
        ('Dr.', 'Dr.'),
        ('Prof.', 'Prof.'),
        ('Hon.', 'Hon.'),
    )
    SEX_CHOICES = (
        ('male', u'Male'),
        ('female', u'Female'),
    )
    
    salutation = forms.ChoiceField(choices=SALUTATION_CHOICES, required=False)
    first_name = forms.CharField(required=False)
    last_name = forms.CharField(required=False)
    initials = forms.CharField(required=False)
    member_number = forms.CharField(required=False)
    language = forms.ChoiceField(choices=settings.LANGUAGES, initial=settings.LANGUAGE_CODE)
    company = forms.CharField(required=False)
    position_title = forms.CharField(required=False)
    position_assignment = forms.CharField(required=False)
    mailing_name = forms.CharField(required=False)
    address_type = forms.CharField(required=False)
    address = forms.CharField(required=False)
    address2 = forms.CharField(required=False)
    city = forms.CharField(required=False)
    state = forms.CharField(required=False)
    zipcode = forms.CharField(required=False)
    country = forms.CharField(required=False)
    county = forms.CharField(required=False)
    phone = forms.CharField(required=False)
    phone2 = forms.CharField(required=False)
    fax = forms.CharField(required=False)
    work_phone = forms.CharField(required=False)
    home_phone = forms.CharField(required=False)
    mobile_phone = forms.CharField(required=False)
    email = forms.EmailField(required=False)
    email2 = forms.EmailField(required=False)
    url = forms.CharField(required=False)
    url2 = forms.CharField(required=False)
    spouse = forms.CharField(required=False)
    department = forms.CharField(required=False)
    education = forms.CharField(required=False)
    student = forms.IntegerField(required=False)
    notes = forms.CharField(required=False)
    admin_notes = forms.CharField(required=False)
    referral_source = forms.CharField(required=False)
    
    status_detail = forms.ChoiceField(choices=STATUS_CHOICES)
    
    class Meta:
        model = AppEntry
        fields = (
            'is_renewal',
            'is_approved',
            'entry_time',
            'decision_dt',
            'judge',
            'user_perms',
            'member_perms',
            'group_perms',
            'status',
            'status_detail',
        )

        fieldsets = [
            ('Membership Details', {
                'fields': [
                    'is_renewal',
                    'is_approved',
                    'entry_time',
                    'decision_dt',
                    'judge',
                    # profile fields
                    'salutation',
                    'first_name',
                    'last_name',
                    'initials',
                    'member_number',
                    'language',
                    'company',
                    'position_title',
                    'position_assignment',
                    'mailing_name',
                    'address_type',
                    'address',
                    'address2',
                    'city',
                    'state',
                    'zipcode',
                    'country',
                    'county',
                    'phone',
                    'phone2',
                    'fax',
                    'work_phone',
                    'home_phone',
                    'mobile_phone',
                    'email',
                    'email2',
                    'url',
                    'url2',
                    'spouse',
                    'department',
                    'education',
                    'student',
                    'notes',
                    'admin_notes',
                    'referral_source',
                ],
                'legend': ''
            }),
            ('Permissions', {
                'fields': [
                    'allow_anonymous_view',
                    'user_perms',
                    'member_perms',
                    'group_perms',
                ],
                'classes': ['permissions'],
            }),
            ('Administrator Only', {
                'fields': [
                    'status',
                    'status_detail'], 
                'classes': ['admin-only'],
            })]

    def __init__(self, *args, **kwargs):
        super(EntryEditForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        entry_fields = AppFieldEntry.objects.filter(entry=instance)

        is_corporate = instance.membership_type and \
            instance.membership_type.corporatemembershiptype_set.exists()
            
        for entry_field in entry_fields:
            field_type = entry_field.field.field_type  # shorten
            field_key = "%s.%s" % (entry_field.field.field_type, entry_field.pk)

            field_class, field_widget = CLASS_AND_WIDGET[field_type]
            field_class = getattr(forms, field_class)

            arg_names = field_class.__init__.im_func.func_code.co_varnames
            field_args = {}

            field_args['label'] = entry_field.field.label
            field_args['initial'] = entry_field.value
            field_args['required'] = False

            if "max_length" in arg_names:
                field_args["max_length"] = FIELD_MAX_LENGTH

            if "choices" in arg_names:

                if field_type == 'membership-type':
                    choices = [t.name for t in instance.app.membership_types.all()]
                    choices_with_price = ['%s $%s' % (t.name, t.price) for t in instance.app.membership_types.all()]
                    field_args["choices"] = zip(choices, choices_with_price)

                    if is_corporate:  # membership type; read-only
                        del field_args["choices"]
                        field_class = getattr(forms, 'CharField') 
                        field_args["widget"] = forms.TextInput(attrs={'readonly':'readonly'})

                elif field_type == 'corporate_membership_id':
                    choices = [c.name for c in CorporateMembership.objects.all()]
                    field_args["choices"] = zip(choices, choices)
                else:
                    choices = entry_field.field.choices.split(',')
                    choices = [c.strip() for c in choices]
                    field_args["choices"] = zip(choices, choices)

            self.fields[field_key] = field_class(**field_args)
        
        # profile
        if self.instance:
            profile = self.instance.user.profile
            self.fields['salutation'].initial = profile.salutation
            self.fields['first_name'].initial = profile.user.first_name
            self.fields['last_name'].initial = profile.user.last_name
            self.fields['initials'].initial = profile.initials
            self.fields['member_number'].initial = profile.member_number
            self.fields['language'].initial = profile.language
            self.fields['company'].initial = profile.company
            self.fields['position_title'].initial = profile.position_title
            self.fields['position_assignment'].initial = profile.position_assignment
            self.fields['mailing_name'].initial = profile.mailing_name
            self.fields['address_type'].initial = profile.address_type
            self.fields['address'].initial = profile.address
            self.fields['address2'].initial = profile.address2
            self.fields['city'].initial = profile.city
            self.fields['state'].initial = profile.state
            self.fields['zipcode'].initial = profile.zipcode
            self.fields['country'].initial = profile.country
            self.fields['county'].initial = profile.county
            self.fields['phone'].initial = profile.phone
            self.fields['phone2'].initial = profile.phone2
            self.fields['fax'].initial = profile.fax
            self.fields['work_phone'].initial = profile.work_phone
            self.fields['home_phone'].initial = profile.home_phone
            self.fields['mobile_phone'].initial = profile.mobile_phone
            self.fields['email'].initial = profile.user.email
            self.fields['email2'].initial = profile.email2
            self.fields['url'].initial = profile.url
            self.fields['url2'].initial = profile.url2
            self.fields['spouse'].initial = profile.spouse
            self.fields['department'].initial = profile.department
            self.fields['education'].initial = profile.education
            self.fields['student'].initial = profile.student
            self.fields['notes'].initial = profile.notes
            self.fields['admin_notes'].initial = profile.admin_notes
            self.fields['referral_source'].initial = profile.referral_source
            profile.save()

    def save(self, *args, **kwargs):
        super(EntryEditForm, self).save(*args, **kwargs)
        
        membership_type = None
        for key, value in self.cleaned_data.items():
            if len(key.split('.')) > 1:
                pk = key.split('.')[1]
                membership_type = None
                membership_type_entry_pk = 0
                
                if 'corporate_membership' in key:
                    corp_memb = CorporateMembership.objects.get(name=value)  # get corp. via name
                    membership_type = corp_memb.corporate_membership_type.membership_type

                if 'membership-type' in key:
                    membership_type_entry_pk = pk

                AppFieldEntry.objects.filter(pk=pk).update(value=value)

                # update membership entry_field
                if membership_type and membership_type_entry_pk:
                    AppFieldEntry.objects.filter(pk=membership_type_entry_pk).update(value=membership_type.name)

        # update membership.membership_type relationship
        if self.instance.membership and membership_type:
            self.instance.membership.membership_type = membership_type
            self.instance.save()
            
        # update profile
        if self.instance:
            data = self.cleaned_data
            profile = self.instance.user.profile
            profile.salutation = data['salutation']
            profile.user.first_name = data['first_name']
            profile.user.last_name = data['last_name']
            profile.initials = data['initials']
            #profile.sex = data['sex']
            profile.member_number = data['member_number']
            profile.language = data['language']
            profile.company = data['company']
            profile.position_title = data['position_title']
            profile.position_assignment = data['position_assignment']
            profile.mailing_name = data['mailing_name']
            profile.address_type = data['address_type']
            profile.address = data['address']
            profile.address2 = data['address2']
            profile.city = data['city']
            profile.state = data['state']
            profile.zipcode = data['zipcode']
            profile.country = data['country']
            profile.county = data['county']
            profile.phone = data['phone']
            profile.phone2 = data['phone2']
            profile.fax = data['fax']
            profile.work_phone = data['work_phone']
            profile.home_phone = data['home_phone']
            profile.mobile_phone = data['mobile_phone']
            profile.user.email = data['email']
            profile.email2 = data['email2']
            profile.url = data['url']
            profile.url2 = data['url2']
            #profile.dob = data['dob']
            #profile.ssn = data['ssn']
            profile.spouse = data['spouse']
            profile.department = data['department']
            profile.education = data['education']
            profile.student = data['student']
            profile.notes = data['notes']
            profile.admin_notes = data['admin_notes']
            profile.referral_source = data['referral_source']
            profile.user.save()
            profile.save()

        return self.instance

class AppEntryForm(forms.ModelForm):

    class Meta:
        model = AppEntry
        exclude = (
            'hash',
            'entry_time',
            'allow_anonymous_view',
            'allow_user_view',
            'allow_user_edit',
            'allow_member_view',
            'allow_member_edit',
            'creator_username',
            'owner',
            'owner_username',
            'status',
            'status_detail',
            'app',
            'user',
            'membership',
            'is_renewal',
            'is_approved',
            'decision_dt',
            'judge',
            'invoice',
            'entity',
        )

    def __init__(self, app=None, *args, **kwargs):
        """
        Dynamically add each of the form fields for the given form model 
        instance and its related field model instances.
        """

        self.app = app
        
        self.types_field = app.membership_types
        self.user = kwargs.pop('user', None) or AnonymousUser
        self.corporate_membership = kwargs.pop('corporate_membership', None) # id; not object

        super(AppEntryForm, self).__init__(*args, **kwargs)

        if self.user.profile.is_superuser:
            self.form_fields = app.fields.visible()
            exclude_types = []
        else:
            self.form_fields = app.fields.non_admin_visible()
            # exclude membership types you are in contract with [not within renewal period]
            exclude_types = Membership.types_in_contract(self.user)
            # exclude membership types that are marked as admin only for non-superusers
            admin_only = MembershipType.objects.filter(admin_only=True)
            for type in admin_only:
                exclude_types.append(type)
            exclude_types = [t.pk for t in exclude_types]  # only pks

        CLASS_AND_WIDGET = {
            'text': ('CharField', None),
            'paragraph-text': ('CharField', 'django.forms.Textarea'),
            'check-box': ('BooleanField', None),
            'choose-from-list': ('ChoiceField', None),
            'multi-select': ('MultipleChoiceField', 'django.forms.CheckboxSelectMultiple'),
            'email-field': ('EmailField', None),
            'file-uploader': ('FileField', None),
            'date': ('DateField', 'django.forms.extras.SelectDateWidget'),
            'date-time': ('DateTimeField', None),
            'membership-type': ('ChoiceField', 'django.forms.RadioSelect'),
            'payment-method': ('ChoiceField', None),
            'first-name': ('CharField', None),
            'last-name': ('CharField', None),
            'email': ('EmailField', None),
            'header': ('CharField', 'tendenci.addons.memberships.widgets.Header'),
            'description': ('CharField', 'tendenci.addons.memberships.widgets.Description'),
            'horizontal-rule': ('CharField', 'tendenci.addons.memberships.widgets.Description'),
            'corporate_membership_id': ('ChoiceField', None),
        }

        for field in self.form_fields:

            if field.field_type == 'corporate_membership_id' and not self.corporate_membership:
                continue  # on to the next one

            field_key = "field_%s" % field.id
            field_class, field_widget = CLASS_AND_WIDGET[field.field_type]
            field_class = getattr(forms, field_class)
            field_args = {"label": field.label, "required": field.required}
            arg_names = field_class.__init__.im_func.func_code.co_varnames

            if "max_length" in arg_names:
                field_args["max_length"] = FIELD_MAX_LENGTH

            if "choices" in arg_names:
                if field.field_type == 'membership-type':

                    if self.corporate_membership:
                        membership_type = self.corporate_membership.corporate_membership_type.membership_type 
                        choices = [membership_type.name]
                        choices_with_price = ['%s $%s' % (membership_type.name, membership_type.price)]
                        if membership_type.admin_fee:
                            choices_with_price = ['%s $%s ($%s admin fee)' % (membership_type.name, membership_type.price, membership_type.admin_fee)]
                        field_args["choices"] = zip(choices, choices_with_price)
                    else:
                        choices = [type.name for type in app.membership_types.exclude(pk__in=exclude_types)]
                        choices_with_price = []
                        for type in app.membership_types.exclude(pk__in=exclude_types):
                            if type.admin_fee:
                                type_label = '%s $%s ($%s admin fee)' % (type.name, type.price, type.admin_fee)
                            else:
                                type_label = '%s $%s' % (type.name, type.price)
                            choices_with_price.append(type_label)
                        field_args["choices"] = zip(choices, choices_with_price)

                        if not self.user.profile.is_superuser:
                            if not field_args['choices']:
                                raise NoMembershipTypes('There are no membership types available for you in this application.')

                elif field.field_type == 'corporate_membership_id' and self.corporate_membership:
                    field_args["choices"] = ((self.corporate_membership.id, self.corporate_membership.name),)
                else:
                    choices = field.choices.split(",")
                    choices = [c.strip() for c in choices]
                    field_args["choices"] = zip(choices, choices)

            if field.field_type == 'corporate_membership_id' and self.corporate_membership:
                pass
            else:
                field_args['initial'] = field.default_value
            field_args['help_text'] = field.help_text

            if field.pk in kwargs['initial']:
                field_args['initial'] = kwargs['initial'][field.pk]

            if field_widget is not None:
                module, widget = field_widget.rsplit(".", 1)
                field_args["widget"] = getattr(import_module(module), widget)

            self.fields[field_key] = field_class(**field_args)
            self.fields[field_key].css_classes = ' %s' % field.css_class

            if field.field_type == 'date':
                year = datetime.today().year
                self.fields[field_key].widget.years = range(year-120, year+120)

        if app.use_captcha and not self.user.is_authenticated():
            self.fields['field_captcha'] = CaptchaField(**{
                'label':'',
                'error_messages':{'required':'CAPTCHA is required'}
            })


    def save(self, **kwargs):
        """
        Create a AppEntry instance and related AppFieldEntry instances for each 
        form field.
        """
        app_entry = super(AppEntryForm, self).save(commit=False)
        app_entry.app = self.app
        
        # TODO: We're assuming that an administrator exists
        # We're assuming this administrator is actively used
        admin = User.objects.order_by('pk')[0]
        
        user = None
        username = None
        if hasattr(self.user, 'pk'):
            user = self.user
            username = user.username
        
        app_entry.user = user
        app_entry.entry_time = datetime.now()
        app_entry.creator = user or admin
        app_entry.creator_username = username or admin.username
        app_entry.owner = user or admin
        app_entry.owner_username = username or admin.username
        app_entry.status = True
        app_entry.status_detail = 'active'
        app_entry.allow_anonymous_view = False
        
        app_entry.save()
        
        app_entry.hash = md5(unicode(app_entry.pk)).hexdigest()
        app_entry.save()
        
        #create all field entries
        for field in self.form_fields:
            if field.field_type == 'corporate_membership_id' and not self.corporate_membership:
                continue
            field_key = "field_%s" % field.id
            value = self.cleaned_data[field_key]
            if value and self.fields[field_key].widget.needs_multipart_form:
                value = fs.save(join("forms", str(uuid4()), value.name), value)
            # if the value is a list convert is to a comma delimited string
            if isinstance(value,list):
                value = ','.join(value)
            if not value: value=''
            app_entry.fields.create(field_id=field.id, value=value)
            
        return app_entry

    def email_to(self):
        """
        Return the value entered for the first field of type EmailField.
        """
        for field in self.form_fields:
            field_class = field.field_type.split("/")[0]
            if field_class == "EmailField":
                return self.cleaned_data["field_%s" % field.id]
        return None

class CSVForm(forms.Form):
    """
    Map CSV import to Membership Application.
    Create Membership Entry on save() method.
    """
    def __init__(self, *args, **kwargs):
        """
        Dynamically create fields using the membership
        application chosen.  The choices provided to these
        dynamic fields are the csv import columns.
        """
        step_numeral, step_name = kwargs.pop('step', (None, None))
        app = kwargs.pop('app', '')
        file_path = kwargs.pop('file_path', '')

        super(CSVForm, self).__init__(*args, **kwargs)

        if step_numeral == 1:
            """
            Basic Form: Application & File Uploader
            """
            
            self.fields['app'] = forms.ModelChoiceField(
                label='Application', queryset=App.objects.all())

            self.fields['csv'] = forms.FileField(label="CSV File")
        
        if step_numeral == 2:
            """
            Basic Form + Mapping Fields
            """

            # file to make field-mapping form
            csv = csv_to_dict(file_path)

            # choices list
            choices = csv[0].keys()

            # make tuples; sort tuples (case-insensitive)
            choice_tuples = [(c,c) for c in csv[0].keys()]

            choice_tuples.insert(0, ('',''))  # insert blank option
            choice_tuples = sorted(choice_tuples, key=lambda c: c[0].lower())

            app_fields = AppField.objects.filter(app=app)

            native_fields = [
                'User Name',
                'Membership Type',
                'Corp. Membership Name',
                'Member Number',
                'Payment Method',
                'Join Date',
                'Renew Date',
                'Expire Date',
                'Owner',
                'Creator',
                'Status',
                'Status Detail',
            ]

            for native_field in native_fields:
                self.fields[slugify(native_field)] = ChoiceField(**{
                    'label': native_field,
                    'choices': choice_tuples,
                    'required': False,
                })

                # compare required field with choices
                # if they match; set initial
                if native_field in choices:
                    self.fields[slugify(native_field)].initial = native_field

            self.fields['user-name'].required = True
            self.fields['membership-type'].required = True

            for app_field in app_fields:
                for csv_row in csv:

                    if slugify(app_field.label) == 'membership-type':
                        continue  # skip membership type

                    self.fields[app_field.label] = ChoiceField(**{
                        'label':app_field.label,
                        'choices': choice_tuples,
                        'required': False,
                    })

                    # compare label with choices
                    # if label matches choice; set initial
                    if app_field.label in choices:
                        self.fields[app_field.label].initial = app_field.label
   


    def save(self, *args, **kwargs):
        """
        Loop through the dynamic fields and create an 
        entry and membership record. Map application, 
        entry, and membership record.

        Checking app.pk, user.pk and entry_time to 
        recognize duplicates.
        """
        step_numeral, step_name = kwargs.pop('step', (None, None))

        if step_numeral == 1:
            """
            Basic Form: Application & File Uploader
            """
            return self.cleaned_data

        if step_numeral == 2:
            """
            Basic Form + Mapping Fields
            """
            pass  # mapping of fields
            return self.cleaned_data

        if step_numeral == 3:
            pass  # end-user is previewing

        if step_numeral == 4:
            memberships = request.session.get('membership.import.memberships')

            for membership in memberships:

                entry = AppEntry.objects.filter(
                    app = app,
                    user = user,
                    entry_time = datetime.now(),
                    membership = membership,
                ).exists()

                if not entry:  # create; if does not exist

                    entry = AppEntry.objects.create(
                        app = app,
                        user = user,
                        entry_time = datetime.now(),
                        membership = membership,
                        is_renewal = membership.renewal,
                        is_approved = True,
                        decision_dt = membership.create_dt,
                        judge = membership.creator,
                        creator=membership.creator,
                        creator_username=membership.creator_username,
                        owner=membership.owner,
                        owner_username=membership.owner_username,
                    )

                    for key, value in self.cleaned_data.items():

                        app_fields = AppField.objects.filter(app=app, label=key)
                        if app_fields:
                            app_field = app_fields[0]
                        else:
                            app_field = None

                        try:
                            AppFieldEntry.objects.create(
                                entry=entry,
                                field=app_field,
                                value=value,
                            )
                        except:
                            print sys.exc_info()[1]


class ExportForm(forms.Form):

    app = forms.ModelChoiceField(
        label=_('Application'), 
        queryset=App.objects.all()
    )

    passcode = forms.CharField(
        label=_("Type Your Password"), 
        widget=forms.PasswordInput(render_value=False)
    )
    
    def __init__(self, *args, **kwargs):
        from tendenci.core.base.http import Http403
        from tendenci.core.site_settings.utils import get_setting
        from tendenci.addons.memberships.models import Membership

        self.user = kwargs.pop('user', None)
        super(ExportForm, self).__init__(*args, **kwargs)

        who_can_export = get_setting('module','memberships','memberexport')

        if not self.user.profile.is_superuser:
            if who_can_export == 'admin-only':
                if not self.user.profile.is_superuser:
                    raise Http403
            elif who_can_export == 'membership-of-same-type':
                if not self.user.profile.is_member:
                    raise Http403
                membership_types = self.user.memberships.values_list('membership_type').distinct()
                self.fields['app'].queryset = App.objects.filter(membership_types__in=membership_types)
            elif who_can_export == 'members':
                if not self.user.profile.is_member:
                    raise Http403
            elif who_can_export == 'users':
                if not self.user.is_authenticated():
                    raise Http403

    def clean_passcode(self):
        value = self.cleaned_data['passcode']
        
        if not self.user.check_password(value):
            raise forms.ValidationError(_("Invalid password."))
        return value

class ReportForm(forms.Form):
    STATUS_CHOICES = (
        ('', '----------'),
        ('ACTIVE', 'ACTIVE'),
        ('EXPIRED', 'EXPIRED'),
    )
    
    membership_type = forms.ModelChoiceField(queryset = MembershipType.objects.all(), required = False)
    membership_status = forms.ChoiceField(choices = STATUS_CHOICES, required = False)


class MembershipDefaultForm(TendenciBaseForm):
    """
    Bound to the MembershipDefault model
    """

    salutation = forms.CharField(required=False)
    first_name = forms.CharField(initial=u'')
    last_name = forms.CharField(initial=u'')
    email = forms.CharField(initial=u'')
    email2 = forms.CharField(initial=u'', required=False)
    display_name = forms.CharField(initial=u'', required=False)
    company = forms.CharField(initial=u'', required=False)
    position_title = forms.CharField(initial=u'', required=False)
    # functional_title = forms.CharField(initial=u'', required=False)
    department = forms.CharField(initial=u'', required=False)
    address = forms.CharField(initial=u'', required=False)
    address2 = forms.CharField(initial=u'', required=False)
    address_type = forms.CharField(initial=u'', required=False)
    city = forms.CharField(initial=u'', required=False)
    state = forms.CharField(initial=u'', required=False)
    zipcode = forms.CharField(initial=u'', required=False)
    country = forms.CharField(initial=u'', required=False)
    phone = forms.CharField(initial=u'', required=False)
    phone2 = forms.CharField(initial=u'', required=False)
    work_phone = forms.CharField(initial=u'', required=False)
    home_phone = forms.CharField(initial=u'', required=False)
    mobile_phone = forms.CharField(initial=u'', required=False)
    pager = forms.CharField(initial=u'', required=False)
    fax = forms.CharField(initial=u'', required=False)
    url = forms.CharField(initial=u'', required=False)
    url2 = forms.CharField(initial=u'', required=False)

    hide_in_search = forms.BooleanField(required=False)
    hide_address = forms.BooleanField(required=False)
    hide_email = forms.BooleanField(required=False)
    hide_phone = forms.BooleanField(required=False)

    dob = forms.DateTimeField(required=False)
    education_grad_dt = forms.DateTimeField(required=False)
    career_start_dt = forms.DateTimeField(required=False)
    career_end_dt = forms.DateTimeField(required=False)

    sex = forms.CharField(initial=u'', required=False)
    spouse = forms.CharField(initial=u'', required=False)
    profession = forms.CharField(initial=u'', required=False)
    custom1 = forms.CharField(initial=u'', required=False)
    custom2 = forms.CharField(initial=u'', required=False)
    custom3 = forms.CharField(initial=u'', required=False)
    custom4 = forms.CharField(initial=u'', required=False)

    username = forms.CharField(initial=u'', required=False)
    password = forms.CharField(initial=u'', widget=forms.PasswordInput, required=False)

    same_as_primary = forms.BooleanField(required=False)
    extra_address = forms.CharField(initial=u'', required=False)
    extra_address2 = forms.CharField(initial=u'', required=False)
    extra_city = forms.CharField(initial=u'', required=False)
    extra_state = forms.CharField(initial=u'', required=False)
    extra_zip_code = forms.CharField(initial=u'', required=False)
    extra_country = forms.CharField(initial=u'', required=False)
    extra_address_type = forms.CharField(initial=u'', required=False)

    class Meta:
        model = MembershipDefault
        fields = (
            'member_number',
            'membership_type',
            'renewal',
            'certifications',
            'work_experience',
            'referral_source',
            'referral_source_other',
            'referral_source_member_name',
            'referral_source_member_number',
            'affiliation_member_number',
            'primary_practice',
            'how_long_in_practice',
            'notes',
            'admin_notes',
            'newsletter_type',
            'directory_type',
            'generate_member_number',
            'application_approved',
            'payment_method',
            'chapter',
            'areas_of_expertise',
            'corporate_membership_id',
            'home_state',
            'year_left_native_country',
            'network_sectors',
            'networking',
            'government_worker',
            'government_agency',
            'license_number',
            'license_state',
            'region',
            'industry',
            'company_size',
            'promotion_code',
            'directory',
            'join_dt',
            'renew_dt',
            'expire_dt',
        )
        widgets = {
            'membership_type': forms.RadioSelect,
            'payment_method': forms.RadioSelect,
            'bod_dt': forms.DateTimeInput(attrs={'class': 'datepicker'}),
            'application_approved_denied_dt': forms.DateTimeInput(
                attrs={'class': 'datepicker'}),
            'application_complete_dt': forms.DateTimeInput(
                attrs={'class': 'datepicker'}),
            'action_taken_dt': forms.DateTimeInput(
                attrs={'class': 'datepicker'}),
            'personnel_notified_dt': forms.DateTimeInput(
                attrs={'class': 'datepicker'}),
            'payment_received_dt': forms.DateTimeInput(
                attrs={'class': 'datepicker'}),
        }

    def __init__(self, *args, **kwargs):
        """
        Setting foreign key fields with temporary objects.
        """
        # request_user = User() or None() object
        request_user = kwargs.pop('request_user', AnonymousUser())
        if not isinstance(request_user, User):
            request_user = None

        super(MembershipDefaultForm, self).__init__(*args, **kwargs)

        # initialize field widgets ---------------------------
        self.fields['payment_method'].empty_label = None
        self.fields['industry'].empty_label = 'Select One'
        self.fields['region'].empty_label = 'Select One'

        if not self.instance.pk:
            self.fields['dob'].widget = forms.DateTimeInput(attrs={'class': 'datepicker'})
            self.fields['education_grad_dt'].widget = forms.DateTimeInput(attrs={'class': 'datepicker'})
            self.fields['career_start_dt'].widget = forms.DateTimeInput(attrs={'class': 'datepicker'})
            self.fields['career_end_dt'].widget = forms.DateTimeInput(attrs={'class': 'datepicker'})

        mts = MembershipType.objects.filter(status=True, status_detail='active')
        mt_values = mts.values_list('pk', 'name', 'price', 'renewal_price', 'admin_fee')

        # TODO: consider global renewal period
        # which result in renewal price
        # TODO: Include admin fee on join price

        mt_choices = []
        for pk, name, price, renewal_price, admin_fee in mt_values:
            price = price or float()
            renewal_price = renewal_price or float()
            admin_fee = admin_fee or float()
            mt_choices.append((pk, '$%s %s' % (price, name)))

        self.fields['membership_type'].choices = mt_choices
        # -----------------------------------------------------

        # change form -----------------------------------------
        if self.instance.pk:

            user_attrs = [
                'first_name',
                'last_name',
                'email',
            ]

            profile_attrs = [
                'email2',
                'company',
                'department',
                'position_title',
                # 'functional_title',
                'address',
                'address2',
                'address_type',
                'city',
                'state',
                'zipcode',
                'country',
                'phone',
                'phone2',
                'work_phone',
                'home_phone',
                'mobile_phone',
                # 'pager',
                'fax',
                'url',
                'url2',
                'dob',
                'sex',
                'spouse',
                # 'profession',
                'hide_in_search',
                'hide_address',
                'hide_email',
                'hide_phone',
            ]

            # initialize user fields
            for user_attr in user_attrs:
                self.fields[user_attr].initial = \
                    getattr(self.instance.user, user_attr)

            # initialize profile fields
            for profile_attr in profile_attrs:
                self.fields[profile_attr].initial = \
                    getattr(self.instance.user.profile, profile_attr)
        # -----------------------------------------------------

    def save(self, *args, **kwargs):
        """
        Create membership record.
        Handle all objects:
            Membership
            Membership.user
            Membership.user.profile
            Membership.invoice
            Membership.user.group_set()
        """
        request = kwargs.pop('request')

        request_user = None
        if hasattr(request, 'user'):
            if isinstance(request.user, User):
                request_user = request.user

        membership = super(MembershipDefaultForm, self).save(*args, **kwargs)

        if request_user:
            membership.creator = request_user
            membership.creator_username = request_user.username
            membership.owner = request_user
            membership.owner_username = request_user.username

        membership.entity = Entity.objects.first()

        # get or create user
        membership.user, created = membership.get_or_create_user(**{
            'username': self.cleaned_data.get('username'),
            'first_name': self.cleaned_data.get('first_name'),
            'last_name': self.cleaned_data.get('last_name'),
            'email': self.cleaned_data.get('email')
        })

        if not membership.pk:
            membership.renewal = membership.user.profile.can_renew()

        membership.set_member_number()

        # create record in database
        # helps with associating invoice record
        membership.save()

        NOW = datetime.now()

        if not membership.approval_required():  # approval not required

            # save invoice estimate
            membership.save_invoice(status_detail='estimate')

            # auto approve
            membership.application_approved = True
            membership.application_approved_dt = NOW

            membership.set_join_dt()
            membership.set_renew_dt()
            membership.set_expire_dt()

        else:  # approval required
            # save invoice tendered
            membership.save_invoice(status_detail='tendered')

        # application complete
        membership.application_complete_dt = NOW
        membership.application_complete_user = membership.user

        # save application fields
        # save join, renew, and expire dt
        membership.save()

        # send welcome email; if required
        if created:
            send_welcome_email(membership.user)

        # [un]subscribe to group
        membership.group_refresh()

        # loop through & set these user attributes
        # user.first_name = self.cleaned_data.get('first_name', u'')
        user_attrs = [
            'first_name',
            'last_name',
            'email',
        ]

        for i in user_attrs:
            setattr(membership.user, i, self.cleaned_data.get(i, u''))
        membership.user.save()
        # -----------------------------------------------------------

        # loop through & set these profile attributes
        # profile.display_name = self.cleaned_data.get('display_name', u'')
        profile_attrs = [
            'display_name',
            'company',
            'position_title',
            # 'functional_title',
            'department',
            'address',
            'address2',
            'city',
            'state',
            'zipcode',
            'country',
            'address_type',
            'phone',
            'phone2',
            'work_phone',
            'home_phone',
            'mobile_phone',
            # 'pager',
            'fax',
            'email',
            'email2',
            'url',
            'url2',
            'hide_in_search',
            'hide_address',
            'hide_email',
            'hide_phone',
            'dob',
            'sex',
            'spouse',
        ]

        for i in profile_attrs:
            setattr(membership.user.profile, i, self.cleaned_data.get(i, u''))
        membership.user.profile.save()
        # -----------------------------------------------------------------

        # save education fields ----------------------------
        educations = zip(
            request.POST.getlist('education_school'),
            request.POST.getlist('education_degree'),
            request.POST.getlist('education_major'),
            request.POST.getlist('education_grad_dt'),
        )

        for education in educations:
            if any(education):
                school, degree, major, grad_dt = education
                Education.objects.create(
                    user=membership.user,
                    school=school,
                    degree=degree,
                    major=major,
                    graduation_dt=grad_dt,
                )
        # --------------------------------------------------

        # save career fields -------------------------------
        careers = zip(
            request.POST.getlist('career_name'),
            request.POST.getlist('career_description'),
            request.POST.getlist('position_title'),
            request.POST.getlist('position_description'),
            request.POST.getlist('career_start_dt'),
            request.POST.getlist('career_end_dt'),
        )

        for career in careers:
            if any(career) and all(career[4:]):
                (career_name, career_description, position_title,
                    position_description, career_start_dt, career_end_dt) = career
                Career.objects.create(
                    company=career_name,
                    company_description=career_description,
                    position_title=position_title,
                    position_description=position_description,
                    start_dt=career_start_dt,
                    end_dt=career_end_dt,
                )
        # --------------------------------------------------

        return membership


class MembershipForm(TendenciBaseForm):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('inactive', 'In Active'),
    )

    status_detail = forms.ChoiceField(choices=STATUS_CHOICES)
    subscribe_dt = SplitDateTimeField(label=_('Subscribe Date'))
    expire_dt = SplitDateTimeField(label=_('Expiration Date'), required=False)
    ma = forms.ModelChoiceField(label=_('Application'), queryset=App.objects.all())

    class Meta:
        model = Membership

        fields = (
            'member_number',
            'membership_type',
            'user',
            'renewal',
            'subscribe_dt',
            'expire_dt',
            'payment_method',
            'ma',
            'send_notice',
            'user_perms',
            'member_perms',
            'group_perms',
            'status_detail',
        )

        fieldsets = [
            ('Membership Details', {
                'fields': [
                    'membership_type',
                    'user',
                    'member_number',
                    'subscribe_dt',
                    'expire_dt',
                    'renewal',
                    'payment_method',
                    'ma',
                    'send_notice',
                ],
                'legend': ''
            }),
            ('Permissions', {
                'fields': [
                    'allow_anonymous_view',
                    'user_perms',
                    'member_perms',
                    'group_perms',
                ],
                'classes': ['permissions'],
            }),
            ('Administrator Only', {
                'fields': [
                    'syndicate',
                    'status_detail'],
                'classes': ['admin-only'],
            })]
