import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

INVITE_EXPIRY_DAYS = 7


class Household(models.Model):
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def member_count(self):
        return self.memberships.count()


class HouseholdMembership(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="membership",
    )
    household = models.ForeignKey(
        Household,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} → {self.household.name}"


class HouseholdInvitation(models.Model):
    household = models.ForeignKey(
        Household,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    email = models.EmailField()
    token = models.CharField(max_length=64, unique=True, db_index=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sent_invitations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    @property
    def is_valid(self):
        if self.accepted_at:
            return False
        return timezone.now() < self.created_at + timedelta(days=INVITE_EXPIRY_DAYS)

    def accept(self, user):
        HouseholdMembership.objects.create(user=user, household=self.household)
        self.accepted_at = timezone.now()
        self.save(update_fields=["accepted_at"])

    def __str__(self):
        return f"Invite to {self.household.name} for {self.email}"
