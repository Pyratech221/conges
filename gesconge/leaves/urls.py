# urls.py
from django.urls import path
from django.views.generic import RedirectView
from . import views

app_name = 'leaves'

urlpatterns = [
    # ==================== URLs des Congés ====================
    path('', views.leave_list_view, name='leave_list'),
    path('create/', views.leave_create_view, name='leave_create'),
    path('<int:pk>/', views.leave_detail_view, name='leave_detail'),
    path('<int:pk>/edit/', views.leave_update_view, name='leave_update'),
    path('<int:pk>/cancel/', views.leave_cancel_view, name='leave_cancel'),
    
    # ==================== URLs de Validation ====================
    path('approvals/', views.approval_list_view, name='approval_list'),
    path('approvals/<int:pk>/action/', views.approval_action_view, name='approval_action'),
    path('approvals/bulk/', views.bulk_approval_view, name='bulk_approval'),
    
    # ==================== URLs de Calendrier ====================
    path('calendar/', views.calendar_view, name='calendar'),
    path('calendar/events/', views.calendar_events_json, name='calendar_events_json'),
    
    # ==================== URLs de Solde ====================
    path('balance/', views.balance_view, name='balance'),
    path('balance/management/', views.balance_management_view, name='balance_management'),
    path('balance/adjust/<int:user_id>/', views.balance_adjust_view, name='balance_adjust'),
    
    # ==================== URLs de Rapport ====================
    path('reports/', views.report_list_view, name='report_list'),
    path('reports/create/', views.report_create_view, name='report_create'),
    path('reports/quick/', views.quick_report_view, name='quick_report'),
    path('reports/<int:pk>/download/', views.report_download_view, name='report_download'),
    
    # ==================== URLs d'Administration ====================
    # Types de congés
    path('admin/leave-types/', views.leavetype_list_view, name='leavetype_list'),
    path('admin/leave-types/create/', views.leavetype_create_view, name='leavetype_create'),
    path('admin/leave-types/<int:pk>/edit/', views.leavetype_update_view, name='leavetype_update'),
    path('admin/leave-types/<int:pk>/delete/', views.leavetype_delete_view, name='leavetype_delete'),
    
    # Jours fériés
    path('admin/holidays/', views.holiday_list_view, name='holiday_list'),
    path('admin/holidays/create/', views.holiday_create_view, name='holiday_create'),
    path('admin/holidays/<int:pk>/edit/', views.holiday_update_view, name='holiday_update'),
    path('admin/holidays/<int:pk>/delete/', views.holiday_delete_view, name='holiday_delete'),
    
    # ==================== URLs d'Import/Export ====================
    path('import/', views.import_data_view, name='import_data'),
    path('export/', views.export_data_view, name='export_data'),
    
    # ==================== URLs de Notification ====================
    path('notifications/', views.notification_list_view, name='notification_list'),
    path('notifications/mark-all-read/', views.mark_all_notifications_read_view, name='mark_all_read'),
    path('notifications/clear-all/', views.clear_all_notifications_view, name='clear_all'),
    
    # ==================== URLs d'API/JSON ====================
    path('api/balance/', views.api_leave_balance_json, name='api_balance'),
    path('api/pending-approvals/', views.api_pending_approvals_json, name='api_pending_approvals'),
    path('api/upcoming-leaves/', views.api_upcoming_leaves_json, name='api_upcoming_leaves'),
    
    # ==================== URLs de Redirection ====================
    path('dashboard/', RedirectView.as_view(pattern_name='users:dashboard'), name='dashboard'),
]