from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()
from .models import DoctorProfile


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'name']


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ['email', 'password', 'name']

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data['email'],
            email=validated_data['email'],
            password=validated_data['password'],
            name=validated_data.get('name', '')
        )


class DoctorProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = DoctorProfile
        fields = [
            'specialty',
            'template_preference',
            'custom_template_name',
            'example_note',
            'onboarding_completed',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']
