from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.db.models import Q, Sum, Count, Prefetch
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.conf import settings
from datetime import datetime, date, timedelta
import calendar
import json
import os
from io import BytesIO
import pandas as pd
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

from .models import (
    LeaveType, Holiday, LeaveRequest, LeaveApproval, LeaveBalance,
    Attendance, Report, Notification, LeaveDay
)
from .forms import (
    LeaveRequestForm, LeaveRequestDraftForm, LeaveApprovalForm, LeaveCancelForm,
    LeaveTypeForm, HolidayForm, LeaveBalanceAdjustForm, AttendanceForm,
    AttendanceValidationForm, ReportForm, QuickReportForm,
    LeaveRequestFilterForm, CalendarFilterForm, BulkLeaveApprovalForm,
    ImportDataForm
)
from users.models import User, Company, ActivityLog, Department, Service
from users.decorators import hr_or_admin_required, manager_or_above_required

# ==================== Helpers ====================
def calculate_working_days(start_date, end_date, company):
    """Calculer les jours ouvrables entre deux dates"""
    # Cette fonction devrait prendre en compte les jours fériés
    # Pour l'instant, calcul simple
    delta = end_date - start_date
    total_days = delta.days + 1
    
    # Soustraire les weekends (samedi=5, dimanche=6)
    working_days = 0
    for i in range(total_days):
        current_date = start_date + timedelta(days=i)
        if current_date.weekday() < 5:  # Lundi à Vendredi
            working_days += 1
    
    return working_days


def send_leave_notification(leave_request, notification_type, extra_context=None):
    """Envoyer une notification pour un congé"""
    from django.template.loader import render_to_string
    from django.core.mail import send_mail
    
    notification_templates = {
        'new_request': {
            'subject': _('Nouvelle demande de congé à valider'),
            'template': 'leaves/notifications/new_request.html',
        },
        'approved': {
            'subject': _('Votre congé a été approuvé'),
            'template': 'leaves/notifications/approved.html',
        },
        'rejected': {
            'subject': _('Votre congé a été rejeté'),
            'template': 'leaves/notifications/rejected.html',
        },
        'cancelled': {
            'subject': _('Demande de congé annulée'),
            'template': 'leaves/notifications/cancelled.html',
        },
        'approval_required': {
            'subject': _('Validation de congé requise'),
            'template': 'leaves/notifications/approval_required.html',
        },
    }
    
    if notification_type not in notification_templates:
        return
    
    template = notification_templates[notification_type]
    context = {
        'leave_request': leave_request,
        'user': leave_request.user,
    }
    if extra_context:
        context.update(extra_context)
    
    # Créer la notification dans la base de données
    notification = Notification.objects.create(
        user=leave_request.user,
        notification_type=notification_type,
        title=template['subject'],
        message=render_to_string(template['template'], context).strip(),
    )
    
    # Envoyer par email si configuré
    if leave_request.user.profile.email_notifications:
        try:
            send_mail(
                subject=template['subject'],
                message=notification.message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[leave_request.user.email],
                fail_silently=True,
            )
            notification.is_email_sent = True
            notification.save()
        except Exception as e:
            print(f"Erreur d'envoi d'email: {e}")


# ==================== Vues des Congés ====================
@login_required
def leave_list_view(request):
    """Liste des demandes de congé de l'utilisateur"""
    leaves = LeaveRequest.objects.filter(user=request.user).order_by('-created_at')
    
    # Filtrage
    form = LeaveRequestFilterForm(
        request.GET,
        company=request.user.company,
        current_user=request.user
    )
    
    if form.is_valid():
        if form.cleaned_data.get('status'):
            leaves = leaves.filter(status=form.cleaned_data['status'])
        if form.cleaned_data.get('leave_type'):
            leaves = leaves.filter(leave_type=form.cleaned_data['leave_type'])
        if form.cleaned_data.get('date_from'):
            leaves = leaves.filter(start_date__gte=form.cleaned_data['date_from'])
        if form.cleaned_data.get('date_to'):
            leaves = leaves.filter(end_date__lte=form.cleaned_data['date_to'])
    
    # Pagination
    paginator = Paginator(leaves, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Statistiques
    stats = {
        'total': leaves.count(),
        'pending': leaves.filter(status='pending').count(),
        'approved': leaves.filter(status='approved').count(),
        'rejected': leaves.filter(status='rejected').count(),
    }
    
    context = {
        'page_obj': page_obj,
        'form': form,
        'stats': stats,
    }
    
    return render(request, 'leaves/leave/leave_list.html', context)


@login_required
def leave_create_view(request):
    """Création d'une demande de congé"""
    if request.method == 'POST':
        if 'save_draft' in request.POST:
            form = LeaveRequestDraftForm(request.POST, request.FILES, 
                                        user=request.user, company=request.user.company)
            if form.is_valid():
                leave = form.save(commit=False)
                leave.user = request.user
                leave.status = 'draft'
                leave.save()
                
                # Log de l'activité
                ActivityLog.log_action(
                    user=request.user,
                    action_type=ActivityLog.ActionType.CREATE,
                    module=ActivityLog.Module.LEAVE_MANAGEMENT,
                    description=f"Création brouillon de congé {leave.leave_type.name}",
                    content_object=leave,
                    request=request
                )
                
                messages.success(request, _("Brouillon sauvegardé !"))
                return redirect('leaves:leave_list')
        else:
            form = LeaveRequestForm(request.POST, request.FILES, 
                                   user=request.user, company=request.user.company)
            if form.is_valid():
                leave = form.save(commit=False)
                leave.user = request.user
                leave.status = 'pending'
                leave.submitted_at = timezone.now()
                
                # Calculer les jours
                total_days = (leave.end_date - leave.start_date).days + 1
                leave.total_days = total_days
                leave.working_days = calculate_working_days(
                    leave.start_date, leave.end_date, request.user.company
                )
                
                leave.save()
                
                # Créer les approbations selon le workflow
                workflow = None  # À implémenter: trouver le workflow approprié
                if workflow:
                    # Créer les approbations selon les niveaux
                    pass
                else:
                    # Workflow par défaut: approbation directe du manager
                    if leave.leave_type.requires_approval:
                        LeaveApproval.objects.create(
                            leave_request=leave,
                            approver=request.user.service.manager if request.user.service else 
                                    request.user.department.manager if request.user.department else None,
                            approval_level=1,
                            status='pending'
                        )
                
                # Envoyer les notifications
                send_leave_notification(leave, 'new_request')
                
                # Log de l'activité
                ActivityLog.log_action(
                    user=request.user,
                    action_type=ActivityLog.ActionType.CREATE,
                    module=ActivityLog.Module.LEAVE_MANAGEMENT,
                    description=f"Soumission de congé {leave.leave_type.name}",
                    content_object=leave,
                    request=request
                )
                
                messages.success(request, _("Demande de congé envoyée avec succès !"))
                return redirect('leaves:leave_list')
    else:
        form = LeaveRequestForm(user=request.user, company=request.user.company)
    
    # Récupérer le solde disponible
    current_year = date.today().year
    balance = LeaveBalance.objects.filter(
        user=request.user,
        leave_type__category='paid',
        year=current_year
    ).first()
    
    context = {
        'form': form,
        'balance': balance,
    }
    
    return render(request, 'leaves/leave/leave_form.html', context)


@login_required
def leave_update_view(request, pk):
    """Modification d'une demande de congé"""
    leave = get_object_or_404(LeaveRequest, pk=pk, user=request.user)
    
    if leave.status not in ['draft', 'pending']:
        messages.error(request, _("Vous ne pouvez modifier que les demandes en brouillon ou en attente."))
        return redirect('leaves:leave_list')
    
    if request.method == 'POST':
        form = LeaveRequestForm(request.POST, request.FILES, instance=leave,
                               user=request.user, company=request.user.company)
        if form.is_valid():
            leave = form.save()
            
            # Mettre à jour le statut si c'était un brouillon
            if leave.status == 'draft' and 'submit' in request.POST:
                leave.status = 'pending'
                leave.submitted_at = timezone.now()
                leave.save()
                
                # Créer les approbations
                if leave.leave_type.requires_approval:
                    LeaveApproval.objects.create(
                        leave_request=leave,
                        approver=request.user.service.manager if request.user.service else 
                                request.user.department.manager if request.user.department else None,
                        approval_level=1,
                        status='pending'
                    )
                
                # Envoyer les notifications
                send_leave_notification(leave, 'new_request')
            
            # Log de l'activité
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.UPDATE,
                module=ActivityLog.Module.LEAVE_MANAGEMENT,
                description=f"Modification de congé {leave.leave_type.name}",
                content_object=leave,
                request=request
            )
            
            messages.success(request, _("Demande de congé mise à jour !"))
            return redirect('leaves:leave_list')
    else:
        form = LeaveRequestForm(instance=leave, user=request.user, company=request.user.company)
    
    context = {
        'form': form,
        'leave': leave,
    }
    
    return render(request, 'leaves/leave/leave_form.html', context)


@login_required
def leave_detail_view(request, pk):
    """Détail d'une demande de congé"""
    leave = get_object_or_404(LeaveRequest, pk=pk)
    
    # Vérifier les permissions
    if leave.user != request.user and not (request.user.is_hr or request.user.is_admin):
        # Vérifier si l'utilisateur est un validateur
        if not LeaveApproval.objects.filter(
            leave_request=leave,
            approver=request.user,
            status='pending'
        ).exists():
            messages.error(request, _("Vous n'avez pas accès à cette demande."))
            return redirect('leaves:leave_list')
    
    # Récupérer les approbations
    approvals = leave.approvals.all().order_by('approval_level')
    
    context = {
        'leave': leave,
        'approvals': approvals,
    }
    
    return render(request, 'leaves/leave/leave_detail.html', context)


@login_required
def leave_cancel_view(request, pk):
    """Annulation d'une demande de congé"""
    leave = get_object_or_404(LeaveRequest, pk=pk, user=request.user)
    
    if leave.status not in ['pending', 'approved']:
        messages.error(request, _("Vous ne pouvez annuler que les demandes en attente ou approuvées."))
        return redirect('leaves:leave_list')
    
    if request.method == 'POST':
        form = LeaveCancelForm(request.POST)
        if form.is_valid():
            old_status = leave.status
            leave.status = 'cancelled'
            leave.cancelled_at = timezone.now()
            leave.save()
            
            # Envoyer les notifications
            send_leave_notification(leave, 'cancelled', {
                'reason': form.cleaned_data['reason'],
                'old_status': old_status,
            })
            
            # Log de l'activité
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.DELETE,
                module=ActivityLog.Module.LEAVE_MANAGEMENT,
                description=f"Annulation de congé {leave.leave_type.name}",
                content_object=leave,
                request=request
            )
            
            messages.success(request, _("Congé annulé avec succès !"))
            return redirect('leaves:leave_list')
    else:
        form = LeaveCancelForm()
    
    context = {
        'form': form,
        'leave': leave,
    }
    
    return render(request, 'leaves/leave/leave_cancel.html', context)


# ==================== Vues de Validation ====================
@login_required
def approval_list_view(request):
    """Liste des demandes à valider"""
    if not request.user.is_approver and not request.user.is_manager:
        messages.error(request, _("Vous n'avez pas les permissions de validation."))
        return redirect('users:dashboard')
    
    # Récupérer les approbations en attente pour cet utilisateur
    approvals = LeaveApproval.objects.filter(
        approver=request.user,
        status='pending'
    ).select_related('leave_request', 'leave_request__user', 'leave_request__leave_type')
    
    # Récupérer également les demandes où l'utilisateur est manager direct
    if request.user.is_manager:
        # Trouver les employés sous sa responsabilité
        team_users = User.objects.filter(
            Q(service__manager=request.user) | 
            Q(department__manager=request.user)
        ).distinct()
        
        team_pending = LeaveRequest.objects.filter(
            user__in=team_users,
            status='pending',
            approvals__isnull=True  # Pas encore d'approbation créée
        )
        
        # Créer des objets d'approbation virtuels pour l'affichage
        for leave in team_pending:
            if not approvals.filter(leave_request=leave).exists():
                # Ceci est pour l'affichage seulement, pas sauvegardé
                approvals = list(approvals) + [LeaveApproval(
                    leave_request=leave,
                    approver=request.user,
                    approval_level=1,
                    status='pending'
                )]
    
    # Pagination
    paginator = Paginator(approvals, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'total_pending': len(approvals),
    }
    
    return render(request, 'leaves/approval/approval_list.html', context)


@login_required
def approval_action_view(request, pk):
    """Action de validation sur une demande"""
    leave = get_object_or_404(LeaveRequest, pk=pk)
    
    # Vérifier si l'utilisateur peut valider cette demande
    can_approve = False
    approval = None
    
    # Vérifier les approbations existantes
    approval = LeaveApproval.objects.filter(
        leave_request=leave,
        approver=request.user,
        status='pending'
    ).first()
    
    # Vérifier si c'est un manager direct
    if not approval and request.user.is_manager:
        if ((leave.user.service and leave.user.service.manager == request.user) or
            (leave.user.department and leave.user.department.manager == request.user)):
            can_approve = True
            # Créer l'approbation si elle n'existe pas
            approval, created = LeaveApproval.objects.get_or_create(
                leave_request=leave,
                approver=request.user,
                defaults={
                    'approval_level': 1,
                    'status': 'pending'
                }
            )
    
    if not approval:
        messages.error(request, _("Vous ne pouvez pas valider cette demande."))
        return redirect('leaves:approval_list')
    
    if request.method == 'POST':
        form = LeaveApprovalForm(request.POST, instance=approval, leave_request=leave)
        if form.is_valid():
            approval = form.save(commit=False)
            approval.signed_at = timezone.now()
            approval.signed_by = request.user
            approval.save()
            
            # Mettre à jour le statut de la demande
            if approval.status == 'approved':
                # Vérifier s'il y a d'autres niveaux de validation
                if leave.current_approval_level < 3:  # Maximum 3 niveaux
                    leave.current_approval_level += 1
                    leave.save()
                    
                    # Créer la prochaine approbation si nécessaire
                    # (à implémenter selon le workflow)
                else:
                    leave.status = 'approved'
                    leave.approved_at = timezone.now()
                    leave.save()
                    
                    # Mettre à jour le solde
                    if leave.leave_type.deduct_from_balance:
                        balance, created = LeaveBalance.objects.get_or_create(
                            user=leave.user,
                            leave_type=leave.leave_type,
                            year=leave.start_date.year,
                            defaults={'entitled_days': 0, 'used_days': 0}
                        )
                        balance.used_days += leave.working_days
                        balance.save()
                    
                    # Envoyer notification d'approbation
                    send_leave_notification(leave, 'approved')
            
            elif approval.status == 'rejected':
                leave.status = 'rejected'
                leave.rejected_at = timezone.now()
                leave.save()
                
                # Envoyer notification de rejet
                send_leave_notification(leave, 'rejected', {
                    'comments': approval.comments
                })
            
            # Log de l'activité
            action = 'approve' if approval.status == 'approved' else 'reject'
            ActivityLog.log_action(
                user=request.user,
                action_type=action,
                module=ActivityLog.Module.APPROVAL,
                description=f"{action.capitalize()} du congé {leave.leave_type.name} de {leave.user.get_full_name()}",
                content_object=leave,
                request=request
            )
            
            messages.success(request, _(f"Demande {approval.get_status_display().lower()} avec succès !"))
            return redirect('leaves:approval_list')
    else:
        form = LeaveApprovalForm(instance=approval, leave_request=leave)
    
    context = {
        'form': form,
        'leave': leave,
        'approval': approval,
    }
    
    return render(request, 'leaves/approval/approval_action.html', context)


@manager_or_above_required
def bulk_approval_view(request):
    """Validation en masse"""
    # Récupérer toutes les demandes en attente pour ce validateur
    available_requests = LeaveRequest.objects.filter(
        status='pending',
        approvals__approver=request.user,
        approvals__status='pending'
    ).distinct().select_related('user', 'leave_type')
    
    total_pending = available_requests.count()
    
    if request.method == 'POST':
        form = BulkLeaveApprovalForm(request.POST, approver=request.user)
        if form.is_valid():
            leave_requests = form.cleaned_data['leave_requests']
            action = form.cleaned_data['action']
            comments = form.cleaned_data['comments']
            
            processed_count = 0
            for leave in leave_requests:
                # Créer ou récupérer l'approbation
                approval, created = LeaveApproval.objects.get_or_create(
                    leave_request=leave,
                    approver=request.user,
                    defaults={
                        'approval_level': 1,
                        'status': 'pending'
                    }
                )
                
                # Appliquer l'action
                approval.status = action
                approval.comments = comments if action == 'rejected' else ''
                approval.signed_at = timezone.now()
                approval.signed_by = request.user
                approval.save()
                
                # Mettre à jour la demande
                if action == 'approved':
                    leave.status = 'approved'
                    leave.approved_at = timezone.now()
                    
                    # Mettre à jour le solde
                    if leave.leave_type.deduct_from_balance:
                        balance, created = LeaveBalance.objects.get_or_create(
                            user=leave.user,
                            leave_type=leave.leave_type,
                            year=leave.start_date.year,
                            defaults={'entitled_days': 0, 'used_days': 0}
                        )
                        balance.used_days += leave.working_days
                        balance.save()
                else:
                    leave.status = 'rejected'
                    leave.rejected_at = timezone.now()
                
                leave.save()
                
                # Envoyer notification
                notification_type = 'approved' if action == 'approved' else 'rejected'
                send_leave_notification(leave, notification_type, {
                    'comments': comments
                })
                
                processed_count += 1
            
            messages.success(request, _(f"{processed_count} demande(s) traitée(s) avec succès !"))
            return redirect('leaves:approval_list')
    else:
        form = BulkLeaveApprovalForm(approver=request.user)
    
    context = {
        'form': form,
        'available_requests': available_requests,
        'total_pending': total_pending,
    }
    
    return render(request, 'leaves/approval/bulk_approval.html', context)
#==================== Vues de Calendrier ====================
@login_required
def calendar_view(request):
    """Calendrier des congés"""
    form = CalendarFilterForm(
        request.GET,
        company=request.user.company,
        user=request.user
    )
    
    leaves = LeaveRequest.objects.filter(
        status='approved'
    ).select_related('user', 'leave_type')
    
    if form.is_valid():
        if form.cleaned_data.get('department'):
            leaves = leaves.filter(user__department=form.cleaned_data['department'])
        if form.cleaned_data.get('service'):
            leaves = leaves.filter(user__service=form.cleaned_data['service'])
        if form.cleaned_data.get('leave_type'):
            leaves = leaves.filter(leave_type=form.cleaned_data['leave_type'])
        if form.cleaned_data.get('show_only_team') and request.user.is_manager:
            # Filtrer pour n'afficher que l'équipe
            team_users = User.objects.filter(
                Q(service__manager=request.user) | 
                Q(department__manager=request.user)
            ).distinct()
            leaves = leaves.filter(user__in=team_users)
    
    view_type = form.cleaned_data.get('view_type', 'month') if form.is_valid() else 'month'
    
    # Préparer les données pour le calendrier
    calendar_data = []
    for leave in leaves:
        calendar_data.append({
            'id': leave.id,
            'title': f"{leave.user.get_full_name()} - {leave.leave_type.name}",
            'start': leave.start_date.isoformat(),
            'end': (leave.end_date + timedelta(days=1)).isoformat(),  # +1 pour inclusion
            'color': leave.leave_type.color,
            'textColor': '#ffffff',
            'url': f"/leaves/{leave.id}/",
        })
    
    context = {
        'form': form,
        'view_type': view_type,
        'calendar_data': json.dumps(calendar_data),
        'leave_types': LeaveType.objects.filter(company=request.user.company, is_active=True),
    }
    
    return render(request, 'leaves/calendar/calendar.html', context)


@login_required
def calendar_events_json(request):
    """API JSON pour les événements du calendrier"""
    start = request.GET.get('start')
    end = request.GET.get('end')
    
    leaves = LeaveRequest.objects.filter(
        status='approved',
        start_date__lte=end,
        end_date__gte=start
    ).select_related('user', 'leave_type')
    
    # Appliquer les filtres
    department_id = request.GET.get('department')
    service_id = request.GET.get('service')
    leave_type_id = request.GET.get('leave_type')
    
    if department_id:
        leaves = leaves.filter(user__department_id=department_id)
    if service_id:
        leaves = leaves.filter(user__service_id=service_id)
    if leave_type_id:
        leaves = leaves.filter(leave_type_id=leave_type_id)
    
    events = []
    for leave in leaves:
        events.append({
            'id': leave.id,
            'title': f"{leave.user.get_full_name()} - {leave.leave_type.name}",
            'start': leave.start_date.isoformat(),
            'end': (leave.end_date + timedelta(days=1)).isoformat(),
            'color': leave.leave_type.color,
            'textColor': '#ffffff',
            'extendedProps': {
                'user': leave.user.get_full_name(),
                'type': leave.leave_type.name,
                'status': leave.get_status_display(),
            }
        })
    
    return JsonResponse(events, safe=False)


# ==================== Vues de Solde ====================
from django.db.models import Sum
from datetime import date

@login_required
def balance_view(request):
    """Vue du solde de congés"""
    current_year = date.today().year

    balances = (
        LeaveBalance.objects
        .filter(user=request.user, year=current_year)
        .select_related('leave_type')
    )

    years = (
        LeaveBalance.objects
        .filter(user=request.user)
        .values_list('year', flat=True)
        .distinct()
        .order_by('-year')
    )

    # Calcul Python pour les propriétés
    total_remaining = sum(b.remaining_days for b in balances)

    context = {
        'balances': balances,
        'current_year': current_year,
        'years': years,
        'total_remaining': total_remaining,
    }

    return render(request, 'leaves/balance/balance.html', context)


@hr_or_admin_required
def balance_management_view(request):
    """Gestion des soldes (RH/Admin)"""
    users = User.objects.filter(company=request.user.company, is_active=True)
    
    # Filtrage par département/service
    department_id = request.GET.get('department')
    service_id = request.GET.get('service')
    
    if department_id:
        users = users.filter(department_id=department_id)
    if service_id:
        users = users.filter(service_id=service_id)
    
    # Calculer les totaux
    current_year = date.today().year
    user_balances = []
    low_balance_users = [
    ub for ub in user_balances if ub["total_remaining"] < 5
    ]
    for user in users:
        balances = LeaveBalance.objects.filter(user=user, year=current_year)

        paid_balance = balances.filter(leave_type__category='paid').first()
        sick_balance = balances.filter(leave_type__category='sick').first()

        total_entitled = sum(b.entitled_days for b in balances)
        total_used = sum(b.used_days for b in balances)
        total_remaining = total_entitled - total_used

        user_balances.append({
            'user': user,
            'balances': balances,
            'paid_balance': paid_balance,
            'sick_balance': sick_balance,
            'total_entitled': total_entitled,
            'total_used': total_used,
            'total_remaining': total_remaining,
        })
    
    context = {
        'user_balances': user_balances,
        'low_balance_users': low_balance_users,
        'current_year': current_year,
        'departments': Department.objects.filter(company=request.user.company),
        'services': Service.objects.filter(department__company=request.user.company),
    }
    
    return render(request, 'leaves/balance/balance_management.html', context)


@hr_or_admin_required
def balance_adjust_view(request, user_id):
    """Ajustement du solde d'un utilisateur"""
    user = get_object_or_404(User, pk=user_id, company=request.user.company)
    
    if request.method == 'POST':
        form = LeaveBalanceAdjustForm(request.POST, user=user, company=request.user.company)
        if form.is_valid():
            leave_type = form.cleaned_data['leave_type']
            year = form.cleaned_data['year']
            adjustment_type = form.cleaned_data['adjustment_type']
            amount = form.cleaned_data['amount']
            reason = form.cleaned_data['reason']
            
            # Récupérer ou créer le solde
            balance, created = LeaveBalance.objects.get_or_create(
                user=user,
                leave_type=leave_type,
                year=year,
                defaults={
                    'entitled_days': 0,
                    'used_days': 0,
                    'carried_over_days': 0,
                }
            )
            
            # Sauvegarder les anciennes valeurs pour le log
            old_data = {
                'entitled_days': float(balance.entitled_days),
                'used_days': float(balance.used_days),
                'carried_over_days': float(balance.carried_over_days),
            }
            
            # Appliquer l'ajustement
            if adjustment_type == 'add_entitled':
                balance.entitled_days += amount
            elif adjustment_type == 'subtract_entitled':
                balance.entitled_days = max(0, balance.entitled_days - amount)
            elif adjustment_type == 'add_used':
                balance.used_days += amount
            elif adjustment_type == 'subtract_used':
                balance.used_days = max(0, balance.used_days - amount)
            elif adjustment_type == 'add_carried':
                balance.carried_over_days += amount
            elif adjustment_type == 'subtract_carried':
                balance.carried_over_days = max(0, balance.carried_over_days - amount)
            elif adjustment_type == 'set_entitled':
                balance.entitled_days = amount
            elif adjustment_type == 'set_used':
                balance.used_days = amount
            elif adjustment_type == 'set_carried':
                balance.carried_over_days = amount
            
            balance.save()
            
            # Log de l'activité
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.UPDATE,
                module=ActivityLog.Module.BALANCE,
                description=f"Ajustement du solde de {user.get_full_name()} - {leave_type.name} ({year})",
                details={
                    'user': user.get_full_name(),
                    'leave_type': leave_type.name,
                    'year': year,
                    'adjustment_type': adjustment_type,
                    'amount': float(amount),
                    'reason': reason,
                    'old_data': old_data,
                    'new_data': {
                        'entitled_days': float(balance.entitled_days),
                        'used_days': float(balance.used_days),
                        'carried_over_days': float(balance.carried_over_days),
                    }
                },
                content_object=balance,
                request=request
            )
            
            messages.success(request, _("Solde ajusté avec succès !"))
            return redirect('leaves:balance_management')
    else:
        form = LeaveBalanceAdjustForm(user=user, company=request.user.company)
    
    # Récupérer les soldes actuels
    current_year = date.today().year
    balances = LeaveBalance.objects.filter(user=user, year=current_year).select_related('leave_type')
    
    context = {
        'form': form,
        'user': user,
        'balances': balances,
        'current_year': current_year,
    }
    
    return render(request, 'leaves/balance/balance_adjust.html', context)





@hr_or_admin_required
def bulk_balance_adjust_view(request):
    """Ajustement de solde en masse (RH/Admin)"""
    current_year = date.today().year
    users = User.objects.filter(
        company=request.user.company,
        is_active=True
    )

    if request.method == "POST":
        leave_type_id = request.POST.get("leave_type")
        year = int(request.POST.get("year", current_year))
        adjustment_type = request.POST.get("adjustment_type")
        amount = float(request.POST.get("amount", 0))
        reason = request.POST.get("reason", "")

        leave_type = get_object_or_404(
            LeaveType,
            id=leave_type_id,
            company=request.user.company
        )

        for user in users:
            balance, created = LeaveBalance.objects.get_or_create(
                user=user,
                leave_type=leave_type,
                year=year,
                defaults={
                    "entitled_days": 0,
                    "used_days": 0,
                    "carried_over_days": 0,
                }
            )

            if adjustment_type == "add_entitled":
                balance.entitled_days += amount
            elif adjustment_type == "subtract_entitled":
                balance.entitled_days = max(0, balance.entitled_days - amount)
            elif adjustment_type == "set_entitled":
                balance.entitled_days = amount

            balance.save()

        messages.success(
            request,
            "Ajustement en masse effectué avec succès."
        )
        return redirect("leaves:balance_management")

    context = {
        "current_year": current_year,
        "leave_types": LeaveType.objects.filter(
            company=request.user.company,
            is_active=True
        ),
    }

    return render(
        request,
        "leaves/balance/bulk_balance_adjust.html",
        context
    )














# ==================== Vues de Rapport ====================
@hr_or_admin_required
def report_list_view(request):
    """Liste des rapports générés"""
    reports = Report.objects.filter(company=request.user.company).order_by('-generated_at')

    pdf_count = reports.filter(output_format='pdf').count()
    excel_count = reports.filter(output_format='excel').count()
    total_size = sum(r.file_size or 0 for r in reports)
    
    # Pagination
    paginator = Paginator(reports, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
    'page_obj': page_obj,
    'pdf_count': pdf_count,
    'excel_count': excel_count,
    'total_size': total_size,
    }
    
    return render(request, 'leaves/reports/report_list.html', context)


@hr_or_admin_required
def report_create_view(request):
    """Création d'un rapport"""
    if request.method == 'POST':
        form = ReportForm(request.POST, company=request.user.company)
        if form.is_valid():
            report = form.save(commit=False)
            report.company = request.user.company
            report.generated_by = request.user
            
            # Générer le rapport
            report_data = generate_report_data(report)
            file_content = generate_report_file(report_data, report.output_format)
            
            # Sauvegarder le fichier
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"report_{report.report_type}_{timestamp}.{report.output_format}"
            
            report.file.save(filename, file_content)
            report.file_size = report.file.size
            report.save()
            
            # Log de l'activité
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.CREATE,
                module=ActivityLog.Module.REPORTING,
                description=f"Génération du rapport {report.name}",
                content_object=report,
                request=request
            )
            
            messages.success(request, _("Rapport généré avec succès !"))
            return redirect('leaves:report_list')
    else:
        form = ReportForm(company=request.user.company)
    
    context = {
        'form': form,
    }
    
    return render(request, 'leaves/reports/report_form.html', context)


@hr_or_admin_required
def quick_report_view(request):
    """Rapport rapide"""
    if request.method == 'POST':
        form = QuickReportForm(request.POST)
        if form.is_valid():
            report_type = form.cleaned_data['report_type']
            period = form.cleaned_data['period']
            output_format = form.cleaned_data['format']
            
            # Déterminer les dates
            today = date.today()
            start_date = None
            end_date = None
            
            if period == 'current_month':
                start_date = date(today.year, today.month, 1)
                end_date = today
            elif period == 'last_month':
                last_month = today.month - 1 if today.month > 1 else 12
                last_year = today.year if today.month > 1 else today.year - 1
                start_date = date(last_year, last_month, 1)
                end_date = date(last_year, last_month, calendar.monthrange(last_year, last_month)[1])
            elif period == 'current_quarter':
                quarter = (today.month - 1) // 3 + 1
                start_month = (quarter - 1) * 3 + 1
                end_month = start_month + 2
                start_date = date(today.year, start_month, 1)
                end_date = date(today.year, end_month, calendar.monthrange(today.year, end_month)[1])
            elif period == 'last_quarter':
                quarter = (today.month - 1) // 3 + 1
                if quarter == 1:
                    last_quarter = 4
                    last_year = today.year - 1
                else:
                    last_quarter = quarter - 1
                    last_year = today.year
                start_month = (last_quarter - 1) * 3 + 1
                end_month = start_month + 2
                start_date = date(last_year, start_month, 1)
                end_date = date(last_year, end_month, calendar.monthrange(last_year, end_month)[1])
            elif period == 'current_year':
                start_date = date(today.year, 1, 1)
                end_date = today
            elif period == 'custom':
                start_date = form.cleaned_data['custom_start']
                end_date = form.cleaned_data['custom_end']
            
            # Générer le rapport
            if report_type == 'monthly_summary':
                data = generate_monthly_summary(request.user.company, start_date, end_date)
            elif report_type == 'team_leave':
                data = generate_team_leave_report(request.user, start_date, end_date)
            elif report_type == 'balance_summary':
                data = generate_balance_summary(request.user.company, date.today().year)
            elif report_type == 'attendance_summary':
                data = generate_attendance_summary(request.user.company, start_date, end_date)
            
            # Créer le fichier
            filename = f"quick_report_{report_type}_{today.strftime('%Y%m%d')}.{output_format}"
            
            if output_format == 'pdf':
                response = generate_pdf_report(data, filename, report_type)
            elif output_format == 'excel':
                response = generate_excel_report(data, filename, report_type)
            elif output_format == 'html':
                # Afficher directement
                context = {
                    'data': data,
                    'report_type': report_type,
                    'start_date': start_date,
                    'end_date': end_date,
                    'generated_at': datetime.now(),
                }
                return render(request, 'leaves/reports/quick_report_display.html', context)
            
            # Log de l'activité
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.VIEW,
                module=ActivityLog.Module.REPORTING,
                description=f"Génération du rapport rapide {report_type}",
                request=request
            )
            
            return response
    
    else:
        form = QuickReportForm()
    
    context = {
        'form': form,
    }
    
    return render(request, 'leaves/reports/quick_report.html', context)


@login_required
def report_download_view(request, pk):
    """Téléchargement d'un rapport"""
    report = get_object_or_404(Report, pk=pk)
    
    # Vérifier les permissions
    if not (request.user.is_hr or request.user.is_admin):
        messages.error(request, _("Vous n'avez pas accès à ce rapport."))
        return redirect('users:dashboard')
    
    if not report.file:
        messages.error(request, _("Le fichier du rapport n'existe pas."))
        return redirect('leaves:report_list')
    
    # Log de l'activité
    ActivityLog.log_action(
        user=request.user,
        action_type=ActivityLog.ActionType.DOWNLOAD,
        module=ActivityLog.Module.REPORTING,
        description=f"Téléchargement du rapport {report.name}",
        content_object=report,
        request=request
    )
    
    # Déterminer le type MIME
    mime_types = {
        'pdf': 'application/pdf',
        'excel': 'application/vnd.ms-excel',
        'csv': 'text/csv',
        'html': 'text/html',
    }
    
    content_type = mime_types.get(report.output_format, 'application/octet-stream')
    
    response = FileResponse(report.file.open('rb'), content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{os.path.basename(report.file.name)}"'
    
    return response


# ==================== Vues d'Administration ====================
@hr_or_admin_required
def leavetype_list_view(request):
    """Liste des types de congés"""
    leave_types = LeaveType.objects.filter(company=request.user.company).order_by('name')
    
    context = {
        'leave_types': leave_types,
    }
    
    return render(request, 'leaves/admin/leavetype_list.html', context)


@hr_or_admin_required
def leavetype_create_view(request):
    """Création d'un type de congé"""
    if request.method == 'POST':
        form = LeaveTypeForm(request.POST, company=request.user.company)
        if form.is_valid():
            leave_type = form.save(commit=False)
            leave_type.company = request.user.company
            leave_type.save()
            
            # Log de l'activité
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.CREATE,
                module=ActivityLog.Module.SETTINGS,
                description=f"Création du type de congé {leave_type.name}",
                content_object=leave_type,
                request=request
            )
            
            messages.success(request, _("Type de congé créé avec succès !"))
            return redirect('leaves:leavetype_list')
    else:
        form = LeaveTypeForm(company=request.user.company)
    
    context = {
        'form': form,
    }
    
    return render(request, 'leaves/admin/leavetype_form.html', context)


@hr_or_admin_required
def leavetype_update_view(request, pk):
    """Modification d'un type de congé"""
    leave_type = get_object_or_404(LeaveType, pk=pk, company=request.user.company)
    
    if request.method == 'POST':
        form = LeaveTypeForm(request.POST, instance=leave_type, company=request.user.company)
        if form.is_valid():
            form.save()
            
            # Log de l'activité
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.UPDATE,
                module=ActivityLog.Module.SETTINGS,
                description=f"Modification du type de congé {leave_type.name}",
                content_object=leave_type,
                request=request
            )
            
            messages.success(request, _("Type de congé mis à jour !"))
            return redirect('leaves:leavetype_list')
    else:
        form = LeaveTypeForm(instance=leave_type, company=request.user.company)
    
    context = {
        'form': form,
        'leave_type': leave_type,
    }
    
    return render(request, 'leaves/admin/leavetype_form.html', context)


@hr_or_admin_required
def leavetype_delete_view(request, pk):
    """Suppression d'un type de congé"""
    leave_type = get_object_or_404(LeaveType, pk=pk, company=request.user.company)
    
    if request.method == 'POST':
        # Vérifier s'il y a des demandes associées
        if LeaveRequest.objects.filter(leave_type=leave_type).exists():
            messages.error(request, _(
                "Impossible de supprimer ce type de congé car il est utilisé par des demandes existantes. "
                "Vous pouvez le désactiver à la place."
            ))
            return redirect('leaves:leavetype_list')
        
        leave_type.delete()
        
        # Log de l'activité
        ActivityLog.log_action(
            user=request.user,
            action_type=ActivityLog.ActionType.DELETE,
            module=ActivityLog.Module.SETTINGS,
            description=f"Suppression du type de congé {leave_type.name}",
            request=request
        )
        
        messages.success(request, _("Type de congé supprimé avec succès !"))
        return redirect('leaves:leavetype_list')
    
    context = {
        'leave_type': leave_type,
    }
    
    return render(request, 'leaves/admin/leavetype_delete.html', context)


from django.db import models

@hr_or_admin_required
def holiday_list_view(request):
    """Liste des jours fériés"""
    current_year = date.today().year
    holidays = Holiday.objects.filter(
        company=request.user.company,
        is_active=True
    ).order_by('date')
    
    # Filtrer par année
    try:
        year = int(request.GET.get('year', current_year))
    except (ValueError, TypeError):
        year = current_year
    if year:
        holidays = holidays.filter(
            models.Q(date__year=year) | models.Q(is_recurring=True)
        )
        
    try:
        selected_year = int(request.GET.get('year', current_year))
    except (ValueError, TypeError):
        selected_year = current_year    
    
    context = {
        'holidays': holidays,
        'current_year': current_year,
        'selected_year': int(year) if year else current_year,
        'years': range(current_year - 5, current_year + 6),
        'months': range(1, 13),
        'selected_year': selected_year,
    }
    
    return render(request, 'leaves/admin/holiday_list.html', context)


@hr_or_admin_required
def holiday_duplicate(request, pk):
    holiday = get_object_or_404(
        Holiday,
        pk=pk,
        company=request.user.company
    )

    if request.method == "POST":
        try:
            new_year = int(request.POST.get("new_year"))
        except (TypeError, ValueError):
            messages.error(request, "Année invalide")
            return redirect("leaves:holiday_list")

        new_date = holiday.date.replace(year=new_year)

        Holiday.objects.create(
            company=holiday.company,
            name=holiday.name,
            date=new_date,
            description=holiday.description,
            is_recurring=holiday.is_recurring,
            is_active=holiday.is_active,
        )

        messages.success(
            request,
            f'Jour férié "{holiday.name}" dupliqué pour {new_year}'
        )

    return redirect("leaves:holiday_list")


@hr_or_admin_required
def holiday_create_view(request):
    """Création d'un jour férié"""
    if request.method == 'POST':
        form = HolidayForm(request.POST)
        if form.is_valid():
            holiday = form.save(commit=False)
            holiday.company = request.user.company
            holiday.save()
            
            # Log de l'activité
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.CREATE,
                module=ActivityLog.Module.SETTINGS,
                description=f"Création du jour férié {holiday.name}",
                content_object=holiday,
                request=request
            )
            
            messages.success(request, _("Jour férié créé avec succès !"))
            return redirect('leaves:holiday_list')
    else:
        form = HolidayForm()
    
    context = {
        'form': form,
    }
    
    return render(request, 'leaves/admin/holiday_form.html', context)


@hr_or_admin_required
def holiday_update_view(request, pk):
    """Modification d'un jour férié"""
    holiday = get_object_or_404(Holiday, pk=pk, company=request.user.company)
    
    if request.method == 'POST':
        form = HolidayForm(request.POST, instance=holiday)
        if form.is_valid():
            form.save()
            
            # Log de l'activité
            ActivityLog.log_action(
                user=request.user,
                action_type=ActivityLog.ActionType.UPDATE,
                module=ActivityLog.Module.SETTINGS,
                description=f"Modification du jour férié {holiday.name}",
                content_object=holiday,
                request=request
            )
            
            messages.success(request, _("Jour férié mis à jour !"))
            return redirect('leaves:holiday_list')
    else:
        form = HolidayForm(instance=holiday)
    
    context = {
        'form': form,
        'holiday': holiday,
    }
    
    return render(request, 'leaves/admin/holiday_form.html', context)


@hr_or_admin_required
def holiday_delete_view(request, pk):
    """Suppression d'un jour férié"""
    holiday = get_object_or_404(Holiday, pk=pk, company=request.user.company)
    
    if request.method == 'POST':
        holiday.delete()
        
        # Log de l'activité
        ActivityLog.log_action(
            user=request.user,
            action_type=ActivityLog.ActionType.DELETE,
            module=ActivityLog.Module.SETTINGS,
            description=f"Suppression du jour férié {holiday.name}",
            request=request
        )
        
        messages.success(request, _("Jour férié supprimé avec succès !"))
        return redirect('leaves:holiday_list')
    
    context = {
        'holiday': holiday,
    }
    
    return render(request, 'leaves/admin/holiday_delete.html', context)


# ==================== Vues d'Import/Export ====================
@hr_or_admin_required
def import_data_view(request):
    """Import de données"""
    if request.method == 'POST':
        form = ImportDataForm(request.POST, request.FILES)
        if form.is_valid():
            import_type = form.cleaned_data['import_type']
            data_file = request.FILES['data_file']
            update_existing = form.cleaned_data['update_existing']
            
            try:
                if import_type == 'users':
                    count = import_users(data_file, request.user.company, update_existing)
                    message = _(f"{count} utilisateurs importés avec succès.")
                elif import_type == 'leave_balances':
                    count = import_leave_balances(data_file, request.user.company, update_existing)
                    message = _(f"{count} soldes de congés importés avec succès.")
                elif import_type == 'holidays':
                    count = import_holidays(data_file, request.user.company, update_existing)
                    message = _(f"{count} jours fériés importés avec succès.")
                elif import_type == 'attendance':
                    count = import_attendance(data_file, request.user.company, update_existing)
                    message = _(f"{count} présences importées avec succès.")
                
                messages.success(request, message)
                
                # Log de l'activité
                ActivityLog.log_action(
                    user=request.user,
                    action_type=ActivityLog.ActionType.IMPORT,
                    module=ActivityLog.Module.SETTINGS,
                    description=f"Import de données: {import_type}",
                    request=request
                )
                
                return redirect('leaves:import_data')
            
            except Exception as e:
                messages.error(request, _(f"Erreur lors de l'import: {str(e)}"))
    
    else:
        form = ImportDataForm()
    
    context = {
        'form': form,
    }
    
    return render(request, 'leaves/import_export/import_data.html', context)


@hr_or_admin_required
def export_data_view(request):
    """Export de données"""
    export_type = request.GET.get('type', 'leave_requests')
    
    # Définir les dates par défaut
    end_date = date.today()
    start_date = end_date - timedelta(days=30)
    
    if export_type == 'leave_requests':
        queryset = LeaveRequest.objects.filter(
            user__company=request.user.company,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).select_related('user', 'leave_type')
        
        # Préparer les données
        data = []
        for leave in queryset:
            data.append({
                'Employé': leave.user.get_full_name(),
                'Type de congé': leave.leave_type.name,
                'Date début': leave.start_date,
                'Date fin': leave.end_date,
                'Statut': leave.get_status_display(),
                'Jours': leave.total_days,
                'Créé le': leave.created_at.date(),
            })
        
        filename = f"export_conges_{date.today().strftime('%Y%m%d')}.csv"
        return export_to_csv(data, filename)
    
    elif export_type == 'leave_balances':
        current_year = date.today().year
        queryset = LeaveBalance.objects.filter(
            user__company=request.user.company,
            year=current_year
        ).select_related('user', 'leave_type')
        
        data = []
        for balance in queryset:
            data.append({
                'Employé': balance.user.get_full_name(),
                'Type de congé': balance.leave_type.name,
                'Année': balance.year,
                'Jours acquis': balance.entitled_days,
                'Jours utilisés': balance.used_days,
                'Jours en attente': balance.pending_days,
                'Jours reportés': balance.carried_over_days,
                'Jours restants': balance.remaining_days,
            })
        
        filename = f"export_soldes_{current_year}_{date.today().strftime('%Y%m%d')}.csv"
        return export_to_csv(data, filename)
    
    elif export_type == 'attendance':
        end_date = date.today()
        start_date = end_date - timedelta(days=90)
        
        queryset = Attendance.objects.filter(
            user__company=request.user.company,
            start_datetime__date__gte=start_date,
            start_datetime__date__lte=end_date
        ).select_related('user')
        
        data = []
        for attendance in queryset:
            data.append({
                'Employé': attendance.user.get_full_name(),
                'Type': attendance.get_attendance_type_display(),
                'Titre': attendance.title,
                'Date début': attendance.start_datetime,
                'Date fin': attendance.end_datetime,
                'Lieu': attendance.location,
                'Validé': 'Oui' if attendance.is_validated else 'Non',
            })
        
        filename = f"export_presences_{date.today().strftime('%Y%m%d')}.csv"
        return export_to_csv(data, filename)
    
    messages.error(request, _("Type d'export non supporté."))
    return redirect('users:dashboard')


# ==================== Vues de Notification ====================
@login_required
def notification_list_view(request):
    """Liste des notifications"""

    base_qs = Notification.objects.filter(
        user=request.user
    ).order_by('-created_at')

    # Stats (AVANT pagination)
    unread_count = base_qs.filter(is_read=False).count()
    read_count = base_qs.filter(is_read=True).count()
    important_count = base_qs.filter(priority=2).count()
    urgent_count = base_qs.filter(priority=3).count()

    # Marquer comme lues (optionnel : à discuter UX)
    if unread_count > 0:
        base_qs.filter(is_read=False).update(
            is_read=True,
            read_at=timezone.now()
        )

    # Pagination
    paginator = Paginator(base_qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'unread_count': unread_count,
        'read_count': read_count,
        'important_count': important_count,
        'urgent_count': urgent_count,
    }

    return render(
        request,
        'leaves/notifications/notification_list.html',
        context
    )


@login_required
@require_http_methods(["POST"])
def mark_all_notifications_read_view(request):
    """Marquer toutes les notifications comme lues"""
    notifications = Notification.objects.filter(user=request.user, is_read=False)
    count = notifications.count()
    
    if count > 0:
        notifications.update(is_read=True, read_at=timezone.now())
        messages.success(request, _(f"{count} notifications marquées comme lues."))
    else:
        messages.info(request, _("Aucune notification non lue."))
    
    return redirect('leaves:notification_list')


@login_required
@require_http_methods(["POST"])
def clear_all_notifications_view(request):
    """Supprimer toutes les notifications lues"""
    notifications = Notification.objects.filter(user=request.user, is_read=True)
    count = notifications.count()
    
    notifications.delete()
    
    if count > 0:
        messages.success(request, _(f"{count} notifications supprimées."))
    else:
        messages.info(request, _("Aucune notification à supprimer."))
    
    return redirect('leaves:notification_list')


# ==================== Vues d'API/JSON ====================
@login_required
def api_leave_balance_json(request):
    """API JSON pour le solde de congés"""
    current_year = date.today().year
    balances = LeaveBalance.objects.filter(
        user=request.user,
        year=current_year
    ).select_related('leave_type')
    
    data = []
    for balance in balances:
        data.append({
            'leave_type': balance.leave_type.name,
            'leave_type_id': balance.leave_type.id,
            'entitled_days': float(balance.entitled_days),
            'used_days': float(balance.used_days),
            'pending_days': float(balance.pending_days),
            'carried_over_days': float(balance.carried_over_days),
            'remaining_days': float(balance.remaining_days),
            'color': balance.leave_type.color,
        })
    
    return JsonResponse({'balances': data, 'year': current_year})


@login_required
def api_pending_approvals_json(request):
    """API JSON pour les approbations en attente"""
    if not request.user.is_approver and not request.user.is_manager:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    approvals = LeaveApproval.objects.filter(
        approver=request.user,
        status='pending'
    ).select_related('leave_request', 'leave_request__user', 'leave_request__leave_type')
    
    data = []
    for approval in approvals:
        data.append({
            'id': approval.id,
            'leave_request_id': approval.leave_request.id,
            'employee': approval.leave_request.user.get_full_name(),
            'leave_type': approval.leave_request.leave_type.name,
            'start_date': approval.leave_request.start_date.isoformat(),
            'end_date': approval.leave_request.end_date.isoformat(),
            'days': float(approval.leave_request.total_days),
            'submitted_at': approval.leave_request.submitted_at.isoformat() if approval.leave_request.submitted_at else None,
            'approval_level': approval.approval_level,
            'urgency': 'high' if (date.today() - approval.leave_request.start_date).days <= 2 else 'normal',
        })
    
    return JsonResponse({'approvals': data, 'count': len(data)})


@login_required
def api_upcoming_leaves_json(request):
    """API JSON pour les prochains congés"""
    upcoming_days = 30
    today = date.today()
    future_date = today + timedelta(days=upcoming_days)
    
    leaves = LeaveRequest.objects.filter(
        user__company=request.user.company,
        status='approved',
        start_date__gte=today,
        start_date__lte=future_date
    ).select_related('user', 'leave_type').order_by('start_date')
    
    # Filtrer pour l'équipe si manager
    if request.user.is_manager and not request.user.is_hr and not request.user.is_admin:
        team_users = User.objects.filter(
            Q(service__manager=request.user) | 
            Q(department__manager=request.user)
        ).distinct()
        leaves = leaves.filter(user__in=team_users)
    
    data = []
    for leave in leaves:
        data.append({
            'id': leave.id,
            'employee': leave.user.get_full_name(),
            'leave_type': leave.leave_type.name,
            'start_date': leave.start_date.isoformat(),
            'end_date': leave.end_date.isoformat(),
            'days': float(leave.total_days),
            'color': leave.leave_type.color,
            'is_own': leave.user == request.user,
        })
    
    return JsonResponse({'leaves': data, 'count': len(data)})


# ==================== Fonctions d'Aide ====================
def generate_report_data(report):
    """Générer les données pour un rapport"""
    leaves = LeaveRequest.objects.filter(
        user__company=report.company,
        created_at__date__gte=report.start_date,
        created_at__date__lte=report.end_date
    )
    
    # Appliquer les filtres
    if report.departments.exists():
        leaves = leaves.filter(user__department__in=report.departments.all())
    if report.services.exists():
        leaves = leaves.filter(user__service__in=report.services.all())
    if report.users.exists():
        leaves = leaves.filter(user__in=report.users.all())
    if report.leave_types.exists():
        leaves = leaves.filter(leave_type__in=report.leave_types.all())
    
    leaves = leaves.select_related('user', 'leave_type')
    
    data = {
        'report': report,
        'leaves': leaves,
        'summary': {
            'total': leaves.count(),
            'approved': leaves.filter(status='approved').count(),
            'pending': leaves.filter(status='pending').count(),
            'rejected': leaves.filter(status='rejected').count(),
            'total_days': sum(float(leave.total_days) for leave in leaves if leave.total_days),
        }
    }
    
    return data
def generate_report_file(data, output_format, report_type):
    """Générer le fichier de rapport selon le format"""
    
    if output_format == 'pdf':
        return generate_pdf_report(data, report_type)
    
    elif output_format == 'excel':
        return generate_excel_report(data, report_type)
    
    elif output_format == 'csv':
        return generate_csv_report(data, report_type)
    
    elif output_format == 'html':
        return generate_html_report(data, report_type)
    
    else:
        raise ValueError(f"Format non supporté: {output_format}")
def generate_csv_report(data, report_type):
    """Générer un rapport CSV"""
    import csv
    from io import StringIO, BytesIO
    
    output = StringIO()
    writer = csv.writer(output, delimiter=';')
    
    if report_type == 'leave_summary':
        writer.writerow(['Employé', 'Matricule', 'Type de congé', 'Date début', 'Date fin', 
                        'Jours', 'Statut', 'Créé le'])
        for leave in data.get('leaves', []):
            writer.writerow([
                leave.user.get_full_name(),
                leave.user.employee_id or '',
                leave.leave_type.name,
                leave.start_date.strftime('%d/%m/%Y'),
                leave.end_date.strftime('%d/%m/%Y'),
                leave.total_days,
                leave.get_status_display(),
                leave.created_at.strftime('%d/%m/%Y %H:%M')
            ])
    
    elif report_type == 'balance_summary':
        writer.writerow(['Employé', 'Matricule', 'Type de congé', 'Année', 
                        'Jours acquis', 'Jours utilisés', 'Jours restants'])
        for balance in data.get('balances', []):
            writer.writerow([
                balance.user.get_full_name(),
                balance.user.employee_id or '',
                balance.leave_type.name,
                balance.year,
                balance.entitled_days,
                balance.used_days,
                balance.remaining_days
            ])
    
    # Convertir en BytesIO
    csv_content = output.getvalue()
    return BytesIO(csv_content.encode('utf-8-sig'))


def generate_html_report(data, report_type):
    """Générer un rapport HTML (pour prévisualisation)"""
    from io import BytesIO
    import weasyprint
    from django.template.loader import render_to_string
    from django.http import HttpResponse
    
    # Générer le HTML
    context = {
        'data': data,
        'report_type': report_type,
        'generated_at': timezone.now(),
    }
    
    html_string = render_to_string('leaves/reports/report_template.html', context)
    
    # Convertir en PDF avec WeasyPrint
    html = weasyprint.HTML(string=html_string)
    pdf = html.write_pdf()
    
    return BytesIO(pdf)
def generate_pdf_report(data, filename, report_type):
    """Générer un rapport PDF"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    
    styles = getSampleStyleSheet()
    story = []
    
    # Titre
    title = Paragraph(f"Rapport: {report_type}", styles['Title'])
    story.append(title)
    
    # Informations
    info = Paragraph(f"Généré le: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal'])
    story.append(info)
    
    # Tableau de données
    if report_type == 'monthly_summary':
        table_data = [['Employé', 'Type', 'Début', 'Fin', 'Jours', 'Statut']]
        for leave in data['leaves']:
            table_data.append([
                leave.user.get_full_name(),
                leave.leave_type.name,
                leave.start_date.strftime('%d/%m/%Y'),
                leave.end_date.strftime('%d/%m/%Y'),
                str(leave.total_days),
                leave.get_status_display()
            ])
    
    elif report_type == 'balance_summary':
        table_data = [['Employé', 'Type', 'Acquis', 'Utilisés', 'Restants']]
        for balance in data['balances']:
            table_data.append([
                balance.user.get_full_name(),
                balance.leave_type.name,
                str(balance.entitled_days),
                str(balance.used_days),
                str(balance.remaining_days)
            ])
    
    table = Table(table_data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 12),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    
    story.append(table)
    
    # Résumé
    if 'summary' in data:
        summary = Paragraph(f"<br/><b>Résumé:</b> Total: {data['summary']['total']} demandes, "
                          f"Approuvées: {data['summary']['approved']}, "
                          f"En attente: {data['summary']['pending']}", styles['Normal'])
        story.append(summary)
    
    doc.build(story)
    
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


def generate_excel_report(data, filename, report_type):
    """Générer un rapport Excel"""
    if report_type == 'monthly_summary':
        df_data = []
        for leave in data['leaves']:
            df_data.append({
                'Employé': leave.user.get_full_name(),
                'Type de congé': leave.leave_type.name,
                'Date début': leave.start_date,
                'Date fin': leave.end_date,
                'Jours': leave.total_days,
                'Statut': leave.get_status_display(),
                'Créé le': leave.created_at.date(),
            })
    
    elif report_type == 'balance_summary':
        df_data = []
        for balance in data['balances']:
            df_data.append({
                'Employé': balance.user.get_full_name(),
                'Type de congé': balance.leave_type.name,
                'Année': balance.year,
                'Jours acquis': balance.entitled_days,
                'Jours utilisés': balance.used_days,
                'Jours en attente': balance.pending_days,
                'Jours reportés': balance.carried_over_days,
                'Jours restants': balance.remaining_days,
            })
    
    df = pd.DataFrame(df_data)
    
    with BytesIO() as buffer:
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Rapport', index=False)
            
            # Ajuster la largeur des colonnes
            worksheet = writer.sheets['Rapport']
            for column in worksheet.columns:
                max_length = 0
                column = [cell for cell in column]
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(cell.value)
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column[0].column_letter].width = adjusted_width
        
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response


def export_to_csv(data, filename):
    """Exporter des données en CSV"""
    if not data:
        return HttpResponse(_("Aucune donnée à exporter."), content_type='text/plain')
    
    # Créer le DataFrame
    df = pd.DataFrame(data)
    
    # Créer la réponse
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    # Écrire le CSV
    df.to_csv(response, index=False, encoding='utf-8-sig')
    
    return response


def import_users(data_file, company, update_existing):
    """Importer des utilisateurs"""
    # Implémentation de l'import d'utilisateurs
    # À adapter selon le format du fichier
    return 0


def import_leave_balances(data_file, company, update_existing):
    """Importer des soldes de congés"""
    # Implémentation de l'import des soldes
    return 0


def import_holidays(data_file, company, update_existing):
    """Importer des jours fériés"""
    # Implémentation de l'import des jours fériés
    return 0


def import_attendance(data_file, company, update_existing):
    """Importer des présences"""
    # Implémentation de l'import des présences
    return 0


def generate_monthly_summary(company, start_date, end_date):
    """Générer un résumé mensuel"""
    leaves = LeaveRequest.objects.filter(
        user__company=company,
        start_date__gte=start_date,
        start_date__lte=end_date
    ).select_related('user', 'leave_type')
    
    return {
        'leaves': leaves,
        'summary': {
            'total': leaves.count(),
            'approved': leaves.filter(status='approved').count(),
            'pending': leaves.filter(status='pending').count(),
            'rejected': leaves.filter(status='rejected').count(),
            'total_days': sum(float(leave.total_days) for leave in leaves if leave.total_days),
        },
        'start_date': start_date,
        'end_date': end_date,
    }


def generate_team_leave_report(manager, start_date, end_date):
    """Générer un rapport de congés de l'équipe"""
    # Trouver l'équipe
    team_users = User.objects.filter(
        Q(service__manager=manager) | 
        Q(department__manager=manager)
    ).distinct()
    
    leaves = LeaveRequest.objects.filter(
        user__in=team_users,
        start_date__gte=start_date,
        start_date__lte=end_date
    ).select_related('user', 'leave_type')
    
    return {
        'leaves': leaves,
        'team_users': team_users,
        'summary': {
            'total_employees': team_users.count(),
            'total_leaves': leaves.count(),
            'approved_leaves': leaves.filter(status='approved').count(),
            'pending_leaves': leaves.filter(status='pending').count(),
        },
    }


def generate_balance_summary(company, year):
    """Générer un rapport de synthèse des soldes"""
    balances = LeaveBalance.objects.filter(
        user__company=company,
        year=year
    ).select_related('user', 'leave_type')
    
    # Regrouper par utilisateur
    user_balances = {}
    for balance in balances:
        if balance.user not in user_balances:
            user_balances[balance.user] = []
        user_balances[balance.user].append(balance)
    
    return {
        'balances': balances,
        'user_balances': user_balances,
        'year': year,
        'summary': {
            'total_users': len(user_balances),
            'total_balance_types': balances.values('leave_type').distinct().count(),
        },
    }


def generate_attendance_summary(company, start_date, end_date):
    """Générer un rapport de synthèse des présences"""
    attendances = Attendance.objects.filter(
        user__company=company,
        start_datetime__date__gte=start_date,
        start_datetime__date__lte=end_date
    ).select_related('user')
    
    return {
        'attendances': attendances,
        'summary': {
            'total': attendances.count(),
            'workshops': attendances.filter(attendance_type='workshop').count(),
            'trainings': attendances.filter(attendance_type='training').count(),
            'meetings': attendances.filter(attendance_type='meeting').count(),
            'validated': attendances.filter(is_validated=True).count(),
        },
        'start_date': start_date,
        'end_date': end_date,
    }            