from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth.views import PasswordResetView, PasswordResetConfirmView
from django.utils.translation import gettext_lazy as _
from django.db.models import Q, Count
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
import json

from django.contrib.auth.models import Group


from .models import (
    User, UserProfile, Company, Division, Department, Service,
    ApprovalWorkflow, ActivityLog
)
from .forms import (
    CustomAuthenticationForm, CustomPasswordChangeForm,
    UserForm, UserProfileForm, UserAdminForm,
    CompanyForm, DivisionForm, DepartmentForm, ServiceForm,
    ApprovalWorkflowForm, UserFilterForm, ActivityLogFilterForm
)
from leaves.models import LeaveRequest

# ==================== Decorators et Helpers ====================
def admin_required(view_func):
    """Décorateur pour les vues réservées aux administrateurs"""
    return user_passes_test(
        lambda u: u.is_authenticated and u.role == User.Role.ADMIN,
        login_url='users:login'
    )(view_func)


def hr_or_admin_required(view_func):
    """Décorateur pour les vues réservées aux RH et administrateurs"""
    return user_passes_test(
        lambda u: u.is_authenticated and u.role in [User.Role.HR, User.Role.ADMIN],
        login_url='users:login'
    )(view_func)


def manager_or_above_required(view_func):
    """Décorateur pour les managers et au-dessus"""
    return user_passes_test(
        lambda u: u.is_authenticated and u.is_manager,
        login_url='users:login'
    )(view_func)


# ==================== Vues d'Authentification ====================
def login_view(request):
    """Vue de connexion"""
    if request.user.is_authenticated:
        return redirect('users:dashboard')
    
    if request.method == 'POST':
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            remember_me = form.cleaned_data.get('remember_me', False)
            
            # Essayer avec le nom d'utilisateur ou l'email
            user = authenticate(request, username=username, password=password)
            if user is None:
                # Essayer avec l'email
                try:
                    user_obj = User.objects.get(email=username)
                    user = authenticate(request, username=user_obj.username, password=password)
                except User.DoesNotExist:
                    pass
            
            if user is not None and user.is_active:
                login(request, user)
                
                # Log de l'activité
                ActivityLog.log_action(
                    user=user,
                    action_type=ActivityLog.ActionType.LOGIN,
                    module=ActivityLog.Module.AUTHENTICATION,
                    description=f"Connexion de {user.get_full_name()}",
                    request=request
                )
                
                # Gestion du "Se souvenir de moi"
                if not remember_me:
                    request.session.set_expiry(0)  # Session expire à la fermeture du navigateur
                
                # Redirection selon le rôle
                next_url = request.GET.get('next', 'users:dashboard')
                messages.success(request, _("Connexion réussie !"))
                return redirect(next_url)
            else:
                messages.error(request, _("Nom d'utilisateur/email ou mot de passe incorrect."))
                # Log de tentative échouée
                ActivityLog.log_action(
                    user=None,
                    action_type=ActivityLog.ActionType.LOGIN,
                    module=ActivityLog.Module.AUTHENTICATION,
                    description=f"Tentative de connexion échouée pour {username}",
                    is_success=False,
                    request=request
                )
    else:
        form = CustomAuthenticationForm()
    
    return render(request, 'users/auth/login.html', {'form': form})


@login_required
def logout_view(request):
    """Vue de déconnexion"""
    # Log de l'activité
    ActivityLog.log_action(
        user=request.user,
        action_type=ActivityLog.ActionType.LOGOUT,
        module=ActivityLog.Module.AUTHENTICATION,
        description=f"Déconnexion de {request.user.get_full_name()}",
        request=request
    )
    
    logout(request)
    messages.info(request, _("Vous avez été déconnecté avec succès."))
    return redirect('users:login')


# ==================== Vues de Dashboard ====================
@login_required
def dashboard(request):
    """Tableau de bord principal"""
    user = request.user
    context = {'user': user}
    team_users = User.objects.none()
    
    # Statistiques selon le rôle
    if user.role in [User.Role.ADMIN, User.Role.HR]:
        # Pour admin/RH
        context['total_users'] = User.objects.filter(company=user.company).count()
        context['active_users'] = User.objects.filter(company=user.company, is_active=True).count()
        context['pending_leaves'] = LeaveRequest.objects.filter(
            status='pending'
        ).count()
        context['today_absences'] = LeaveRequest.objects.filter(
            status='approved',
            start_date__lte=timezone.now().date(),
            end_date__gte=timezone.now().date()
        ).count()
        
    elif user.role == User.Role.MANAGER or user.is_approver:
        # Pour managers
        # Trouver les employés sous sa responsabilité
        team_users = User.objects.filter(
            Q(service__manager=user) | 
            Q(department__manager=user) |
            Q(managed_services__members=user) |
            Q(managed_departments__members=user)
        ).distinct()
        
        context['team_size'] = team_users.count()
        context['team_pending_leaves'] = LeaveRequest.objects.filter(
            user__in=team_users,
            status='pending'
        ).count()
        context['team_today_absences'] = LeaveRequest.objects.filter(
            user__in=team_users,
            status='approved',
            start_date__lte=timezone.now().date(),
            end_date__gte=timezone.now().date()
        ).count()
    
    # Pour tous les utilisateurs
    context['my_pending_leaves'] = LeaveRequest.objects.filter(
        user=user,
        status='pending'
    ).count()
    
    context['my_approved_leaves'] = LeaveRequest.objects.filter(
    user=user,
    status='approved',
    start_date__gte=timezone.now().date()
    ).order_by('-start_date')[:5]
    
    # Notifications non lues
    context['unread_notifications'] = user.notifications.filter(
    is_read=False
    ).order_by('-created_at')[:5]
    
    # Calendrier des prochains congés de l'équipe (pour managers)
    if user.is_manager:
        team_leaves = LeaveRequest.objects.filter(
            user__in=team_users,
            status='approved',
            start_date__gte=timezone.now().date()
        ).order_by('start_date')[:10]
        context['team_upcoming_leaves'] = team_leaves
    
    # Log de l'activité
    ActivityLog.log_action(
        user=user,
        action_type=ActivityLog.ActionType.VIEW,
        module=ActivityLog.Module.SYSTEM,
        description="Accès au tableau de bord",
        request=request
    )
    
    return render(request, 'users/dashboard.html', context)


# ==================== Vues de Profil ====================
@login_required
def profile_view(request):
    """Vue du profil utilisateur"""
    user = request.user
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    
    if request.method == 'POST':
        user_form = UserForm(request.POST, request.FILES, instance=user)
        profile_form = UserProfileForm(request.POST, instance=profile)
        
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            
            # Log de l'activité
            ActivityLog.log_action(
                user=user,
                action_type=ActivityLog.ActionType.UPDATE,
                module=ActivityLog.Module.PROFILE,
                description="Mise à jour du profil",
                request=request
            )
            
            messages.success(request, _("Profil mis à jour avec succès !"))
            return redirect('users:profile')
    else:
        user_form = UserForm(instance=user)
        profile_form = UserProfileForm(instance=profile)
    
    context = {
        'user_form': user_form,
        'profile_form': profile_form,
        'profile': profile,
    }
    
    return render(request, 'users/profile/profile.html', context)


@login_required
def change_password_view(request):
    """Vue de changement de mot de passe"""
    if request.method == 'POST':
        form = CustomPasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # Garder l'utilisateur connecté
            
            # Log de l'activité
            ActivityLog.log_action(
                user=user,
                action_type=ActivityLog.ActionType.UPDATE,
                module=ActivityLog.Module.AUTHENTICATION,
                description="Changement de mot de passe",
                request=request
            )
            
            messages.success(request, _("Votre mot de passe a été changé avec succès !"))
            return redirect('users:profile')
    else:
        form = CustomPasswordChangeForm(request.user)
    
    return render(request, 'users/profile/change_password.html', {'form': form})


# ==================== Vues de Gestion des Utilisateurs ====================
@hr_or_admin_required
def user_list_view(request):
    """Liste des utilisateurs (pour RH/Admin)"""
    users = User.objects.filter(company=request.user.company).order_by('last_name', 'first_name')
    
    # Filtrage
    form = UserFilterForm(request.GET)
    if form.is_valid():
        if form.cleaned_data.get('role'):
            users = users.filter(role=form.cleaned_data['role'])
        if form.cleaned_data.get('company'):
            users = users.filter(company=form.cleaned_data['company'])
        if form.cleaned_data.get('department'):
            users = users.filter(department=form.cleaned_data['department'])
        if form.cleaned_data.get('service'):
            users = users.filter(service=form.cleaned_data['service'])
        if form.cleaned_data.get('is_active'):
            is_active = form.cleaned_data['is_active'] == 'true'
            users = users.filter(is_active=is_active)
    
    # Pagination
    paginator = Paginator(users, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'form': form,
        'total_users': users.count(),
        'active_users': users.filter(is_active=True).count(),
    }
    
    return render(request, 'users/management/user_list.html', context)


@hr_or_admin_required
def user_create_view(request):
    """Création d'un nouvel utilisateur"""
    if request.method == 'POST':
        form = UserAdminForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save(commit=False)
            
            # Définir le mot de passe si fourni
            password = form.cleaned_data.get('password')
            if password:
                user.set_password(password)
            else:
                # Générer un mot de passe par défaut (matricule ou email)
                user.set_password(user.employee_id or user.email)
            
            # Assigner l'entreprise de l'utilisateur connecté si non spécifiée
            if not user.company:
                user.company = request.user.company
            
            user.save()
            form.save_m2m()  # Sauvegarder les relations ManyToMany
            
            # Créer le profil utilisateur
            UserProfile.objects.get_or_create(user=user)
            
            # Log de l'activité
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.CREATE,
                module=ActivityLog.Module.USER_MANAGEMENT,
                description=f"Création de l'utilisateur {user.get_full_name()}",
                content_object=user,
                request=request
            )
            
            messages.success(request, _("Utilisateur créé avec succès !"))
            return redirect('users:user_list')
    else:
        initial = {'company': request.user.company}
        form = UserAdminForm(initial=initial)
    
    return render(request, 'users/management/user_form.html', {'form': form, 'title': _('Créer un utilisateur')})


@hr_or_admin_required
def user_update_view(request, pk):
    """Modification d'un utilisateur"""
    user = get_object_or_404(User, pk=pk, company=request.user.company)
    
    if request.method == 'POST':
        form = UserAdminForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            old_data = {
                'role': user.role,
                'is_active': user.is_active,
                'is_approver': user.is_approver,
            }
            
            user = form.save()
            
            # Mettre à jour le mot de passe si fourni
            password = form.cleaned_data.get('password')
            if password:
                user.set_password(password)
                user.save()
            
            # Log de l'activité avec les changements
            new_data = {
                'role': user.role,
                'is_active': user.is_active,
                'is_approver': user.is_approver,
            }
            
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.UPDATE,
                module=ActivityLog.Module.USER_MANAGEMENT,
                description=f"Modification de l'utilisateur {user.get_full_name()}",
                content_object=user,
                old_data=old_data,
                new_data=new_data,
                request=request
            )
            
            messages.success(request, _("Utilisateur mis à jour avec succès !"))
            return redirect('users:user_list')
    else:
        form = UserAdminForm(instance=user)
    
    return render(request, 'users/management/user_form.html', {'form': form, 'title': _('Modifier un utilisateur')})


@hr_or_admin_required
def user_delete_view(request, pk):
    """Suppression d'un utilisateur"""
    user = get_object_or_404(User, pk=pk, company=request.user.company)
    
    if request.method == 'POST':
        # Log de l'activité avant suppression
        ActivityLog.log_action(
            user=request.user,
            action_type=ActivityLog.ActionType.DELETE,
            module=ActivityLog.Module.USER_MANAGEMENT,
            description=f"Suppression de l'utilisateur {user.get_full_name()}",
            content_object=user,
            request=request
        )
        
        user.delete()
        messages.success(request, _("Utilisateur supprimé avec succès !"))
        return redirect('users:user_list')
    
    return render(request, 'users/management/user_confirm_delete.html', {'user': user})


@login_required
def user_detail_view(request, pk):
    """Détail d'un utilisateur"""
    user = get_object_or_404(User, pk=pk)
    
    # Vérifier les permissions (admin/RH ou manager de l'utilisateur)
    if not (request.user.is_hr or 
            request.user.is_admin or
            (request.user.is_manager and (
                user.service and user.service.manager == request.user or
                user.department and user.department.manager == request.user
            ))):
        messages.error(request, _("Vous n'avez pas la permission de voir ce profil."))
        return redirect('users:dashboard')
    
    # Récupérer les statistiques de l'utilisateur
    leave_requests = LeaveRequest.objects.filter(user=user)
    approved_leaves = leave_requests.filter(status='approved')
    
    context = {
        'profile_user': user,
        'total_leaves': leave_requests.count(),
        'approved_leaves': approved_leaves.count(),
        'pending_leaves': leave_requests.filter(status='pending').count(),
        'upcoming_leaves': approved_leaves.filter(start_date__gte=timezone.now().date())[:5],
    }
    
    return render(request, 'users/management/user_detail.html', context)


# ==================== Vues Organisationnelles ====================
@hr_or_admin_required
def company_update_view(request):
    """Mise à jour de l'entreprise"""
    company = request.user.company
    
    if request.method == 'POST':
        form = CompanyForm(request.POST, request.FILES, instance=company)
        if form.is_valid():
            form.save()
            
            # Log de l'activité
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.UPDATE,
                module=ActivityLog.Module.ORGANIZATION,
                description="Mise à jour des informations de l'entreprise",
                content_object=company,
                request=request
            )
            
            messages.success(request, _("Informations de l'entreprise mises à jour !"))
            return redirect('users:dashboard')
    else:
        form = CompanyForm(instance=company)
    
    return render(request, 'users/organization/company_form.html', {'form': form})


@hr_or_admin_required
def organization_structure_view(request):
    """Vue de la structure organisationnelle"""
    company = request.user.company
    
    # Récupérer la structure hiérarchique
    divisions = Division.objects.filter(company=company).prefetch_related('departments')
    departments = Department.objects.filter(company=company).prefetch_related('services')
    
    # Statistiques
    total_departments = departments.count()
    total_services = Service.objects.filter(department__company=company).count()
    total_employees = User.objects.filter(company=company, is_active=True).count()
    
    context = {
        'company': company,
        'divisions': divisions,
        'departments': departments,
        'total_departments': total_departments,
        'total_services': total_services,
        'total_employees': total_employees,
    }
    
    return render(request, 'users/organization/structure.html', context)


@hr_or_admin_required
def division_list_view(request):
    """Liste des directions"""
    divisions = Division.objects.filter(company=request.user.company)
    return render(request, 'users/organization/division_list.html', {'divisions': divisions})


@hr_or_admin_required
def division_create_view(request):
    """Création d'une direction"""
    if request.method == 'POST':
        form = DivisionForm(request.POST)
        if form.is_valid():
            division = form.save()
            
            # Log de l'activité
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.CREATE,
                module=ActivityLog.Module.ORGANIZATION,
                description=f"Création de la direction {division.name}",
                content_object=division,
                request=request
            )
            
            messages.success(request, _("Direction créée avec succès !"))
            return redirect('users:division_list')
    else:
        form = DivisionForm(initial={'company': request.user.company})
    
    return render(request, 'users/organization/division_form.html', {'form': form})


@hr_or_admin_required
def department_list_view(request):
    """Liste des départements"""
    departments = Department.objects.filter(company=request.user.company)
    return render(request, 'users/organization/department_list.html', {'departments': departments})


@hr_or_admin_required
def department_create_view(request):
    """Création d'un département"""
    if request.method == 'POST':
        form = DepartmentForm(request.POST)
        if form.is_valid():
            department = form.save()
            
            # Log de l'activité
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.CREATE,
                module=ActivityLog.Module.ORGANIZATION,
                description=f"Création du département {department.name}",
                content_object=department,
                request=request
            )
            
            messages.success(request, _("Département créé avec succès !"))
            return redirect('users:department_list')
    else:
        form = DepartmentForm(initial={'company': request.user.company})
    
    return render(request, 'users/organization/department_form.html', {'form': form})


@hr_or_admin_required
def service_list_view(request):
    """Liste des services"""
    services = Service.objects.filter(department__company=request.user.company)
    return render(request, 'users/organization/service_list.html', {'services': services})


@hr_or_admin_required
def service_create_view(request):
    """Création d'un service"""
    if request.method == 'POST':
        form = ServiceForm(request.POST)
        if form.is_valid():
            service = form.save()
            
            # Log de l'activité
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.CREATE,
                module=ActivityLog.Module.ORGANIZATION,
                description=f"Création du service {service.name}",
                content_object=service,
                request=request
            )
            
            messages.success(request, _("Service créé avec succès !"))
            return redirect('users:service_list')
    else:
        form = ServiceForm()
    
    return render(request, 'users/organization/service_form.html', {'form': form})


# ==================== Vues de Workflow ====================
@hr_or_admin_required
def workflow_list_view(request):
    """Liste des workflows de validation"""
    workflows = ApprovalWorkflow.objects.filter(company=request.user.company)
    return render(request, 'users/workflow/workflow_list.html', {'workflows': workflows})


@hr_or_admin_required
def workflow_create_view(request):
    """Création d'un workflow"""
    if request.method == 'POST':
        form = ApprovalWorkflowForm(request.POST)
        if form.is_valid():
            workflow = form.save(commit=False)
            workflow.company = request.user.company
            workflow.save()
            form.save_m2m()  # Sauvegarder les relations ManyToMany
            
            # Log de l'activité
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.CREATE,
                module=ActivityLog.Module.APPROVAL,
                description=f"Création du workflow {workflow.name}",
                content_object=workflow,
                request=request
            )
            
            messages.success(request, _("Workflow créé avec succès !"))
            return redirect('users:workflow_list')
    else:
        form = ApprovalWorkflowForm(initial={'company': request.user.company})
    
    return render(request, 'users/workflow/workflow_form.html', {'form': form})


@hr_or_admin_required
def workflow_update_view(request, pk):
    """Modification d'un workflow"""
    workflow = get_object_or_404(ApprovalWorkflow, pk=pk, company=request.user.company)
    
    if request.method == 'POST':
        form = ApprovalWorkflowForm(request.POST, instance=workflow)
        if form.is_valid():
            workflow = form.save()
            
            # Log de l'activité
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.UPDATE,
                module=ActivityLog.Module.APPROVAL,
                description=f"Modification du workflow {workflow.name}",
                content_object=workflow,
                request=request
            )
            
            messages.success(request, _("Workflow mis à jour avec succès !"))
            return redirect('users:workflow_list')
    else:
        form = ApprovalWorkflowForm(instance=workflow)
    
    return render(request, 'users/workflow/workflow_form.html', {'form': form})


@hr_or_admin_required
def workflow_delete_view(request, pk):
    """Suppression d'un workflow"""
    workflow = get_object_or_404(ApprovalWorkflow, pk=pk, company=request.user.company)
    
    if request.method == 'POST':
        # Log de l'activité
        ActivityLog.log_action(
            user=request.user,
            action_type=ActivityLog.ActionType.DELETE,
            module=ActivityLog.Module.APPROVAL,
            description=f"Suppression du workflow {workflow.name}",
            content_object=workflow,
            request=request
        )
        
        workflow.delete()
        messages.success(request, _("Workflow supprimé avec succès !"))
        return redirect('users:workflow_list')
    
    return render(request, 'users/workflow/workflow_confirm_delete.html', {'workflow': workflow})


# ==================== Vues de Journal d'Activité ====================
@admin_required
def activity_log_view(request):
    """Journal d'activité (admin seulement)"""
    logs = ActivityLog.objects.all().select_related('user').order_by('-created_at')
    
    # Filtrage
    form = ActivityLogFilterForm(request.GET)
    if form.is_valid():
        if form.cleaned_data.get('user'):
            logs = logs.filter(user=form.cleaned_data['user'])
        if form.cleaned_data.get('action_type'):
            logs = logs.filter(action_type=form.cleaned_data['action_type'])
        if form.cleaned_data.get('module'):
            logs = logs.filter(module=form.cleaned_data['module'])
        if form.cleaned_data.get('date_from'):
            logs = logs.filter(created_at__date__gte=form.cleaned_data['date_from'])
        if form.cleaned_data.get('date_to'):
            logs = logs.filter(created_at__date__lte=form.cleaned_data['date_to'])
        if form.cleaned_data.get('is_success'):
            is_success = form.cleaned_data['is_success'] == 'true'
            logs = logs.filter(is_success=is_success)
    
    # Pagination
    paginator = Paginator(logs, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Statistiques
    total_logs = logs.count()
    success_logs = logs.filter(is_success=True).count()
    error_logs = total_logs - success_logs
    
    context = {
        'page_obj': page_obj,
        'form': form,
        'total_logs': total_logs,
        'success_logs': success_logs,
        'error_logs': error_logs,
    }
    
    return render(request, 'users/activity/activity_log.html', context)


@admin_required
def activity_log_detail_view(request, pk):
    """Détail d'une entrée du journal d'activité"""
    log = get_object_or_404(ActivityLog, pk=pk)
    return render(request, 'users/activity/activity_log_detail.html', {'log': log})


# ==================== Vues API/Ajax ====================
@login_required
def get_departments_ajax(request):
    """Récupérer les départements d'une entreprise (AJAX)"""
    company_id = request.GET.get('company_id')
    departments = Department.objects.filter(company_id=company_id)
    
    data = [{'id': d.id, 'name': d.name} for d in departments]
    return JsonResponse(data, safe=False)


@login_required
def get_services_ajax(request):
    """Récupérer les services d'un département (AJAX)"""
    department_id = request.GET.get('department_id')
    services = Service.objects.filter(department_id=department_id)
    
    data = [{'id': s.id, 'name': s.name} for s in services]
    return JsonResponse(data, safe=False)


@login_required
def mark_notification_read_ajax(request):
    """Marquer une notification comme lue (AJAX)"""
    if request.method == 'POST' and request.is_ajax():
        notification_id = request.POST.get('notification_id')
        try:
            notification = request.user.notifications.get(id=notification_id)
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save()
            return JsonResponse({'success': True})
        except:
            return JsonResponse({'success': False})
    return JsonResponse({'success': False})


# ==================== Vues de Gestion des Permissions ====================
@admin_required
def permission_management_view(request):
    """Gestion des permissions (admin seulement)"""
    # Récupérer tous les utilisateurs avec leurs permissions
    users = User.objects.filter(company=request.user.company).select_related('profile')
    
    # Récupérer tous les groupes
    from django.contrib.auth.models import Group
    groups = Group.objects.all()
    
    context = {
        'users': users,
        'groups': groups,
    }
    
    return render(request, 'users/permissions/permission_management.html', context)


@admin_required
def assign_group_ajax(request):
    """Assigner un groupe à un utilisateur (AJAX)"""
    if request.method == 'POST' and request.is_ajax():
        user_id = request.POST.get('user_id')
        group_id = request.POST.get('group_id')
        action = request.POST.get('action')  # 'add' ou 'remove'
        
        try:
            user = User.objects.get(id=user_id, company=request.user.company)
            group = Group.objects.get(id=group_id)
            
            if action == 'add':
                user.groups.add(group)
                # Log de l'activité
                ActivityLog.log_action(
                    user=request.user,
                    action_type=ActivityLog.ActionType.UPDATE,
                    module=ActivityLog.Module.USER_MANAGEMENT,
                    description=f"Ajout du groupe {group.name} à {user.get_full_name()}",
                    content_object=user,
                    request=request
                )
            elif action == 'remove':
                user.groups.remove(group)
                # Log de l'activité
                ActivityLog.log_action(
                    user=request.user,
                    action_type=ActivityLog.ActionType.UPDATE,
                    module=ActivityLog.Module.USER_MANAGEMENT,
                    description=f"Retrait du groupe {group.name} de {user.get_full_name()}",
                    content_object=user,
                    request=request
                )
            
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False})




@login_required
def no_permission_view(request):
    """Vue pour afficher la page d'absence de permission"""
    return render(request, 'leaves/no_permission.html')