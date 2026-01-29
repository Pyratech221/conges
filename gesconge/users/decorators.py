# leaves/decorators.py
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from functools import wraps
from django.utils.translation import gettext_lazy as _
from users.models import User
from django.contrib import messages

def hr_or_admin_required(view_func):
    """Décorateur pour les vues réservées aux RH et administrateurs"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('users:login')
        
        if not (request.user.is_hr or request.user.is_admin):
            messages.error(request, _("Vous n'avez pas les permissions nécessaires pour accéder à cette page."))
            return redirect('users:no_permission')  # Redirige vers une page HTML
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def manager_or_above_required(view_func):
    """Décorateur pour les managers et au-dessus"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('users:login')
        
        if not request.user.is_manager:
            messages.error(request, _("Vous n'avez pas les permissions de manager nécessaires pour accéder à cette page."))
            return redirect('users:no_permission')
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def raf_required(view_func):
    """Décorateur pour les responsables RAF (Absence/Formation)"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('users:login')
        
        if not request.user.is_raf:
            messages.error(request, _("Vous n'avez pas les permissions de responsable RAF nécessaires pour accéder à cette page."))
            return redirect('users:no_permission')
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def approver_required(view_func):
    """Décorateur pour les validateurs de congés"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('users:login')
        
        if not request.user.is_approver:
            messages.error(request, _("Vous n'avez pas les permissions de validation nécessaires pour accéder à cette page."))
            return redirect('users:no_permission')
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def company_member_required(view_func):
    """Décorateur pour s'assurer que l'utilisateur appartient à une entreprise"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('users:login')
        
        if not request.user.company:
            messages.error(request, _("Vous n'êtes affilié à aucune entreprise."))
            return redirect('users:no_permission')
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def ajax_login_required(view_func):
    """Décorateur pour les requêtes AJAX qui nécessitent une authentification"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                from django.http import JsonResponse
                return JsonResponse({'error': 'Authentication required'}, status=401)
            return redirect('users:login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def department_manager_required(view_func):
    """Décorateur pour les managers de département"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('users:login')
        
        if not (request.user.is_manager and 
               (request.user.managed_departments.exists() or 
                request.user.service and request.user.service.manager == request.user)):
            messages.error(request, _("Vous n'avez pas les permissions de manager de département."))
            return redirect('users:no_permission')
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def check_object_permission(model_class, permission_field='user', permission_check=None):
    """
    Décorateur générique pour vérifier les permissions sur un objet
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            obj_id = kwargs.get('pk')
            if obj_id:
                try:
                    obj = model_class.objects.get(pk=obj_id)
                    
                    if permission_check:
                        has_permission = permission_check(request.user, obj)
                    else:
                        has_permission = (
                            getattr(obj, permission_field) == request.user or
                            request.user.is_hr or
                            request.user.is_admin
                        )
                    
                    if not has_permission:
                        messages.error(request, _("Vous n'avez pas la permission d'accéder à cet objet."))
                        return redirect('users:no_permission')
                    
                    # Ajouter l'objet au contexte de la requête
                    request.obj = obj
                    
                except model_class.DoesNotExist:
                    messages.error(request, _("L'objet demandé n'existe pas."))
                    return redirect('users:no_permission')
            
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator