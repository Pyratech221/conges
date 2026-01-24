from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, PasswordResetForm, SetPasswordForm
from django.utils.translation import gettext_lazy as _
from .models import User, UserProfile, Company, Division, Department, Service, ApprovalWorkflow,ActivityLog

# ==================== Forms d'Authentification ====================
class CustomAuthenticationForm(AuthenticationForm):
    """Formulaire de connexion personnalisé"""
    username = forms.CharField(
        label=_("Nom d'utilisateur ou Email"),
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _("Nom d'utilisateur ou email")})
    )
    password = forms.CharField(
        label=_("Mot de passe"),
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': _("Mot de passe")})
    )
    remember_me = forms.BooleanField(
        label=_("Se souvenir de moi"),
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )


class CustomPasswordChangeForm(PasswordChangeForm):
    """Formulaire de changement de mot de passe"""
    old_password = forms.CharField(
        label=_("Ancien mot de passe"),
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    new_password1 = forms.CharField(
        label=_("Nouveau mot de passe"),
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    new_password2 = forms.CharField(
        label=_("Confirmation du nouveau mot de passe"),
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )


class CustomPasswordResetForm(PasswordResetForm):
    """Formulaire de réinitialisation de mot de passe"""
    email = forms.EmailField(
        label=_("Email"),
        max_length=254,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': _("Entrez votre email"),
            'autocomplete': 'email'
        })
    )


class CustomSetPasswordForm(SetPasswordForm):
    """Formulaire de définition du mot de passe"""
    new_password1 = forms.CharField(
        label=_("Nouveau mot de passe"),
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    new_password2 = forms.CharField(
        label=_("Confirmation du nouveau mot de passe"),
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )


# ==================== Forms de Profil ====================
class UserProfileForm(forms.ModelForm):
    """Formulaire du profil utilisateur"""
    class Meta:
        model = UserProfile
        fields = ['language', 'theme', 'email_notifications', 'in_app_notifications',
                 'notify_on_approval', 'notify_on_status_change', 'notify_on_leave_balance']
        widgets = {
            'language': forms.Select(attrs={'class': 'form-select'}),
            'theme': forms.Select(attrs={'class': 'form-select'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
            else:
                field.widget.attrs['class'] = 'form-control'


class UserForm(forms.ModelForm):
    """Formulaire d'édition des informations utilisateur"""
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'personal_phone',
                 'emergency_contact', 'emergency_phone', 'profile_picture']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'personal_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'emergency_contact': forms.TextInput(attrs={'class': 'form-control'}),
            'emergency_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'profile_picture': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }


class UserAdminForm(forms.ModelForm):
    """Formulaire d'administration des utilisateurs (pour RH/Admin)"""
    password = forms.CharField(
        label=_("Mot de passe"),
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False
    )
    confirm_password = forms.CharField(
        label=_("Confirmer le mot de passe"),
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False
    )
    
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'role', 'company',
                 'service', 'department', 'employee_id', 'position', 'hire_date',
                 'contract_type', 'is_active', 'is_approver', 'max_approval_level',
                 'is_raf', 'notes']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'company': forms.Select(attrs={'class': 'form-select'}),
            'service': forms.Select(attrs={'class': 'form-select'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'employee_id': forms.TextInput(attrs={'class': 'form-control'}),
            'position': forms.TextInput(attrs={'class': 'form-control'}),
            'hire_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'contract_type': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrer les choix selon l'utilisateur connecté
        user = kwargs.get('instance')
        if 'company' in self.fields:
            self.fields['company'].queryset = Company.objects.all()
        if 'service' in self.fields:
            self.fields['service'].queryset = Service.objects.all()
        if 'department' in self.fields:
            self.fields['department'].queryset = Department.objects.all()
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if password and password != confirm_password:
            raise forms.ValidationError(_("Les mots de passe ne correspondent pas."))
        
        return cleaned_data


# ==================== Forms Organisationnels ====================
class CompanyForm(forms.ModelForm):
    """Formulaire pour l'entreprise"""
    class Meta:
        model = Company
        fields = ['name', 'logo', 'address', 'phone', 'email', 'website',
                 'fiscal_id', 'leave_year_start_month', 'leave_year_start_day']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'website': forms.URLInput(attrs={'class': 'form-control'}),
            'fiscal_id': forms.TextInput(attrs={'class': 'form-control'}),
            'leave_year_start_month': forms.Select(attrs={'class': 'form-select'}),
            'leave_year_start_day': forms.Select(attrs={'class': 'form-select'}),
            'logo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }


class DivisionForm(forms.ModelForm):
    """Formulaire pour la direction"""
    class Meta:
        model = Division
        fields = ['company', 'name', 'code', 'manager', 'description']
        widgets = {
            'company': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'manager': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['manager'].queryset = User.objects.filter(
            role__in=[User.Role.ADMIN, User.Role.HR, User.Role.MANAGER]
        )


class DepartmentForm(forms.ModelForm):
    """Formulaire pour le département"""
    class Meta:
        model = Department
        fields = ['company', 'division', 'name', 'code', 'manager', 'description']
        widgets = {
            'company': forms.Select(attrs={'class': 'form-select'}),
            'division': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'manager': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['manager'].queryset = User.objects.filter(
            role__in=[User.Role.ADMIN, User.Role.HR, User.Role.MANAGER]
        )
        
        # Filtre dynamique pour division
        if 'company' in self.data:
            try:
                company_id = int(self.data.get('company'))
                self.fields['division'].queryset = Division.objects.filter(company_id=company_id)
            except (ValueError, TypeError):
                pass


class ServiceForm(forms.ModelForm):
    """Formulaire pour le service"""
    class Meta:
        model = Service
        fields = ['department', 'name', 'code', 'manager', 'description']
        widgets = {
            'department': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'manager': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['manager'].queryset = User.objects.filter(
            role__in=[User.Role.ADMIN, User.Role.HR, User.Role.MANAGER]
        )


# ==================== Forms de Workflow ====================
class ApprovalWorkflowForm(forms.ModelForm):
    """Formulaire pour le workflow de validation"""
    class Meta:
        model = ApprovalWorkflow
        fields = ['company', 'name', 'description', 'levels',
                 'level1_approver', 'level1_specific_user',
                 'level2_approver', 'level2_specific_user',
                 'level3_approver', 'level3_specific_user',
                 'require_comments_on_rejection', 'auto_approve_after_days',
                 'apply_to_all', 'apply_to_departments', 'apply_to_services',
                 'apply_to_users', 'is_active']
        widgets = {
            'company': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'levels': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 3}),
            'level1_approver': forms.Select(attrs={'class': 'form-select'}),
            'level1_specific_user': forms.Select(attrs={'class': 'form-select'}),
            'level2_approver': forms.Select(attrs={'class': 'form-select'}),
            'level2_specific_user': forms.Select(attrs={'class': 'form-select'}),
            'level3_approver': forms.Select(attrs={'class': 'form-select'}),
            'level3_specific_user': forms.Select(attrs={'class': 'form-select'}),
            'auto_approve_after_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'apply_to_departments': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 5}),
            'apply_to_services': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 5}),
            'apply_to_users': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 10}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrer les validateurs potentiels
        for field in ['level1_specific_user', 'level2_specific_user', 'level3_specific_user']:
            if field in self.fields:
                self.fields[field].queryset = User.objects.filter(
                    is_approver=True
                ).exclude(role=User.Role.EMPLOYEE)
        
        # Filtrer les départements et services par entreprise
        if 'company' in self.data:
            try:
                company_id = int(self.data.get('company'))
                self.fields['apply_to_departments'].queryset = Department.objects.filter(company_id=company_id)
                self.fields['apply_to_services'].queryset = Service.objects.filter(department__company_id=company_id)
                self.fields['apply_to_users'].queryset = User.objects.filter(company_id=company_id)
            except (ValueError, TypeError):
                pass
    
    def clean(self):
        cleaned_data = super().clean()
        levels = cleaned_data.get('levels', 1)
        
        # Validation des niveaux
        if levels >= 2 and cleaned_data.get('level2_approver') == 'none':
            self.add_error('level2_approver', _("Veuillez sélectionner un validateur pour le niveau 2."))
        
        if levels >= 3 and cleaned_data.get('level3_approver') == 'none':
            self.add_error('level3_approver', _("Veuillez sélectionner un validateur pour le niveau 3."))
        
        return cleaned_data


# ==================== Forms de Filtre ====================
class UserFilterForm(forms.Form):
    """Formulaire de filtrage des utilisateurs"""
    role = forms.ChoiceField(
        label=_("Rôle"),
        choices=[('', _('Tous les rôles'))] + list(User.Role.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    company = forms.ModelChoiceField(
        label=_("Entreprise"),
        queryset=Company.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    department = forms.ModelChoiceField(
        label=_("Département"),
        queryset=Department.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    service = forms.ModelChoiceField(
        label=_("Service"),
        queryset=Service.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    is_active = forms.ChoiceField(
        label=_("Statut"),
        choices=[('', _('Tous')), ('true', _('Actif')), ('false', _('Inactif'))],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limiter les choix selon les permissions
        # (à adapter selon l'utilisateur connecté)


class ActivityLogFilterForm(forms.Form):
    """Formulaire de filtrage des journaux d'activité"""
    user = forms.ModelChoiceField(
        label=_("Utilisateur"),
        queryset=User.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    action_type = forms.ChoiceField(
        label=_("Type d'action"),
        choices=[('', _('Tous'))] + list(ActivityLog.ActionType.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    module = forms.ChoiceField(
        label=_("Module"),
        choices=[('', _('Tous'))] + list(ActivityLog.Module.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    date_from = forms.DateField(
        label=_("Du"),
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    date_to = forms.DateField(
        label=_("Au"),
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    is_success = forms.ChoiceField(
        label=_("Statut"),
        choices=[('', _('Tous')), ('true', _('Succès')), ('false', _('Échec'))],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )