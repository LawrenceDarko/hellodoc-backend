from rest_framework import serializers
from .models import Consultation

ALLOWED_UPLOAD_CONTENT_TYPES = [
    'audio/mpeg',
    'audio/mp3',
    'audio/wav',
    'audio/x-wav',
    'audio/wave',
    'audio/webm',
    'audio/ogg',
    'audio/mp4',
    'audio/m4a',
    'audio/x-m4a',
    'video/mp4',
    'video/webm',
    'video/ogg',
]

ALLOWED_UPLOAD_EXTENSIONS = ['.mp3', '.wav', '.m4a', '.mp4', '.webm']


class ConsultationSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.name', read_only=True)
    zoom_link = serializers.CharField(source='zoom_join_url', read_only=True)

    class Meta:
        model = Consultation
        fields = [
            'id', 'patient', 'patient_name', 'source', 'status',
            'progress_step', 'progress_percent', 'zoom_meeting_id', 'zoom_join_url', 'zoom_link',
            'zoom_start_url', 'zoom_password', 'recall_bot_id', 'scheduled_at',
            'audio_file_name', 'duration_minutes', 'notes',
            'error_message', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'doctor', 'status', 'progress_step', 'progress_percent',
            'audio_file_name', 'error_message', 'created_at', 'updated_at'
        ]


class ConsultationStatusSerializer(serializers.ModelSerializer):
    """Lightweight serializer used by the frontend polling endpoint."""
    class Meta:
        model = Consultation
        fields = [
            'id',
            'status',
            'progress_step',
            'progress_percent',
            'error_message',
            'zoom_join_url',
            'zoom_password',
            'recall_bot_id',
        ]


class ConsultationUploadSerializer(serializers.Serializer):
    """Validates the multipart/form-data upload request."""
    patient_id = serializers.UUIDField()
    audio_file = serializers.FileField()
    consultation_date = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_audio_file(self, value):
        import os
        ext = os.path.splitext(value.name)[1].lower()
        if ext not in ALLOWED_UPLOAD_EXTENSIONS:
            raise serializers.ValidationError(
                f"Unsupported file type. Allowed: {', '.join(ALLOWED_UPLOAD_EXTENSIONS)}"
            )
        content_type = getattr(value, 'content_type', '')
        if content_type and content_type not in ALLOWED_UPLOAD_CONTENT_TYPES:
            raise serializers.ValidationError(
                f"Unsupported content type. Allowed: {', '.join(ALLOWED_UPLOAD_CONTENT_TYPES)}"
            )

        max_size = 100 * 1024 * 1024
        if value.size > max_size:
            raise serializers.ValidationError("File size must be under 100MB.")
        return value
