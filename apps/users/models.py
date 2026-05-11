from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255, blank=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return self.email


class DoctorProfile(models.Model):
    TEMPLATE_CHOICES = [
        ('soap', 'SOAP Note'),
        ('hp', 'H&P'),
        ('progress', 'Progress Note'),
        ('custom', 'Custom'),
    ]

    doctor = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    specialty = models.CharField(max_length=255, blank=True, default='')
    template_preference = models.CharField(
        max_length=20,
        choices=TEMPLATE_CHOICES,
        default='soap'
    )
    custom_template_name = models.CharField(max_length=255, blank=True, default='')
    example_note = models.TextField(
        blank=True,
        default='',
        help_text="De-identified example note used to personalise AI output style."
    )
    onboarding_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile — {self.doctor.email}"
