from django.db import models
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from django.contrib.contenttypes.models import ContentType

class Company(models.Model):
    """Modèle pour l'entreprise"""
    name = models.CharField(_("Nom de l'entreprise"), max_length=255, unique=True)
    logo = models.ImageField(_("Logo"), upload_to='company_logos/', null=True, blank=True)
    address = models.TextField(_("Adresse"), blank=True)
    phone = models.CharField(_("Téléphone"), max_length=20, blank=True)
    email = models.EmailField(_("Email"), blank=True)
    website = models.URLField(_("Site web"), blank=True)
    fiscal_id = models.CharField(_("Matricule fiscal"), max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Configuration des congés
    leave_year_start_month = models.PositiveIntegerField(
        _("Mois de début d'année de congés"),
        default=1,
        choices=[(i, i) for i in range(1, 13)],
        help_text=_("Mois où commence l'année de congés (1=Janvier)")
    )
    leave_year_start_day = models.PositiveIntegerField(
        _("Jour de début d'année de congés"),
        default=1,
        choices=[(i, i) for i in range(1, 32)],
        help_text=_("Jour où commence l'année de congés")
    )
    
    class Meta:
        verbose_name = _("Entreprise")
        verbose_name_plural = _("Entreprises")
    
    def __str__(self):
        return self.name


class Division(models.Model):
    """Direction - Optionnelle"""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='divisions')
    name = models.CharField(_("Nom de la direction"), max_length=255)
    code = models.CharField(_("Code"), max_length=50, blank=True)
    manager = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, 
                               related_name='managed_divisions')
    description = models.TextField(_("Description"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _("Direction")
        verbose_name_plural = _("Directions")
        unique_together = ('company', 'name')
    
    def __str__(self):
        return f"{self.name} - {self.company.name}"


class Department(models.Model):
    """Département"""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='departments')
    division = models.ForeignKey(Division, on_delete=models.SET_NULL, null=True, blank=True, 
                                related_name='departments')
    name = models.CharField(_("Nom du département"), max_length=255)
    code = models.CharField(_("Code"), max_length=50, blank=True)
    manager = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, 
                               related_name='managed_departments')
    description = models.TextField(_("Description"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _("Département")
        verbose_name_plural = _("Départements")
        unique_together = ('company', 'name')
    
    def __str__(self):
        return self.name


class Service(models.Model):
    """Service"""
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='services')
    name = models.CharField(_("Nom du service"), max_length=255)
    code = models.CharField(_("Code"), max_length=50, blank=True)
    manager = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, 
                               related_name='managed_services')
    description = models.TextField(_("Description"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _("Service")
        verbose_name_plural = _("Services")
        unique_together = ('department', 'name')
    
    def __str__(self):
        return self.name


class User(AbstractUser):
    """Utilisateur personnalisé avec rôle intégré"""
    class Role(models.TextChoices):
        ADMIN = 'admin', _('Administrateur')
        HR = 'hr', _('Ressources Humaines')
        EMPLOYEE = 'employee', _('Employé')
        MANAGER = 'manager', _('Manager')
        RAF = 'raf', _('RAF (Responsable Absence Formation)')
    
    # Informations de base
    role = models.CharField(_("Rôle"), max_length=20, choices=Role.choices, default=Role.EMPLOYEE)
    
    # Structure organisationnelle
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='employees', null=True, blank=True)
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, blank=True, 
                               related_name='members')
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, 
                                  related_name='members')
    
    # Informations professionnelles
    employee_id = models.CharField(_("Matricule"), max_length=50, unique=True, blank=True, null=True)
    position = models.CharField(_("Poste"), max_length=255, blank=True)
    hire_date = models.DateField(_("Date d'embauche"), null=True, blank=True)
    contract_type = models.CharField(_("Type de contrat"), max_length=100, blank=True)
    
    # Informations personnelles
    phone_regex = RegexValidator(
        regex=r'^\+?1?\d{9,15}$',
        message=_("Numéro de téléphone doit être au format: '+999999999'. Jusqu'à 15 chiffres.")
    )
    personal_phone = models.CharField(_("Téléphone personnel"), validators=[phone_regex], max_length=17, blank=True)
    emergency_contact = models.CharField(_("Contact d'urgence"), max_length=255, blank=True)
    emergency_phone = models.CharField(_("Téléphone d'urgence"), validators=[phone_regex], max_length=17, blank=True)
    
    # Photo de profil
    profile_picture = models.ImageField(_("Photo de profil"), upload_to='profile_pictures/', null=True, blank=True)
    
    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login = models.DateTimeField(_("Dernière connexion"), null=True, blank=True)
    
    # Champs spécifiques aux managers/validateurs
    is_approver = models.BooleanField(_("Peut valider les congés"), default=False)
    max_approval_level = models.PositiveIntegerField(
        _("Niveau maximum de validation"),
        default=1,
        help_text=_("Niveau hiérarchique maximum pour la validation (1 = N+1, 2 = N+2, etc.)")
    )
    
    # Champs pour les absences et formations
    is_raf = models.BooleanField(_("Responsable Absence Formation"), default=False)
    
    # Métadonnées
    is_active = models.BooleanField(_("Actif"), default=True)
    notes = models.TextField(_("Notes"), blank=True)
    
    # Relations ManyToMany pour les permissions supplémentaires
    additional_groups = models.ManyToManyField(
        Group,
        verbose_name=_("Groupes supplémentaires"),
        blank=True,
        related_name='additional_users'
    )
    user_permissions = models.ManyToManyField(
        Permission,
        verbose_name=_('Permissions utilisateur'),
        blank=True,
        related_name='custom_user_permissions',
        help_text=_('Permissions spécifiques à cet utilisateur.')
    )
    
    class Meta:
        verbose_name = _("Utilisateur")
        verbose_name_plural = _("Utilisateurs")
        ordering = ['last_name', 'first_name']
    
    def __str__(self):
        return f"{self.get_full_name()} ({self.employee_id})"
    
    @property
    def full_name(self):
        return self.get_full_name()
    
    @property
    def is_hr(self):
        return self.role in [self.Role.HR, self.Role.ADMIN]
    
    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN
    
    @property
    def is_manager(self):
        return self.role in [self.Role.MANAGER, self.Role.ADMIN, self.Role.HR] or self.is_approver
    
    def get_organizational_hierarchy(self):
        """Retourne la hiérarchie organisationnelle de l'utilisateur"""
        hierarchy = []
        if self.company:
            hierarchy.append(self.company)
        if self.service:
            hierarchy.append(self.service.department)
            hierarchy.append(self.service)
        elif self.department:
            hierarchy.append(self.department)
        return hierarchy
    
    
    # Dans la classe User, ajoutez cette méthode
    def log_activity(self, action_type, module, description, **kwargs):
        """Méthode raccourci pour logger une activité de l'utilisateur"""
        from .models import ActivityLog
        kwargs['user'] = self
        return ActivityLog.log_action(
            action_type=action_type,
            module=module,
            description=description,
            **kwargs
        )


class UserProfile(models.Model):
    """Profil étendu de l'utilisateur"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    
    # Préférences
    language = models.CharField(_("Langue"), max_length=10, default='fr', 
                               choices=[('fr', 'Français'), ('en', 'English')])
    theme = models.CharField(_("Thème"), max_length=20, default='light',
                            choices=[('light', 'Clair'), ('dark', 'Sombre')])
    
    # Notifications
    email_notifications = models.BooleanField(_("Notifications par email"), default=True)
    in_app_notifications = models.BooleanField(_("Notifications dans l'application"), default=True)
    notify_on_approval = models.BooleanField(_("Notifier lors d'une demande à valider"), default=True)
    notify_on_status_change = models.BooleanField(_("Notifier lors du changement de statut"), default=True)
    notify_on_leave_balance = models.BooleanField(_("Notifier sur le solde de congés"), default=True)
    
    # Signature numérique
    signature = models.ImageField(_("Signature"), upload_to='signatures/', null=True, blank=True)
    
    # Documents
    cv = models.FileField(_("CV"), upload_to='cvs/', null=True, blank=True)
    diploma = models.FileField(_("Diplôme"), upload_to='diplomas/', null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _("Profil utilisateur")
        verbose_name_plural = _("Profils utilisateurs")
    
    def __str__(self):
        return f"Profil de {self.user.get_full_name()}"


class ApprovalWorkflow(models.Model):
    """Configuration du workflow de validation"""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='approval_workflows')
    name = models.CharField(_("Nom du workflow"), max_length=255)
    description = models.TextField(_("Description"), blank=True)
    
    # Configuration des niveaux de validation
    levels = models.PositiveIntegerField(
        _("Nombre de niveaux de validation"),
        default=1,
        help_text=_("Nombre d'étapes de validation requises")
    )
    
    # Qui valide à chaque niveau
    level1_approver = models.CharField(
        _("Validateur niveau 1"),
        max_length=50,
        choices=[
            ('direct_manager', _('Manager direct')),
            ('department_manager', _('Chef de département')),
            ('hr', _('Ressources Humaines')),
            ('specific_user', _('Utilisateur spécifique')),
        ],
        default='direct_manager'
    )
    level1_specific_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='level1_workflows'
    )
    
    level2_approver = models.CharField(
        _("Validateur niveau 2"),
        max_length=50,
        choices=[
            ('department_manager', _('Chef de département')),
            ('division_manager', _('Chef de direction')),
            ('hr', _('Ressources Humaines')),
            ('specific_user', _('Utilisateur spécifique')),
            ('none', _('Aucun')),
        ],
        default='none'
    )
    level2_specific_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='level2_workflows'
    )
    
    level3_approver = models.CharField(
        _("Validateur niveau 3"),
        max_length=50,
        choices=[
            ('division_manager', _('Chef de direction')),
            ('hr_director', _('Directeur RH')),
            ('specific_user', _('Utilisateur spécifique')),
            ('none', _('Aucun')),
        ],
        default='none'
    )
    level3_specific_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='level3_workflows'
    )
    
    # Options
    require_comments_on_rejection = models.BooleanField(
        _("Commentaires obligatoires en cas de rejet"),
        default=True
    )
    auto_approve_after_days = models.PositiveIntegerField(
        _("Approbation automatique après X jours"),
        null=True, blank=True,
        help_text=_("Si vide, pas d'approbation automatique")
    )
    
    # Application
    apply_to_all = models.BooleanField(_("Appliquer à toute l'entreprise"), default=False)
    apply_to_departments = models.ManyToManyField(
        Department, 
        verbose_name=_("Départements concernés"),
        blank=True
    )
    apply_to_services = models.ManyToManyField(
        Service,
        verbose_name=_("Services concernés"),
        blank=True
    )
    apply_to_users = models.ManyToManyField(
        User,
        verbose_name=_("Utilisateurs concernés"),
        blank=True
    )
    
    is_active = models.BooleanField(_("Actif"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _("Workflow de validation")
        verbose_name_plural = _("Workflows de validation")
    
    def __str__(self):
        return f"{self.name} - {self.company.name}"




class ActivityLog(models.Model):
    """Journalisation des activités utilisateurs"""
    class ActionType(models.TextChoices):
        LOGIN = 'login', _('Connexion')
        LOGOUT = 'logout', _('Déconnexion')
        CREATE = 'create', _('Création')
        UPDATE = 'update', _('Modification')
        DELETE = 'delete', _('Suppression')
        APPROVE = 'approve', _('Approbation')
        REJECT = 'reject', _('Rejet')
        VIEW = 'view', _('Consultation')
        EXPORT = 'export', _('Exportation')
        IMPORT = 'import', _('Importation')
        DOWNLOAD = 'download', _('Téléchargement')
        SYSTEM = 'system', _('Action système')
        OTHER = 'other', _('Autre')
    
    class Module(models.TextChoices):
        AUTHENTICATION = 'authentication', _('Authentification')
        USER_MANAGEMENT = 'user_management', _('Gestion utilisateurs')
        ORGANIZATION = 'organization', _('Organisation')
        LEAVE_MANAGEMENT = 'leave_management', _('Gestion congés')
        APPROVAL = 'approval', _('Validation')
        ATTENDANCE = 'attendance', _('Présence')
        REPORTING = 'reporting', _('Rapports')
        PROFILE = 'profile', _('Profil')
        SETTINGS = 'settings', _('Paramètres')
        SYSTEM = 'system', _('Système')
    
    # Utilisateur concerné
    user = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='activity_logs',
        verbose_name=_("Utilisateur")
    )
    
    # Action effectuée
    action_type = models.CharField(
        _("Type d'action"),
        max_length=50,
        choices=ActionType.choices
    )
    
    # Module concerné
    module = models.CharField(
        _("Module"),
        max_length=50,
        choices=Module.choices
    )
    
    # Description détaillée
    description = models.TextField(_("Description"))
    
    # Objet concerné (générique)
    content_type = models.ForeignKey(
        'contenttypes.ContentType', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name=_("Type de contenu")
    )
    object_id = models.PositiveIntegerField(
        _("ID de l'objet"),
        null=True, 
        blank=True
    )
    
    # Données avant/après (pour tracking des modifications)
    old_data = models.JSONField(
        _("Données avant modification"),
        null=True, 
        blank=True,
        help_text=_("Valeurs avant la modification (format JSON)")
    )
    new_data = models.JSONField(
        _("Données après modification"),
        null=True, 
        blank=True,
        help_text=_("Valeurs après la modification (format JSON)")
    )
    
    # IP et informations de la session
    ip_address = models.GenericIPAddressField(
        _("Adresse IP"),
        null=True, 
        blank=True
    )
    user_agent = models.TextField(
        _("User Agent"),
        blank=True
    )
    
    # Localisation (si disponible)
    latitude = models.DecimalField(
        _("Latitude"),
        max_digits=9, 
        decimal_places=6,
        null=True, 
        blank=True
    )
    longitude = models.DecimalField(
        _("Longitude"),
        max_digits=9, 
        decimal_places=6,
        null=True, 
        blank=True
    )
    
    # Statut de l'action
    is_success = models.BooleanField(
        _("Succès"),
        default=True
    )
    error_message = models.TextField(
        _("Message d'erreur"),
        blank=True
    )
    
    # Métadonnées
    duration = models.DecimalField(
        _("Durée (secondes)"),
        max_digits=10, 
        decimal_places=3,
        null=True, 
        blank=True,
        help_text=_("Durée d'exécution de l'action")
    )
    
    created_at = models.DateTimeField(
        _("Date et heure"),
        auto_now_add=True
    )
    
    class Meta:
        verbose_name = _("Journal d'activité")
        verbose_name_plural = _("Journaux d'activité")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['action_type', 'created_at']),
            models.Index(fields=['module', 'created_at']),
        ]
    
    def __str__(self):
        user_name = self.user.get_full_name() if self.user else _("Utilisateur inconnu")
        return f"{user_name} - {self.get_action_type_display()} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"
    
    @property
    def object_repr(self):
        """Représentation de l'objet concerné"""
        if self.content_type and self.object_id:
            try:
                obj = self.content_type.get_object_for_this_type(pk=self.object_id)
                return str(obj)
            except:
                return f"{self.content_type.model}#{self.object_id}"
        return ""
    
    @classmethod
    def log_action(cls, user=None, action_type='other', module='system', 
                   description='', content_object=None, old_data=None, 
                   new_data=None, ip_address=None, user_agent='', 
                   is_success=True, error_message='', request=None):
        """
        Méthode utilitaire pour enregistrer une activité
        
        Args:
            user: Utilisateur effectuant l'action
            action_type: Type d'action (choix dans ActionType)
            module: Module concerné (choix dans Module)
            description: Description de l'action
            content_object: Objet Django concerné
            old_data: Données avant modification (dict)
            new_data: Données après modification (dict)
            ip_address: Adresse IP
            user_agent: User Agent du navigateur
            is_success: Si l'action a réussi
            error_message: Message d'erreur en cas d'échec
            request: Objet HttpRequest (facultatif)
        """
        if request:
            if not ip_address:
                ip_address = cls.get_client_ip(request)
            if not user_agent:
                user_agent = request.META.get('HTTP_USER_AGENT', '')
        
        # Récupérer le type de contenu et l'ID de l'objet
        content_type = None
        object_id = None
        if content_object and hasattr(content_object, 'pk'):
            content_type = ContentType.objects.get_for_model(content_object)
            object_id = content_object.pk
        
        # Créer l'entrée de log
        log_entry = cls.objects.create(
            user=user,
            action_type=action_type,
            module=module,
            description=description,
            content_type=content_type,
            object_id=object_id,
            old_data=old_data,
            new_data=new_data,
            ip_address=ip_address,
            user_agent=user_agent,
            is_success=is_success,
            error_message=error_message
        )
        
        return log_entry
    
    @staticmethod
    def get_client_ip(request):
        """Récupère l'adresse IP du client"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip    