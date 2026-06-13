from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .emails import send_invitation_email
from .models import Household, HouseholdInvitation, HouseholdMembership

User = get_user_model()

SESSION_INVITE_KEY = "pending_invite_token"


# ── Account ──────────────────────────────────────────────────────────────────


@login_required
def account_detail(request):
    return render(request, "accounts/account.html")


@login_required
def account_delete(request):
    if request.method == "POST":
        user = request.user
        try:
            membership = user.membership
            household = membership.household
            is_last = household.member_count == 1
        except HouseholdMembership.DoesNotExist:
            is_last = False
            household = None

        logout(request)
        if is_last and household:
            household.delete()  # cascades membership, invitations, entries
        user.delete()
        messages.success(request, "Your account has been deleted.")
        return redirect("home")

    # GET — check whether they're the last member so the template can warn them
    try:
        membership = request.user.membership
        is_last = membership.household.member_count == 1
    except HouseholdMembership.DoesNotExist:
        is_last = False

    return render(
        request, "accounts/account_delete_confirm.html", {"is_last_member": is_last}
    )


# ── Onboarding ────────────────────────────────────────────────────────────────


@login_required
def onboarding(request):
    # Already in a household — shouldn't be here
    try:
        request.user.membership
        return redirect("accounts:household")
    except HouseholdMembership.DoesNotExist:
        pass

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            return render(
                request, "accounts/onboarding.html", {"error": "Please enter a name."}
            )
        household = Household.objects.create(name=name)
        HouseholdMembership.objects.create(user=request.user, household=household)
        messages.success(request, f"Welcome! “{household.name}” is all set up.")
        return redirect("accounts:household")

    return render(request, "accounts/onboarding.html")


# ── Household settings ────────────────────────────────────────────────────────


@login_required
def household_settings(request):
    try:
        membership = request.user.membership
    except HouseholdMembership.DoesNotExist:
        return redirect("onboarding")

    household = membership.household
    members = household.memberships.select_related("user").order_by("joined_at")
    pending_invites = household.invitations.filter(accepted_at=None).order_by(
        "-created_at"
    )

    return render(
        request,
        "accounts/household.html",
        {
            "household": household,
            "members": members,
            "pending_invites": pending_invites,
        },
    )


@login_required
def household_invite(request):
    if request.method != "POST":
        return redirect("accounts:household")

    try:
        membership = request.user.membership
    except HouseholdMembership.DoesNotExist:
        return redirect("onboarding")

    household = membership.household
    email = request.POST.get("email", "").strip().lower()

    if not email:
        messages.error(request, "Please enter an email address.")
        return redirect("accounts:household")

    # Already a member?
    if User.objects.filter(
        email__iexact=email, membership__household=household
    ).exists():
        messages.error(request, f"{email} is already a member of this household.")
        return redirect("accounts:household")

    # Already a member of a different household?
    if User.objects.filter(email__iexact=email).exclude(membership=None).exists():
        messages.error(request, f"{email} already belongs to another household.")
        return redirect("accounts:household")

    # Invalidate any existing pending invite for this email+household
    HouseholdInvitation.objects.filter(
        household=household, email__iexact=email, accepted_at=None
    ).delete()

    invitation = HouseholdInvitation.objects.create(
        household=household,
        email=email,
        invited_by=request.user,
    )
    send_invitation_email(request, invitation)
    messages.success(request, f"Invitation sent to {email}.")
    return redirect("accounts:household")


def invite_accept(request, token):
    invitation = get_object_or_404(HouseholdInvitation, token=token)

    if not invitation.is_valid:
        return render(
            request, "accounts/invite_invalid.html", {"reason": "expired_or_used"}
        )

    if not request.user.is_authenticated:
        # Store token in session so the signal can pick it up after login
        request.session[SESSION_INVITE_KEY] = token

        # Send to signup if they don't have an account yet, otherwise login
        from allauth.account.models import EmailAddress

        has_account = EmailAddress.objects.filter(
            email__iexact=invitation.email
        ).exists()
        if has_account:
            return redirect(f"/accounts/login/?next=/accounts/invite/{token}/")
        return redirect(f"/accounts/signup/?next=/accounts/invite/{token}/")

    # Authenticated user
    try:
        request.user.membership
        messages.error(request, "You already belong to a household.")
        return redirect("accounts:household")
    except HouseholdMembership.DoesNotExist:
        pass

    if request.method == "POST":
        invitation.accept(request.user)
        messages.success(request, f'You\'ve joined "{invitation.household.name}".')
        return redirect("accounts:household")

    return render(request, "accounts/invite_accept.html", {"invitation": invitation})


# ── Leave / delete household ──────────────────────────────────────────────────


@login_required
def household_leave(request):
    try:
        membership = request.user.membership
    except HouseholdMembership.DoesNotExist:
        return redirect("onboarding")

    household = membership.household
    is_last = household.member_count == 1

    if request.method == "POST":
        if is_last:
            # Last member — delete the whole household
            household.delete()
            messages.success(request, "Your household has been deleted.")
        else:
            membership.delete()
            messages.success(request, f'You\'ve left "{household.name}".')
        return redirect("home")

    return render(
        request,
        "accounts/household_leave_confirm.html",
        {"household": household, "is_last_member": is_last},
    )
