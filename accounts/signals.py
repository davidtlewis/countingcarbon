from allauth.account.signals import user_logged_in
from django.dispatch import receiver

from .models import HouseholdInvitation, HouseholdMembership
from .views import SESSION_INVITE_KEY


@receiver(user_logged_in)
def accept_pending_invite(sender, request, user, **kwargs):
    token = request.session.pop(SESSION_INVITE_KEY, None)
    if not token:
        return

    try:
        invitation = HouseholdInvitation.objects.get(token=token, accepted_at=None)
    except HouseholdInvitation.DoesNotExist:
        return

    if not invitation.is_valid:
        return

    # Don't join if already in a household
    try:
        user.membership
        return
    except HouseholdMembership.DoesNotExist:
        pass

    invitation.accept(user)
