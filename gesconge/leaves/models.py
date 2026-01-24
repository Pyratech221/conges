from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from users.models import User, Company

class LeaveType(models.Model):
    """Type de congé/absence"""
    class Category(models.TextChoices):
        PAID = 'paid', _('Congés payés')
        UNPAID = 'unpaid', _('Congés sans solde')
        SICK = 'sick', _('Congés maladie')
        MATERNITY = 'maternity', _('Congé maternité')
        PATERNITY = 'paternity', _('Congé paternité')
        TRAINING = 'training', _('Formation/Atelier')
        SPECIAL = 'special', _('Congé exceptionnel')
        OTHER = 'other', _('Autre')
    
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='leave_types')
    name = models.CharField(_("Nom du type"), max_length=255)
    category = models.CharField(_("Catégorie"), max_length=50, choices=Category.choices, default=Category.PAID)
    code = models.CharField(_("Code"), max_length=50, blank=True)
    
    # Configuration
    requires_approval = models.BooleanField(_("Nécessite une validation"), default=True)
    requires_document = models.BooleanField(_("Nécessite un justificatif"), default=False)
    deduct_from_balance = models.BooleanField(_("Déduit du solde"), default=True)
    is_active = models.BooleanField(_("Actif"), default=True)
    
    # Limites
    max_days_per_year = models.PositiveIntegerField(
        _("Nombre maximum de jours par an"),
        null=True, blank=True,
        help_text=_("Laisser vide pour illimité")
    )
    max_consecutive_days = models.PositiveIntegerField(
        _("Nombre maximum de jours consécutifs"),
        null=True, blank=True,
        help_text=_("Laisser vide pour illimité")
    )
    min_notice_days = models.PositiveIntegerField(
        _("Délai de préavis minimum (jours)"),
        default=0
    )
    
    # Couleur pour le calendrier
    color = models.CharField(_("Couleur"), max_length=7, default='#007bff', 
                           help_text=_("Couleur HEX pour l'affichage"))
    icon = models.CharField(_("Icône"), max_length=50, blank=True, 
                          help_text=_("Classe CSS pour l'icône"))
    
    description = models.TextField(_("Description"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _("Type de congé")
        verbose_name_plural = _("Types de congé")
        unique_together = ('company', 'name')
    
    def __str__(self):
        return f"{self.name} - {self.company.name}"


class Holiday(models.Model):
    """Jours fériés"""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='holidays')
    name = models.CharField(_("Nom"), max_length=255)
    date = models.DateField(_("Date"))
    is_recurring = models.BooleanField(_("Récurrent chaque année"), default=True)
    description = models.TextField(_("Description"), blank=True)
    is_active = models.BooleanField(_("Actif"), default=True)
    
    class Meta:
        verbose_name = _("Jour férié")
        verbose_name_plural = _("Jours fériés")
        ordering = ['date']
        unique_together = ('company', 'date', 'name')
    
    def __str__(self):
        return f"{self.name} ({self.date})"


class LeaveBalance(models.Model):
    """Solde de congés d'un employé"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='leave_balances')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, related_name='balances')
    year = models.PositiveIntegerField(_("Année"))
    
    # Soldes
    entitled_days = models.DecimalField(
        _("Jours acquis"),
        max_digits=5,
        decimal_places=2,
        default=0
    )
    used_days = models.DecimalField(
        _("Jours utilisés"),
        max_digits=5,
        decimal_places=2,
        default=0
    )
    pending_days = models.DecimalField(
        _("Jours en attente"),
        max_digits=5,
        decimal_places=2,
        default=0
    )
    carried_over_days = models.DecimalField(
        _("Jours reportés"),
        max_digits=5,
        decimal_places=2,
        default=0
    )
    
    # Calculé
    @property
    def remaining_days(self):
        return self.entitled_days + self.carried_over_days - self.used_days - self.pending_days
    
    # Métadonnées
    last_calculated = models.DateTimeField(_("Dernier calcul"), auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _("Solde de congé")
        verbose_name_plural = _("Soldes de congé")
        unique_together = ('user', 'leave_type', 'year')
    
    def __str__(self):
        return f"{self.user} - {self.leave_type} ({self.year})"


class LeaveRequest(models.Model):
    """Demande de congé/absence"""
    class Status(models.TextChoices):
        DRAFT = 'draft', _('Brouillon')
        PENDING = 'pending', _('En attente')
        APPROVED = 'approved', _('Approuvé')
        REJECTED = 'rejected', _('Rejeté')
        CANCELLED = 'cancelled', _('Annulé')
        IN_PROGRESS = 'in_progress', _('En cours')
        COMPLETED = 'completed', _('Terminé')
    
    class DayType(models.TextChoices):
        FULL_DAY = 'full_day', _('Journée complète')
        MORNING = 'morning', _('Matin')
        AFTERNOON = 'afternoon', _('Après-midi')
        SPECIFIC_HOURS = 'specific_hours', _('Heures spécifiques')
    
    # Informations de base
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name='requests')
    workflow = models.ForeignKey('users.ApprovalWorkflow', on_delete=models.SET_NULL, 
                                null=True, blank=True, related_name='leave_requests')
    
    # Période
    start_date = models.DateField(_("Date de début"))
    end_date = models.DateField(_("Date de fin"))
    start_day_type = models.CharField(_("Type de jour début"), max_length=20, 
                                     choices=DayType.choices, default=DayType.FULL_DAY)
    end_day_type = models.CharField(_("Type de jour fin"), max_length=20, 
                                   choices=DayType.choices, default=DayType.FULL_DAY)
    
    # Pour les heures spécifiques
    start_time = models.TimeField(_("Heure de début"), null=True, blank=True)
    end_time = models.TimeField(_("Heure de fin"), null=True, blank=True)
    
    # Calcul des jours
    total_days = models.DecimalField(
        _("Nombre total de jours"),
        max_digits=5,
        decimal_places=2,
        default=0
    )
    working_days = models.DecimalField(
        _("Nombre de jours ouvrables"),
        max_digits=5,
        decimal_places=2,
        default=0
    )
    
    # Détails
    reason = models.TextField(_("Motif"))
    contact_during_leave = models.CharField(_("Contact pendant le congé"), max_length=255, blank=True)
    phone_during_leave = models.CharField(_("Téléphone pendant le congé"), max_length=20, blank=True)
    
    # Remplaçant
    replacement = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='replacement_for',
        verbose_name=_("Remplaçant")
    )
    
    # Documents
    attachment = models.FileField(
        _("Justificatif"),
        upload_to='leave_attachments/',
        null=True,
        blank=True
    )
    
    # Statut et suivi
    status = models.CharField(
        _("Statut"),
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT
    )
    current_approval_level = models.PositiveIntegerField(_("Niveau de validation actuel"), default=1)
    
    # Dates importantes
    submitted_at = models.DateTimeField(_("Date de soumission"), null=True, blank=True)
    approved_at = models.DateTimeField(_("Date d'approbation"), null=True, blank=True)
    rejected_at = models.DateTimeField(_("Date de rejet"), null=True, blank=True)
    cancelled_at = models.DateTimeField(_("Date d'annulation"), null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _("Demande de congé")
        verbose_name_plural = _("Demandes de congé")
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user} - {self.leave_type} ({self.start_date} au {self.end_date})"
    
    def save(self, *args, **kwargs):
        # Calcul automatique du total_days si vide
        if not self.total_days and self.start_date and self.end_date:
            delta = self.end_date - self.start_date
            self.total_days = delta.days + 1  # +1 pour inclure le premier jour
        super().save(*args, **kwargs)


class LeaveApproval(models.Model):
    """Validation d'une demande de congé"""
    class ApprovalStatus(models.TextChoices):
        PENDING = 'pending', _('En attente')
        APPROVED = 'approved', _('Approuvé')
        REJECTED = 'rejected', _('Rejeté')
    
    leave_request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name='approvals')
    approver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='leave_approvals')
    approval_level = models.PositiveIntegerField(_("Niveau de validation"))
    
    # Décision
    status = models.CharField(
        _("Statut"),
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING
    )
    comments = models.TextField(_("Commentaires"), blank=True)
    
    # Signature
    signed_at = models.DateTimeField(_("Date de signature"), null=True, blank=True)
    signed_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='signed_approvals',
        verbose_name=_("Signé par")
    )
    
    # Délégation
    is_delegated = models.BooleanField(_("Délégation"), default=False)
    original_approver = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='delegated_from',
        verbose_name=_("Validateur original")
    )
    
    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notified_at = models.DateTimeField(_("Date de notification"), null=True, blank=True)
    
    class Meta:
        verbose_name = _("Validation de congé")
        verbose_name_plural = _("Validations de congé")
        unique_together = ('leave_request', 'approval_level')
    
    def __str__(self):
        return f"Validation niveau {self.approval_level} - {self.leave_request}"


class LeaveDay(models.Model):
    """Détail jour par jour d'une demande de congé"""
    leave_request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name='leave_days')
    date = models.DateField(_("Date"))
    is_working_day = models.BooleanField(_("Jour ouvrable"), default=True)
    is_holiday = models.BooleanField(_("Jour férié"), default=False)
    day_type = models.CharField(
        _("Type de jour"),
        max_length=20,
        choices=LeaveRequest.DayType.choices,
        default=LeaveRequest.DayType.FULL_DAY
    )
    duration = models.DecimalField(
        _("Durée en jours"),
        max_digits=3,
        decimal_places=2,
        default=1.0
    )
    
    class Meta:
        verbose_name = _("Jour de congé")
        verbose_name_plural = _("Jours de congé")
        unique_together = ('leave_request', 'date')
    
    def __str__(self):
        return f"{self.date} - {self.leave_request}"


class Notification(models.Model):
    """Notifications système"""
    class NotificationType(models.TextChoices):
        LEAVE_REQUEST = 'leave_request', _('Nouvelle demande de congé')
        LEAVE_APPROVED = 'leave_approved', _('Congé approuvé')
        LEAVE_REJECTED = 'leave_rejected', _('Congé rejeté')
        LEAVE_CANCELLED = 'leave_cancelled', _('Congé annulé')
        APPROVAL_REQUIRED = 'approval_required', _('Validation requise')
        REMINDER = 'reminder', _('Rappel')
        BALANCE_LOW = 'balance_low', _('Solde faible')
        SYSTEM = 'system', _('Message système')
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(
        _("Type de notification"),
        max_length=50,
        choices=NotificationType.choices
    )
    title = models.CharField(_("Titre"), max_length=255)
    message = models.TextField(_("Message"))
    
    # Lien vers l'objet concerné
    content_type = models.ForeignKey('contenttypes.ContentType', on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    
    # Suivi
    is_read = models.BooleanField(_("Lu"), default=False)
    is_email_sent = models.BooleanField(_("Email envoyé"), default=False)
    read_at = models.DateTimeField(_("Date de lecture"), null=True, blank=True)
    
    # Métadonnées
    priority = models.PositiveIntegerField(
        _("Priorité"),
        default=1,
        choices=[(1, 'Normal'), (2, 'Important'), (3, 'Urgent')]
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(_("Expire le"), null=True, blank=True)
    
    class Meta:
        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user} - {self.title}"


class Attendance(models.Model):
    """Pointage/Présence (pour les ateliers)"""
    class AttendanceType(models.TextChoices):
        WORKSHOP = 'workshop', _('Atelier')
        TRAINING = 'training', _('Formation')
        MEETING = 'meeting', _('Réunion')
        OTHER = 'other', _('Autre')
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='attendances')
    attendance_type = models.CharField(
        _("Type de présence"),
        max_length=50,
        choices=AttendanceType.choices,
        default=AttendanceType.WORKSHOP
    )
    title = models.CharField(_("Titre"), max_length=255)
    description = models.TextField(_("Description"), blank=True)
    
    # Période
    start_datetime = models.DateTimeField(_("Date et heure de début"))
    end_datetime = models.DateTimeField(_("Date et heure de fin"))
    
    # Lieu
    location = models.CharField(_("Lieu"), max_length=255, blank=True)
    
    # Validation RAF
    raf_validator = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='validated_attendances',
        verbose_name=_("Validateur RAF")
    )
    is_validated = models.BooleanField(_("Validé"), default=False)
    validated_at = models.DateTimeField(_("Date de validation"), null=True, blank=True)
    
    # Documents
    certificate = models.FileField(
        _("Certificat/Attestation"),
        upload_to='attendance_certificates/',
        null=True,
        blank=True
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _("Présence")
        verbose_name_plural = _("Présences")
        ordering = ['-start_datetime']
    
    def __str__(self):
        return f"{self.user} - {self.title} ({self.start_datetime.date()})"


class Report(models.Model):
    """Rapports générés"""
    class ReportType(models.TextChoices):
        LEAVE_SUMMARY = 'leave_summary', _('Résumé des congés')
        ATTENDANCE = 'attendance', _('Présence')
        BALANCE = 'balance', _('Soldes')
        CUSTOM = 'custom', _('Personnalisé')
    
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='reports')
    report_type = models.CharField(_("Type de rapport"), max_length=50, choices=ReportType.choices)
    name = models.CharField(_("Nom du rapport"), max_length=255)
    description = models.TextField(_("Description"), blank=True)
    
    # Filtres
    start_date = models.DateField(_("Date de début"), null=True, blank=True)
    end_date = models.DateField(_("Date de fin"), null=True, blank=True)
    departments = models.ManyToManyField('users.Department', blank=True)
    services = models.ManyToManyField('users.Service', blank=True)
    users = models.ManyToManyField(User, blank=True)
    leave_types = models.ManyToManyField(LeaveType, blank=True)
    
    # Format de sortie
    output_format = models.CharField(
        _("Format de sortie"),
        max_length=10,
        choices=[('pdf', 'PDF'), ('excel', 'Excel'), ('csv', 'CSV'), ('html', 'HTML')],
        default='pdf'
    )
    
    # Résultat
    file = models.FileField(_("Fichier"), upload_to='reports/', null=True, blank=True)
    file_size = models.PositiveIntegerField(_("Taille du fichier"), null=True, blank=True)
    
    # Métadonnées
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='generated_reports')
    generated_at = models.DateTimeField(_("Généré le"), auto_now_add=True)
    is_scheduled = models.BooleanField(_("Planifié"), default=False)
    schedule_frequency = models.CharField(
        _("Fréquence de planification"),
        max_length=20,
        choices=[('daily', 'Quotidien'), ('weekly', 'Hebdomadaire'), ('monthly', 'Mensuel')],
        blank=True
    )
    
    class Meta:
        verbose_name = _("Rapport")
        verbose_name_plural = _("Rapports")
        ordering = ['-generated_at']
    
    def __str__(self):
        return f"{self.name} - {self.company.name}"