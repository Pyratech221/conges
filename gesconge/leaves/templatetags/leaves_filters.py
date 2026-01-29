from django import template
from django.utils import timezone
from django.db.models import Q
from ..models import LeaveApproval, Notification
import calendar as cal
from datetime import datetime,date
register = template.Library()


@register.filter
def is_read(queryset, value=True):
    """Filtrer les notifications par statut de lecture"""
    return queryset.filter(is_read=value)

@register.filter
def status(queryset, value):
    """Filtrer les approbations par statut"""
    return queryset.filter(status=value)

@register.filter
def leave_type__category(queryset, value):
    """Filtrer les soldes par catégorie de type de congé"""
    return queryset.filter(leave_type__category=value)

@register.filter
def length(queryset):
    """Retourner la longueur d'un queryset"""
    return len(queryset)

@register.filter
def first(queryset):
    """Retourner le premier élément d'un queryset"""
    return queryset.first()

@register.filter
def slice(queryset, value):
    """Trancher un queryset"""
    try:
        start, end = map(int, value.split(':'))
        return queryset[start:end]
    except:
        return queryset

@register.filter
def timesince(value):
    """Format timesince en français simplifié"""
    if not value:
        return ""
    
    now = timezone.now()
    diff = now - value
    
    if diff.days > 365:
        years = diff.days // 365
        return f"il y a {years} an{'s' if years > 1 else ''}"
    elif diff.days > 30:
        months = diff.days // 30
        return f"il y a {months} mois"
    elif diff.days > 0:
        return f"il y a {diff.days} jour{'s' if diff.days > 1 else ''}"
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f"il y a {hours} heure{'s' if hours > 1 else ''}"
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f"il y a {minutes} minute{'s' if minutes > 1 else ''}"
    else:
        return "à l'instant"

@register.filter
def group_by_type(leaves):
    """Grouper les congés par type"""
    from collections import defaultdict
    result = defaultdict(int)
    for leave in leaves:
        result[leave.leave_type.name] += 1
    return dict(result)

@register.filter
def group_by_status(leaves):
    """Grouper les congés par statut"""
    from collections import defaultdict
    result = defaultdict(int)
    for leave in leaves:
        result[leave.get_status_display()] += 1
    return dict(result)

@register.filter
def filter_by_status(queryset, status):
    """Filtrer un queryset par statut"""
    return queryset.filter(status=status)

@register.filter
def filter_by_type_category(queryset, category):
    """Filtrer par catégorie de type de congé"""
    return queryset.filter(leave_type__category=category)

@register.simple_tag
def get_unread_notifications_count(user):
    """Compter les notifications non lues"""
    return Notification.objects.filter(user=user, is_read=False).count()

@register.simple_tag
def get_pending_approvals_count(user):
    """Compter les approbations en attente"""
    return LeaveApproval.objects.filter(
        approver=user,
        status='pending'
    ).count()

@register.simple_tag
def get_user_balance(user, category='paid'):
    """Obtenir le solde d'un utilisateur pour une catégorie"""
    from ..models import LeaveBalance
    balance = LeaveBalance.objects.filter(
        user=user,
        leave_type__category=category,
        year=timezone.now().year
    ).first()
    return balance.remaining_days if balance else 0


@register.filter
def filter_by_priority(queryset, priority):
    """Filtrer par priorité"""
    try:
        return queryset.filter(priority=int(priority))
    except:
        return queryset
    
@register.filter
def filter_by_attr(queryset, args):
    """
    Filtrer un queryset ou liste d'objets par attribut et valeur.
    Usage dans le template: 
        {{ leave_types|filter_by_attr:"is_active,True"|length }}
    """
    try:
        attr, value = args.split(',')
        # Convertir "True"/"False" en bool
        if value.lower() == 'true':
            value = True
        elif value.lower() == 'false':
            value = False
        return [obj for obj in queryset if getattr(obj, attr, None) == value]
    except:
        return queryset 




@register.filter
def date_month(month):
    """Renvoie le nom français du mois"""
    months = [
        'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
        'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre'
    ]
    try:
        return months[int(month)-1]
    except (ValueError, IndexError):
        return ''


@register.filter
def filter_date_month(holidays, month):
    """
    Filtre la liste de jours fériés pour ne garder que ceux du mois donné.
    `holidays` doit être un queryset ou une liste d'objets avec un attribut `date`.
    """
    try:
        month = int(month)
        return [h for h in holidays if h.date.month == month]
    except (ValueError, AttributeError):
        return []


@register.filter
def concat(value, arg):
    value = '' if value in (None, '') else str(value)
    arg = '' if arg in (None, '') else str(arg)
    return value + arg


@register.filter
def days_in_month(month, year):
    try:
        month = int(month)
        year = int(year)
        return cal.monthrange(year, month)[1]
    except (ValueError, TypeError):
        return 0
    
@register.filter
def filter_date(holidays, date_str):
    """
    Filtre la liste des jours fériés pour ne garder que ceux dont la date correspond à date_str.
    date_str doit être au format 'YYYY-MM-DD'.
    Exemple : {{ holidays|filter_date:"2026-01-25" }}
    """
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        return [h for h in holidays if h.date == target_date]
    except Exception:
        return []    
    
@register.filter
def is_past(date_obj):
    """
    Retourne True si la date est passée par rapport à aujourd'hui.
    """
    if not date_obj:
        return False
    return date_obj < date.today()    


@register.filter
def days_until(date_obj):
    """Retourne le nombre de jours jusqu'à la date"""
    if not date_obj:
        return 0
    delta = date_obj - date.today()
    return delta.days if delta.days > 0 else 0 


@register.filter
def range_list(start, end):
    """Retourne une liste de nombres de start à end-1 (comme range Python)"""
    try:
        return list(range(int(start), int(end)))
    except (ValueError, TypeError):
        return []

@register.filter
def range_inclusive(start, end):
    """Retourne une liste de nombres de start à end inclus."""
    try:
        return list(range(int(start), int(end) + 1))
    except (ValueError, TypeError):
        return []
    
@register.filter
def first_list(value):
    """Retourne le premier élément d'une liste, ou None si vide"""
    try:
        return value[0]
    except (IndexError, TypeError):
        return None    


@register.filter
def filter_status(queryset, status):
    return queryset.filter(status=status)    


@register.filter
def times(number):
    """Retourne une liste de 0 à number-1 (similaire à range)"""
    return range(number)

@register.filter
def add(value, arg):
    """Addition"""
    try:
        return value + arg
    except:
        return value

@register.filter
def divisibleby(value, arg):
    """Vérifie si value est divisible par arg"""
    try:
        return value % arg == 0
    except:
        return False
    
@register.filter
def days_range(start, end):
    """Retourne une liste de jours de start à end"""
    return range(start, end + 1)    

@register.filter
def date_weekday(date_str):
    """Retourne le jour de la semaine (0=Dimanche, 1=Lundi, ... 6=Samedi)"""
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        return date_obj.weekday()  # 0=Lundi, 6=Dimanche dans Python
    except:
        return 0

@register.filter
def stringformat(value, format_str):
    """Format une chaîne"""
    return format_str % value

@register.filter
def modulo(value, arg):
    """Retourne le modulo"""
    return value % arg

@register.filter
def minus(value, arg):
    """Soustraction"""
    return value - arg


@register.filter
def first_day_offset(month, year):
    """Calcule le décalage pour le premier jour du mois (0=Lundi)"""
    try:
        import calendar
        # weekday() retourne 0=Lundi, 6=Dimanche
        first_weekday = calendar.weekday(int(year), int(month), 1)
        return first_weekday  # 0=Lundi, donc pas de décalage
    except:
        return 0



@register.filter
def first_weekday(month, year):
    """Retourne le jour de la semaine du 1er du mois (0=Lundi)"""
    try:
        import calendar
        # weekday() retourne 0=Lundi, 1=Mardi, ..., 6=Dimanche
        return calendar.weekday(int(year), int(month), 1)
    except:
        return 0    



@register.filter
def pad_month(month):
    """Ajoute un zéro devant le mois si nécessaire (1 → '01')"""
    try:
        return f"{int(month):02d}"
    except:
        return str(month).zfill(2)

@register.filter
def pad_day(day):
    """Ajoute un zéro devant le jour si nécessaire (1 → '01')"""
    try:
        return f"{int(day):02d}"
    except:
        return str(day).zfill(2)    