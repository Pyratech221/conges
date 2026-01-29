from django import forms
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from datetime import datetime, date, timedelta
import calendar
from .models import (
    LeaveType, Holiday, LeaveRequest, LeaveApproval, 
    Attendance, Report, LeaveBalance
)
from users.models import User, Department, Service

# ==================== Forms de Congés ====================
class LeaveRequestForm(forms.ModelForm):
    """Formulaire de demande de congé"""
    class Meta:
        model = LeaveRequest
        fields = ['leave_type', 'start_date', 'end_date', 'start_day_type',
                 'end_day_type', 'start_time', 'end_time', 'reason',
                 'contact_during_leave', 'phone_during_leave', 'replacement',
                 'attachment']
        widgets = {
            'leave_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_leave_type'}),
            'start_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'id': 'id_start_date'
            }),
            'end_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'id': 'id_end_date'
            }),
            'start_day_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_start_day_type'}),
            'end_day_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_end_day_type'}),
            'start_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'contact_during_leave': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_during_leave': forms.TextInput(attrs={'class': 'form-control'}),
            'replacement': forms.Select(attrs={'class': 'form-select'}),
            'attachment': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)
        
        # Filtrer les types de congés par entreprise
        if self.company:
            self.fields['leave_type'].queryset = LeaveType.objects.filter(
                company=self.company,
                is_active=True
            )
        
        # Filtrer les remplaçants
        if self.user and self.user.company:
            self.fields['replacement'].queryset = User.objects.filter(
                company=self.user.company,
                is_active=True
            ).exclude(id=self.user.id)
        
        # Masquer les champs d'heure si pas spécifiques
        self.fields['start_time'].required = False
        self.fields['end_time'].required = False
        
        # Ajouter des placeholders
        self.fields['reason'].widget.attrs['placeholder'] = _("Décrivez la raison de votre congé...")
        self.fields['contact_during_leave'].widget.attrs['placeholder'] = _("Nom de la personne à contacter")
        self.fields['phone_during_leave'].widget.attrs['placeholder'] = _("Téléphone de contact")
    
    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        start_day_type = cleaned_data.get('start_day_type')
        end_day_type = cleaned_data.get('end_day_type')
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        leave_type = cleaned_data.get('leave_type')
        
        # Validation des dates
        if start_date and end_date:
            if start_date > end_date:
                raise ValidationError(_("La date de début ne peut pas être après la date de fin."))
            
            # Vérifier le délai de préavis
            if leave_type and leave_type.min_notice_days > 0:
                notice_date = date.today() + timedelta(days=leave_type.min_notice_days)
                if start_date < notice_date:
                    raise ValidationError(_(
                        f"Ce type de congé nécessite un préavis de {leave_type.min_notice_days} jours. "
                        f"La date de début ne peut pas être avant le {notice_date.strftime('%d/%m/%Y')}."
                    ))
            
            # Vérifier la durée maximale consécutive
            if leave_type and leave_type.max_consecutive_days:
                total_days = (end_date - start_date).days + 1
                if total_days > leave_type.max_consecutive_days:
                    raise ValidationError(_(
                        f"Ce type de congé ne peut pas dépasser {leave_type.max_consecutive_days} jours consécutifs. "
                        f"Vous avez demandé {total_days} jours."
                    ))
        
        # Validation des heures pour le type spécifique
        if start_day_type == 'specific_hours' or end_day_type == 'specific_hours':
            if not start_time or not end_time:
                raise ValidationError(_(
                    "Les heures de début et de fin sont requises pour les congés avec heures spécifiques."
                ))
            if start_time and end_time and start_time >= end_time:
                raise ValidationError(_("L'heure de début doit être avant l'heure de fin."))
        
        # Vérifier les chevauchements de congés
        if self.user and start_date and end_date:
            overlapping_leaves = LeaveRequest.objects.filter(
                user=self.user,
                status__in=['pending', 'approved'],
                start_date__lte=end_date,
                end_date__gte=start_date
            )
            if self.instance:
                overlapping_leaves = overlapping_leaves.exclude(id=self.instance.id)
            
            if overlapping_leaves.exists():
                raise ValidationError(_(
                    "Vous avez déjà un congé en cours ou en attente sur cette période. "
                    "Veuillez choisir une autre période."
                ))
        
        return cleaned_data


class LeaveRequestDraftForm(LeaveRequestForm):
    """Formulaire pour sauvegarder en brouillon"""
    class Meta(LeaveRequestForm.Meta):
        fields = LeaveRequestForm.Meta.fields


class LeaveApprovalForm(forms.ModelForm):
    """Formulaire de validation d'un congé"""
    class Meta:
        model = LeaveApproval
        fields = ['status', 'comments']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'comments': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': _("Commentaires (obligatoires en cas de rejet)...")
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.leave_request = kwargs.pop('leave_request', None)
        super().__init__(*args, **kwargs)
        
        # Personnaliser les choix selon le workflow
        if self.leave_request:
            if self.leave_request.current_approval_level == 1:
                self.fields['status'].choices = [
                    ('pending', _('En attente')),
                    ('approved', _('Approuver')),
                    ('rejected', _('Rejeter')),
                ]
    
    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get('status')
        comments = cleaned_data.get('comments')
        
        # Vérifier les commentaires en cas de rejet
        if status == 'rejected' and not comments:
            self.add_error('comments', _("Les commentaires sont obligatoires pour rejeter une demande."))
        
        return cleaned_data


class LeaveCancelForm(forms.Form):
    """Formulaire d'annulation d'un congé"""
    reason = forms.CharField(
        label=_("Raison de l'annulation"),
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': _("Pourquoi annulez-vous ce congé ?...")
        }),
        required=True
    )


# ==================== Forms d'Administration ====================
class LeaveTypeForm(forms.ModelForm):
    """Formulaire pour les types de congés"""
    class Meta:
        model = LeaveType
        fields = ['name', 'category', 'code', 'requires_approval', 
                 'requires_document', 'deduct_from_balance', 'is_active',
                 'max_days_per_year', 'max_consecutive_days', 'min_notice_days',
                 'color', 'icon', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'max_days_per_year': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'max_consecutive_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'min_notice_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'color': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color',
                'style': 'width: 50px; height: 38px; padding: 0;'
            }),
            'icon': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        self.company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)
        
        # Marquer les champs booléens
        for field in ['requires_approval', 'requires_document', 'deduct_from_balance', 'is_active']:
            self.fields[field].widget.attrs['class'] = 'form-check-input'


class HolidayForm(forms.ModelForm):
    """Formulaire pour les jours fériés"""
    class Meta:
        model = Holiday
        fields = ['name', 'date', 'is_recurring', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['is_recurring'].widget.attrs['class'] = 'form-check-input'
        self.fields['is_active'].widget.attrs['class'] = 'form-check-input'


class LeaveBalanceAdjustForm(forms.Form):
    """Formulaire d'ajustement du solde de congés"""
    leave_type = forms.ModelChoiceField(
        label=_("Type de congé"),
        queryset=LeaveType.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    year = forms.IntegerField(
        label=_("Année"),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 2000, 'max': 2100})
    )
    adjustment_type = forms.ChoiceField(
        label=_("Type d'ajustement"),
        choices=[
            ('add_entitled', _("Ajouter des jours acquis")),
            ('subtract_entitled', _("Retirer des jours acquis")),
            ('add_used', _("Ajouter des jours utilisés")),
            ('subtract_used', _("Retirer des jours utilisés")),
            ('add_carried', _("Ajouter des jours reportés")),
            ('subtract_carried', _("Retirer des jours reportés")),
            ('set_entitled', _("Définir les jours acquis")),
            ('set_used', _("Définir les jours utilisés")),
            ('set_carried', _("Définir les jours reportés")),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    amount = forms.DecimalField(
        label=_("Montant"),
        max_digits=5,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    reason = forms.CharField(
        label=_("Raison de l'ajustement"),
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        required=True
    )
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)
        
        if self.company:
            self.fields['leave_type'].queryset = LeaveType.objects.filter(
                company=self.company,
                is_active=True
            )
        
        self.fields['year'].initial = datetime.now().year


# ==================== Forms de Présence ====================
class AttendanceForm(forms.ModelForm):
    """Formulaire de présence (atelier/formation)"""
    class Meta:
        model = Attendance
        fields = ['attendance_type', 'title', 'description', 'start_datetime',
                 'end_datetime', 'location', 'certificate']
        widgets = {
            'attendance_type': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'start_datetime': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'end_datetime': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            'certificate': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
    
    def clean(self):
        cleaned_data = super().clean()
        start_datetime = cleaned_data.get('start_datetime')
        end_datetime = cleaned_data.get('end_datetime')
        
        if start_datetime and end_datetime:
            if start_datetime >= end_datetime:
                raise ValidationError(_("La date/heure de début doit être avant la date/heure de fin."))
            
            # Vérifier que la durée ne dépasse pas une semaine (pour les ateliers)
            if (end_datetime - start_datetime).days > 7:
                raise ValidationError(_("La durée ne peut pas dépasser 7 jours."))
        
        return cleaned_data


class AttendanceValidationForm(forms.ModelForm):
    """Formulaire de validation des présences (RAF)"""
    class Meta:
        model = Attendance
        fields = ['is_validated']
        widgets = {
            'is_validated': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['is_validated'].label = _("Valider cette présence")


# ==================== Forms de Rapports ====================
class ReportForm(forms.ModelForm):
    """Formulaire de génération de rapport"""
    class Meta:
        model = Report
        fields = ['report_type', 'name', 'description', 'start_date', 'end_date',
                 'departments', 'services', 'users', 'leave_types', 'output_format']
        # Note: 'company' n'est pas dans les champs car il sera défini automatiquement
        widgets = {
            'report_type': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'departments': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 5}),
            'services': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 5}),
            'users': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 10}),
            'leave_types': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 5}),
            'output_format': forms.Select(attrs={'class': 'form-select'}),
        }
    
    def __init__(self, *args, **kwargs):
        self.company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)
        
        if self.company:
            self.fields['departments'].queryset = Department.objects.filter(company=self.company)
            self.fields['services'].queryset = Service.objects.filter(department__company=self.company)
            self.fields['users'].queryset = User.objects.filter(company=self.company, is_active=True)
            self.fields['leave_types'].queryset = LeaveType.objects.filter(company=self.company, is_active=True)
        
        # Définir les dates par défaut (mois en cours)
        today = date.today()
        first_day = date(today.year, today.month, 1)
        self.fields['start_date'].initial = first_day
        self.fields['end_date'].initial = today
    
    def save(self, commit=True):
        """Override save pour ajouter automatiquement la company"""
        instance = super().save(commit=False)
        
        if self.company:
            instance.company = self.company
        
        if commit:
            instance.save()
            # Sauvegarder les relations ManyToMany
            self.save_m2m()
        
        return instance

class QuickReportForm(forms.Form):
    """Formulaire de rapport rapide"""
    report_type = forms.ChoiceField(
        label=_("Type de rapport"),
        choices=[
            ('monthly_summary', _("Résumé mensuel")),
            ('team_leave', _("Congés de l'équipe")),
            ('balance_summary', _("Synthèse des soldes")),
            ('attendance_summary', _("Synthèse des présences")),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    period = forms.ChoiceField(
        label=_("Période"),
        choices=[
            ('current_month', _("Mois en cours")),
            ('last_month', _("Mois dernier")),
            ('current_quarter', _("Trimestre en cours")),
            ('last_quarter', _("Trimestre dernier")),
            ('current_year', _("Année en cours")),
            ('custom', _("Personnalisée")),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    custom_start = forms.DateField(
        label=_("Date de début"),
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    custom_end = forms.DateField(
        label=_("Date de fin"),
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    format = forms.ChoiceField(
        label=_("Format"),
        choices=[
            ('pdf', 'PDF'),
            ('excel', 'Excel'),
        ],
        initial='pdf',
        widget=forms.Select(attrs={'class': 'form-select'})
    )


# ==================== Forms de Filtre ====================
class LeaveRequestFilterForm(forms.Form):
    """Formulaire de filtrage des demandes de congé"""
    STATUS_CHOICES = [
        ('', _('Tous les statuts')),
        ('pending', _('En attente')),
        ('approved', _('Approuvé')),
        ('rejected', _('Rejeté')),
        ('cancelled', _('Annulé')),
        ('draft', _('Brouillon')),
    ]
    
    status = forms.ChoiceField(
        label=_("Statut"),
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    leave_type = forms.ModelChoiceField(
        label=_("Type de congé"),
        queryset=LeaveType.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    date_from = forms.DateField(
        label=_("À partir du"),
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    date_to = forms.DateField(
        label=_("Jusqu'au"),
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    user = forms.ModelChoiceField(
        label=_("Employé"),
        queryset=User.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    def __init__(self, *args, **kwargs):
        self.company = kwargs.pop('company', None)
        self.current_user = kwargs.pop('current_user', None)
        super().__init__(*args, **kwargs)
        
        if self.company:
            self.fields['leave_type'].queryset = LeaveType.objects.filter(
                company=self.company,
                is_active=True
            )
            self.fields['user'].queryset = User.objects.filter(
                company=self.company,
                is_active=True
            )
        
        # Définir les dates par défaut (3 derniers mois)
        today = date.today()
        three_months_ago = today - timedelta(days=90)
        self.fields['date_from'].initial = three_months_ago
        self.fields['date_to'].initial = today


class CalendarFilterForm(forms.Form):
    """Formulaire de filtrage du calendrier"""
    view_type = forms.ChoiceField(
        label=_("Vue"),
        choices=[
            ('month', _("Mensuelle")),
            ('week', _("Hebdomadaire")),
            ('day', _("Quotidienne")),
            ('list', _("Liste")),
        ],
        initial='month',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    department = forms.ModelChoiceField(
        label=_("Département"),
        queryset=Department.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    service = forms.ModelChoiceField(
        label=_("Service"),
        queryset=Service.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    leave_type = forms.ModelChoiceField(
        label=_("Type de congé"),
        queryset=LeaveType.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    show_only_team = forms.BooleanField(
        label=_("Afficher uniquement mon équipe"),
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    def __init__(self, *args, **kwargs):
        self.company = kwargs.pop('company', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if self.company:
            self.fields['department'].queryset = Department.objects.filter(company=self.company)
            self.fields['service'].queryset = Service.objects.filter(department__company=self.company)
            self.fields['leave_type'].queryset = LeaveType.objects.filter(
                company=self.company,
                is_active=True
            )


# ==================== Forms Utilitaires ====================
class BulkLeaveApprovalForm(forms.Form):
    """Formulaire de validation en masse"""
    leave_requests = forms.ModelMultipleChoiceField(
        label=_("Demandes à valider"),
        queryset=LeaveRequest.objects.none(),
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': 10})
    )
    action = forms.ChoiceField(
        label=_("Action"),
        choices=[
            ('approve', _("Approuver toutes")),
            ('reject', _("Rejeter toutes")),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    comments = forms.CharField(
        label=_("Commentaires (appliqués à toutes)"),
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        required=False
    )
    
    def __init__(self, *args, **kwargs):
        self.approver = kwargs.pop('approver', None)
        super().__init__(*args, **kwargs)
        
        if self.approver:
            # Filtrer les demandes en attente pour ce validateur
            self.fields['leave_requests'].queryset = LeaveRequest.objects.filter(
                status='pending',
                approvals__approver=self.approver,
                approvals__status='pending'
            ).distinct()


class ImportDataForm(forms.Form):
    """Formulaire d'import de données"""
    import_type = forms.ChoiceField(
        label=_("Type de données à importer"),
        choices=[
            ('users', _("Utilisateurs")),
            ('leave_balances', _("Soldes de congés")),
            ('holidays', _("Jours fériés")),
            ('attendance', _("Présences")),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    data_file = forms.FileField(
        label=_("Fichier (CSV ou Excel)"),
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    update_existing = forms.BooleanField(
        label=_("Mettre à jour les enregistrements existants"),
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )