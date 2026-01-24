from django.urls import path, include
from django.contrib.auth import views as auth_views
from . import views

app_name = 'users'

urlpatterns = [
    # ==================== Authentification ====================
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Réinitialisation de mot de passe
    path('password-reset/', 
         auth_views.PasswordResetView.as_view(
             template_name='users/auth/password_reset.html',
             email_template_name='users/auth/password_reset_email.html',
             subject_template_name='users/auth/password_reset_subject.txt',
             success_url='/users/password-reset/done/'
         ), 
         name='password_reset'),
    path('password-reset/done/', 
         auth_views.PasswordResetDoneView.as_view(
             template_name='users/auth/password_reset_done.html'
         ), 
         name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(
             template_name='users/auth/password_reset_confirm.html',
             success_url='/users/password-reset-complete/'
         ), 
         name='password_reset_confirm'),
    path('password-reset-complete/', 
         auth_views.PasswordResetCompleteView.as_view(
             template_name='users/auth/password_reset_complete.html'
         ), 
         name='password_reset_complete'),
    
    # ==================== Dashboard ====================
    path('', views.dashboard, name='dashboard'),
    
    # ==================== Profil ====================
    path('profile/', views.profile_view, name='profile'),
    path('profile/change-password/', views.change_password_view, name='change_password'),
    
    # ==================== Gestion des Utilisateurs ====================
    path('users/', views.user_list_view, name='user_list'),
    path('users/create/', views.user_create_view, name='user_create'),
    path('users/<int:pk>/', views.user_detail_view, name='user_detail'),
    path('users/<int:pk>/edit/', views.user_update_view, name='user_update'),
    path('users/<int:pk>/delete/', views.user_delete_view, name='user_delete'),
    
    # ==================== Structure Organisationnelle ====================
    path('company/edit/', views.company_update_view, name='company_edit'),
    path('organization/structure/', views.organization_structure_view, name='organization_structure'),
    
    # Directions
    path('divisions/', views.division_list_view, name='division_list'),
    path('divisions/create/', views.division_create_view, name='division_create'),
    
    # Départements
    path('departments/', views.department_list_view, name='department_list'),
    path('departments/create/', views.department_create_view, name='department_create'),
    
    # Services
    path('services/', views.service_list_view, name='service_list'),
    path('services/create/', views.service_create_view, name='service_create'),
    
    # ==================== Workflows de Validation ====================
    path('workflows/', views.workflow_list_view, name='workflow_list'),
    path('workflows/create/', views.workflow_create_view, name='workflow_create'),
    path('workflows/<int:pk>/edit/', views.workflow_update_view, name='workflow_update'),
    path('workflows/<int:pk>/delete/', views.workflow_delete_view, name='workflow_delete'),
    
    # ==================== Journal d'Activité ====================
    path('activity-logs/', views.activity_log_view, name='activity_log'),
    path('activity-logs/<int:pk>/', views.activity_log_detail_view, name='activity_log_detail'),
    
    # ==================== Gestion des Permissions ====================
    path('permissions/', views.permission_management_view, name='permission_management'),
    
    # ==================== API/Ajax ====================
    path('ajax/get-departments/', views.get_departments_ajax, name='ajax_get_departments'),
    path('ajax/get-services/', views.get_services_ajax, name='ajax_get_services'),
    path('ajax/mark-notification-read/', views.mark_notification_read_ajax, name='ajax_mark_notification_read'),
    path('ajax/assign-group/', views.assign_group_ajax, name='ajax_assign_group'),
]