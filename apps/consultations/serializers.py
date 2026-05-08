from rest_framework import serializers
from .models import Consultation


class ConsultationSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.name', read_only=True)
    zoom_link = serializers.CharField(source='zoom_join_url', read_only=True)

    class Meta:
        model = Consultation
        fields = [
            'id', 'patient', 'patient_name', 'source', 'status',
            'progress_step', 'zoom_meeting_id', 'zoom_join_url', 'zoom_link',
            'zoom_start_url', 'zoom_password', 'recall_bot_id', 'scheduled_at',
            'audio_file_name', 'duration_minutes', 'notes',
            'error_message', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'doctor', 'status', 'progress_step',
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
        allowed_types = ['audio/mpeg', 'audio/wav', 'audio/mp4', 'audio/x-m4a',
                         'video/mp4', 'audio/webm', 'application/octet-stream']
        allowed_extensions = ['.mp3', '.wav', '.m4a', '.mp4', '.webm']
        import os
        ext = os.path.splitext(value.name)[1].lower()
        if ext not in allowed_extensions:
            raise serializers.ValidationError(
                f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
            )
        # OpenAI Whisper API limit is 25MB; files larger than this will be compressed
        max_size = 500 * 1024 * 1024  # Accept up to 500MB; will compress if needed
        if value.size > max_size:
            raise serializers.ValidationError("File size must be under 500MB.")
        return value
