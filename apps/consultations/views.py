import logging
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404

from apps.patients.models import Patient
from .models import Consultation
from .serializers import (
    ConsultationSerializer,
    ConsultationStatusSerializer,
    ConsultationUploadSerializer,
)
from .tasks import process_consultation
from .utils import create_zoom_meeting

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# LIST & CREATE CONSULTATIONS
# ─────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def consultation_list(request):
    """
    GET /api/consultations/
    List all consultations for the authenticated doctor.
    Optional query param: ?patient=<uuid>
    Optional query param: ?status=scheduled,completed
    """
    qs = Consultation.objects.filter(doctor=request.user).select_related('patient')

    patient_id = request.query_params.get('patient')
    if patient_id:
        qs = qs.filter(patient_id=patient_id)

    status_filter = request.query_params.get('status')
    if status_filter:
        statuses = [s.strip() for s in status_filter.split(',')]
        qs = qs.filter(status__in=statuses)

    serializer = ConsultationSerializer(qs, many=True)
    return Response(serializer.data)


# ─────────────────────────────────────────────────────────
# UPLOAD ENDPOINT — The entry point into the pipeline
# ─────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_consultation(request):
    """
    POST /api/consultations/upload/

    Accepts multipart/form-data:
      - patient_id (UUID)
      - audio_file (file: mp3, wav, m4a, mp4)
      - consultation_date (date: YYYY-MM-DD)
      - notes (string, optional)

    Flow:
      1. Validate input
      2. Verify patient belongs to this doctor
      3. Save audio file to storage (Supabase S3 or local)
      4. Create Consultation record with status='pending'
      5. Fire Celery task: process_consultation.delay(consultation.id)
      6. Return consultation_id immediately — frontend will poll for status
    """
    serializer = ConsultationUploadSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    patient_id = serializer.validated_data['patient_id']
    audio_file = serializer.validated_data['audio_file']
    notes = serializer.validated_data.get('notes', '')

    # Ensure patient belongs to this doctor
    patient = get_object_or_404(Patient, id=patient_id, doctor=request.user)

    # Create the consultation record
    consultation = Consultation.objects.create(
        doctor=request.user,
        patient=patient,
        source='upload',
        status='pending',
        progress_step='Upload received, queuing for processing...',
        audio_file=audio_file,
        audio_file_name=audio_file.name,
        notes=notes,
    )

    # Fire the Celery pipeline task — non-blocking
    process_consultation.delay(str(consultation.id))

    logger.info(
        f"Consultation {consultation.id} created for patient {patient.name}. "
        f"Celery task queued."
    )

    return Response({
        'consultation_id': str(consultation.id),
        'status': consultation.status,
        'progress_step': consultation.progress_step,
        'message': 'File uploaded successfully. Processing has started.',
    }, status=status.HTTP_202_ACCEPTED)


# ─────────────────────────────────────────────────────────
# STATUS POLLING — Frontend calls this every 3 seconds
# ─────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def consultation_status(request, consultation_id):
    """
    GET /api/consultations/:id/status/

    Lightweight endpoint for frontend polling.
    Returns: { id, status, progress_step, error_message }

    Status values the frontend should handle:
      'pending'      → show step 1 active (Uploading)
      'transcribing' → show step 2 active (Transcribing)
      'analyzing'    → show step 3 active (Analyzing)
      'completed'    → stop polling, redirect to /consultations/:id
      'failed'       → stop polling, show error_message
    """
    consultation = get_object_or_404(
        Consultation, id=consultation_id, doctor=request.user
    )
    serializer = ConsultationStatusSerializer(consultation)
    return Response(serializer.data)


# ─────────────────────────────────────────────────────────
# CONSULTATION DETAIL
# ─────────────────────────────────────────────────────────

@api_view(['GET', 'DELETE'])
@permission_classes([IsAuthenticated])
def consultation_detail(request, consultation_id):
    """
    GET /api/consultations/:id/

    Returns full consultation metadata on GET.
    Deletes the consultation and its related report on DELETE.
    """
    consultation = get_object_or_404(
        Consultation, id=consultation_id, doctor=request.user
    )

    if request.method == 'DELETE':
        consultation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    return Response(ConsultationSerializer(consultation).data)


# ─────────────────────────────────────────────────────────
# SCHEDULE A ZOOM CONSULTATION (no file upload)
# ─────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def schedule_consultation(request):
    """
    POST /api/consultations/schedule/

    Body: { patient_id, scheduled_at, zoom_link, notes }

    Creates a scheduled Zoom consultation. No Celery task is fired here —
    the task will be triggered after the Zoom recording is uploaded.
    """
    patient_id = request.data.get('patient_id')
    scheduled_at = request.data.get('scheduled_at')
    zoom_link = request.data.get('zoom_link', '')
    notes = request.data.get('notes', '')

    if not patient_id or not scheduled_at:
        return Response(
            {'error': 'patient_id and scheduled_at are required.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    patient = get_object_or_404(Patient, id=patient_id, doctor=request.user)

    # If no zoom_link provided, attempt to create a meeting via Zoom API
    if not zoom_link:
        try:
            topic = f"Consultation: {patient.name} with Dr. {request.user.get_full_name() or request.user.username}"
            created_link = create_zoom_meeting(topic, scheduled_at)
            if created_link:
                zoom_link = created_link
        except Exception:
            logger.exception('Error creating Zoom meeting')

    consultation = Consultation.objects.create(
        doctor=request.user,
        patient=patient,
        source='zoom',
        status='pending',
        progress_step='Consultation scheduled',
        zoom_link=zoom_link,
        scheduled_at=scheduled_at,
        notes=notes,
    )

    return Response(ConsultationSerializer(consultation).data, status=status.HTTP_201_CREATED)
