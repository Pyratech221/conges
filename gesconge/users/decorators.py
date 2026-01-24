# leaves/decorators.py
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from functools import wraps
from django.utils.translation import gettext_lazy as _
from users.models import User

def hr_or_admin_required(view_func):
    """Décorateur pour les vues réservées aux RH et administrateurs"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('users:login')
        
        if not (request.user.is_hr or request.user.is_admin):
            raise PermissionDenied(_("Vous n'avez pas les permissions nécessaires pour accéder à cette page."))
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def manager_or_above_required(view_func):
    """Décorateur pour les managers et au-dessus"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('users:login')
        
        if not request.user.is_manager:
            raise PermissionDenied(_("Vous n'avez pas les permissions de manager nécessaires pour accéder à cette page."))
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def raf_required(view_func):
    """Décorateur pour les responsables RAF (Absence/Formation)"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('users:login')
        
        if not request.user.is_raf:
            raise PermissionDenied(_("Vous n'avez pas les permissions de responsable RAF nécessaires pour accéder à cette page."))
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def approver_required(view_func):
    """Décorateur pour les validateurs de congés"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('users:login')
        
        if not request.user.is_approver:
            raise PermissionDenied(_("Vous n'avez pas les permissions de validation nécessaires pour accéder à cette page."))
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def company_member_required(view_func):
    """Décorateur pour s'assurer que l'utilisateur appartient à une entreprise"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('users:login')
        
        if not request.user.company:
            raise PermissionDenied(_("Vous n'êtes affilié à aucune entreprise."))
        
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
            raise PermissionDenied(_("Vous n'avez pas les permissions de manager de département."))
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def check_object_permission(model_class, permission_field='user', permission_check=None):
    """
    Décorateur générique pour vérifier les permissions sur un objet
    
    Args:
        model_class: Classe du modèle
        permission_field: Champ à vérifier (par défaut 'user')
        permission_check: Fonction personnalisée de vérification
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
                        raise PermissionDenied(_("Vous n'avez pas la permission d'accéder à cet objet."))
                    
                    # Ajouter l'objet au contexte de la requête
                    request.obj = obj
                    
                except model_class.DoesNotExist:
                    raise PermissionDenied(_("L'objet demandé n'existe pas."))
            
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator