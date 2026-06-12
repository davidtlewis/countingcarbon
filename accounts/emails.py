from django.core.mail import send_mail
from django.urls import reverse


def send_invitation_email(request, invitation):
    accept_url = request.build_absolute_uri(
        reverse("accounts:invite_accept", kwargs={"token": invitation.token})
    )
    household_name = invitation.household.name
    inviter_email = invitation.invited_by.email if invitation.invited_by else "a member"

    subject = f'You\'re invited to join "{household_name}" on CountingCarbon'
    body = (
        f"Hi,\n\n"
        f"{inviter_email} has invited you to share a carbon footprint tracker "
        f'for "{household_name}" on CountingCarbon.\n\n'
        f"Click the link below to accept the invitation:\n"
        f"{accept_url}\n\n"
        f"This link expires in 7 days.\n\n"
        f"If you didn't expect this email, you can ignore it.\n\n"
        f"-- CountingCarbon"
    )

    send_mail(
        subject=subject,
        message=body,
        from_email=None,  # uses DEFAULT_FROM_EMAIL
        recipient_list=[invitation.email],
        fail_silently=False,
    )
