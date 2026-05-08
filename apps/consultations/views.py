import logging
import json as json_module
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import HttpResponse

from apps.patients.models import Patient
from .models import Consultation
from .serializers import (
    ConsultationSerializer,
    ConsultationStatusSerializer,
    ConsultationUploadSerializer,
)
from .tasks import process_consultation, process_zoom_consultation
from .utils import create_zoom_meeting, create_recall_bot

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

    Body:
    {
        "patient_id": "uuid",
        "scheduled_at": "2026-05-10T14:00:00Z",
        "duration_minutes": 30,
        "notes": "optional"
    }

    Flow:
    1. Validate required fields
    2. Create Zoom meeting via Server-to-Server OAuth
    3. Schedule Recall.ai bot to join 2 minutes before start time
    4. Save all details to Consultation record
    5. Return join details immediately
    """
    from datetime import datetime, timedelta

    patient_id = request.data.get('patient_id')
    scheduled_at = request.data.get('scheduled_at')
    duration_minutes = int(request.data.get('duration_minutes', 30))
    notes = request.data.get('notes', '')

    if not patient_id or not scheduled_at:
        return Response(
            {'error': 'patient_id and scheduled_at are required.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    patient = get_object_or_404(Patient, id=patient_id, doctor=request.user)

    try:
        # Step 1: Create the Zoom meeting
        meeting_topic = (
            f"HelloDoc: Dr. {request.user.get_full_name() or request.user.username}"
            f" & {patient.name}"
        )
        zoom_data = create_zoom_meeting(
            topic=meeting_topic,
            start_time_iso=scheduled_at,
            duration_minutes=duration_minutes,
        )

        # Step 2: Schedule Recall.ai bot to join 2 minutes before start
        scheduled_dt = datetime.fromisoformat(scheduled_at.replace('Z', '+00:00'))
        bot_join_dt = scheduled_dt - timedelta(minutes=2)
        bot_join_iso = bot_join_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

        recall_data = create_recall_bot(
            join_url=zoom_data['join_url'],
            bot_name='HelloDoc AI',
            join_at_iso=bot_join_iso,
        )

        # Step 3: Save consultation with all Zoom + Recall.ai details
        consultation = Consultation.objects.create(
            doctor=request.user,
            patient=patient,
            source='zoom',
            status='scheduled',
            progress_step='Meeting created. AI bot will join automatically 2 minutes before start.',
            scheduled_at=scheduled_at,
            duration_minutes=duration_minutes,
            notes=notes,
            zoom_meeting_id=zoom_data['meeting_id'],
            zoom_join_url=zoom_data['join_url'],
            zoom_start_url=zoom_data['start_url'],
            zoom_password=zoom_data['password'],
            recall_bot_id=recall_data['bot_id'],
        )

        logger.info(
            f"Consultation {consultation.id} scheduled. "
            f"Zoom meeting: {zoom_data['meeting_id']} | "
            f"Recall bot: {recall_data['bot_id']} | "
            f"Bot joins at: {bot_join_iso}"
        )

        return Response({
            'id': str(consultation.id),
            'consultation_id': str(consultation.id),
            'status': consultation.status,
            'scheduled_at': scheduled_at,
            'zoom_join_url': zoom_data['join_url'],
            'zoom_link': zoom_data['join_url'],  # Frontend compatibility
            'zoom_password': zoom_data['password'],
            'zoom_meeting_id': zoom_data['meeting_id'],
            'recall_bot_id': recall_data['bot_id'],
            'bot_joins_at': bot_join_iso,
            'message': (
                f"Consultation scheduled. The HelloDoc AI will join the "
                f"Zoom call automatically at {bot_join_iso}."
            ),
        }, status=status.HTTP_201_CREATED)

    except Exception as exc:
        logger.error(f"Failed to schedule consultation: {exc}", exc_info=True)
        return Response(
            {'error': f'Failed to create meeting: {str(exc)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ─────────────────────────────────────────────────────────
# RECALL.AI WEBHOOK — Handles bot events from Zoom calls
# ─────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def recall_webhook(request):
    """
    POST /api/webhooks/recall/

    Recall.ai calls this when bot events occur during/after the Zoom call.
    No JWT auth — protected by HMAC signature verification instead.
    Must respond with 200 within 5 seconds. All heavy work goes to Celery.

    Events handled:
      bot.in_call_recording  → bot joined and is recording (update status)
      bot.done               → call ended, recording ready (trigger pipeline)
      bot.fatal_error        → bot failed to join (mark failed)
    """
    from .utils import verify_recall_signature

    # Verify Recall.ai signature
    signature = request.headers.get('X-Recall-Signature', '')
    if not verify_recall_signature(request.body, signature):
        logger.warning("Recall webhook rejected: invalid signature")
        return HttpResponse(status=401)

    try:
        payload = json_module.loads(request.body)
    except json_module.JSONDecodeError:
        logger.warning("Recall webhook rejected: invalid JSON body")
        return HttpResponse(status=400)

    event = payload.get('event', '')
    bot_id = payload.get('data', {}).get('bot', {}).get('id', '')

    logger.info(f"Recall webhook received: event={event} bot_id={bot_id}")

    if not bot_id:
        return HttpResponse(status=200)

    # Find the consultation linked to this bot
    try:
        consultation = Consultation.objects.get(recall_bot_id=bot_id)
    except Consultation.DoesNotExist:
        logger.warning(f"No consultation found for recall_bot_id: {bot_id}")
        return HttpResponse(status=200)  # Return 200 so Recall does not retry endlessly

    if event == 'bot.in_call_recording':
        consultation.status = 'in_progress'
        consultation.progress_step = 'AI is in the Zoom call and recording...'
        consultation.save(update_fields=['status', 'progress_step', 'updated_at'])

    elif event == 'bot.done':
        consultation.status = 'processing'
        consultation.progress_step = 'Call ended. Downloading recording...'
        consultation.save(update_fields=['status', 'progress_step', 'updated_at'])
        # Hand off to Celery — downloads recording then runs existing pipeline
        process_zoom_consultation.delay(str(consultation.id), bot_id)

    elif event == 'bot.fatal_error':
        error_msg = payload.get('data', {}).get('message', 'Recall.ai bot fatal error.')
        consultation.status = 'failed'
        consultation.error_message = error_msg
        consultation.progress_step = 'AI bot failed to join the call.'
        consultation.save(update_fields=['status', 'error_message', 'progress_step', 'updated_at'])
        logger.error(f"Recall bot fatal error for consultation {consultation.id}: {error_msg}")

    # Always return 200 immediately — Recall.ai retries on non-200
    return HttpResponse(status=200)
