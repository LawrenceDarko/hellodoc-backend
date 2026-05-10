import json
import logging
import tempfile
import os
import subprocess

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from openai import OpenAI
from redis import Redis

logger = logging.getLogger(__name__)

# OpenAI Whisper API file size limit
WHISPER_MAX_SIZE_BYTES = 25 * 1024 * 1024  # 25MB
WHISPER_SAFE_SIZE_BYTES = 20 * 1024 * 1024  # Leave headroom for multipart overhead
WHISPER_CHUNK_SECONDS = 600  # 10 minutes per segment when chunking long recordings
WHISPER_MAX_DURATION_SECONDS = 60 * 60


def get_openai_client():
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def update_status(consultation, status, step='', progress_percent=None):
    """Helper to update consultation status and save."""
    consultation.status = status
    consultation.progress_step = step
    update_fields = ['status', 'progress_step', 'updated_at']
    if progress_percent is not None:
        consultation.progress_percent = max(0, min(100, int(progress_percent)))
        update_fields.append('progress_percent')
    consultation.save(update_fields=update_fields)


def log_openai_usage(response, label):
    usage = getattr(response, 'usage', None)
    if not usage:
        logger.info("OpenAI usage unavailable for %s", label)
        return

    logger.info(
        "OpenAI usage for %s: prompt_tokens=%s completion_tokens=%s total_tokens=%s",
        label,
        getattr(usage, 'prompt_tokens', None),
        getattr(usage, 'completion_tokens', None),
        getattr(usage, 'total_tokens', None),
    )


def get_audio_duration_seconds(audio_path):
    cmd = [
        'ffprobe',
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise Exception(f"ffprobe duration check failed: {result.stderr}")
    return float(result.stdout.strip())


def enforce_daily_transcription_limit(consultation, duration_seconds):
    duration_minutes = duration_seconds / 60
    cap = getattr(settings, 'TRANSCRIPTION_DAILY_MINUTE_CAP', 120)
    redis_client = Redis.from_url(settings.CELERY_BROKER_URL)
    today = timezone.now().date().isoformat()
    key = f"transcription_minutes:{consultation.doctor_id}:{today}"
    total = redis_client.incrbyfloat(key, duration_minutes)
    redis_client.expire(key, 60 * 60 * 48)

    if total > cap:
        redis_client.incrbyfloat(key, -duration_minutes)
        raise Exception(
            f"Daily transcription limit exceeded. Requested {duration_minutes:.1f} minutes; "
            f"cap is {cap} minutes/day."
        )

    logger.info(
        "Transcription minutes for user %s on %s: %.1f/%.1f",
        consultation.doctor_id,
        today,
        total,
        cap,
    )


# ─────────────────────────────────────────────────────────
# MASTER TASK — chains all steps, called immediately after upload
# ─────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def process_consultation(self, consultation_id):
    """
    Master pipeline task. Runs all steps in sequence.
    Flow:
      1. Transcribe audio with Whisper
      2. Generate doctor's note from chunked transcript
      3. Generate SOAP note from doctor's note
      4. Generate differential diagnosis
      5. Generate scan recommendations
    """
    from apps.consultations.models import Consultation

    try:
        consultation = Consultation.objects.get(id=consultation_id)
    except Consultation.DoesNotExist:
        logger.error(f"Consultation {consultation_id} not found")
        return

    try:
        # STEP 1: Transcribe audio with Whisper
        raw_transcript = step_transcribe(consultation)

        # STEP 2: Generate doctor's note from chunked transcript (no diarization)
        doctors_note = step_generate_doctors_note(consultation, raw_transcript)

        # STEP 3: Generate SOAP note from doctor's note
        step_generate_soap(consultation, doctors_note)

        # STEP 4: Generate differential diagnosis from doctor's note
        diagnosis_payload = step_generate_diagnosis(consultation, doctors_note)

        # STEP 5: Generate scan recommendations unless the note lacks enough detail
        if diagnosis_payload.get('insufficient_information'):
            update_status(consultation, 'completed', 'Report ready', 100)
            logger.info(
                f"Consultation {consultation_id} completed without diagnosis/scans: {diagnosis_payload.get('insufficient_reason', '')}"
            )
            return

        step_generate_scans(consultation, diagnosis_payload.get('diagnoses', []))

        # All done
        update_status(consultation, 'completed', 'Report ready', 100)
        logger.info(f"Consultation {consultation_id} fully processed.")

    except Exception as exc:
        logger.error(f"Pipeline failed for {consultation_id}: {exc}", exc_info=True)
        consultation.status = 'failed'
        consultation.error_message = str(exc)
        consultation.save(update_fields=['status', 'error_message', 'updated_at'])
        raise


# ─────────────────────────────────────────────────────────
# STEP 1 — Transcribe with OpenAI Whisper
# ─────────────────────────────────────────────────────────

def compress_audio(input_path, output_path, target_bitrate='64k'):
    """
    Compress audio file to reduce size for Whisper API (25MB limit).
    Uses ffmpeg with lower bitrate to reduce file size while maintaining intelligibility.
    """
    try:
        logger.info(f"Compressing audio from {input_path} to bitrate {target_bitrate}")
        
        # Use ffmpeg to compress the audio
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-b:a', target_bitrate,
            '-q:a', '9',
            '-y',  # Overwrite output file
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode != 0:
            raise Exception(f"ffmpeg compression failed: {result.stderr}")
        
        output_size = os.path.getsize(output_path)
        logger.info(f"Compressed audio size: {output_size / (1024*1024):.2f}MB")
        return output_path
    except Exception as e:
        logger.error(f"Audio compression failed: {e}")
        raise Exception(f"Failed to compress audio: {e}")


def build_compressed_audio_path(source_path, suffix, label):
    base_path = source_path[: -len(suffix)] if suffix and source_path.endswith(suffix) else os.path.splitext(source_path)[0]
    return f"{base_path}_{label}.mp3"


def segment_audio_for_whisper(source_path):
    """
    Split a large audio file into smaller mp3 chunks for Whisper.
    Each chunk is re-encoded at a low bitrate so it stays well below the request limit.
    """
    output_dir = tempfile.mkdtemp(prefix='whisper_chunks_')
    output_pattern = os.path.join(output_dir, 'chunk_%03d.mp3')

    cmd = [
        'ffmpeg',
        '-i', source_path,
        '-vn',
        '-map', '0:a:0',
        '-c:a', 'libmp3lame',
        '-b:a', '64k',
        '-f', 'segment',
        '-segment_time', str(WHISPER_CHUNK_SECONDS),
        '-reset_timestamps', '1',
        '-y',
        output_pattern,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise Exception(f"ffmpeg segmentation failed: {result.stderr}")

    chunk_paths = sorted(
        os.path.join(output_dir, name)
        for name in os.listdir(output_dir)
        if name.endswith('.mp3')
    )

    if not chunk_paths:
        raise Exception('No audio chunks were generated for transcription.')

    return output_dir, chunk_paths


def transcribe_audio_path(client, audio_path):
    with open(audio_path, 'rb') as audio_file:
        transcript_response = client.audio.transcriptions.create(
            model='whisper-1',
            file=audio_file,
            response_format='verbose_json',
            language='en',
        )

    log_openai_usage(transcript_response, 'whisper transcription')
    return transcript_response.text


def parse_json_array_payload(content, label, item_keys=None):
    """
    Extract a JSON array from a model response.
    The response may be an array, a JSON object containing an array value,
    or a JSON string wrapping either of those shapes.
    """
    if content is None:
        raise ValueError(f"{label} response content was empty.")

    def parse_candidate(candidate):
        if isinstance(candidate, list):
            if all(isinstance(item, dict) for item in candidate):
                return candidate
            if len(candidate) == 1 and isinstance(candidate[0], str):
                return parse_candidate(candidate[0])
            return None

        if isinstance(candidate, dict):
            error_message = candidate.get('error') or candidate.get('message') or candidate.get('detail')
            if error_message and not any(key in candidate for key in ('condition', 'likelihood', 'icd_code', 'scan_name', 'reason', 'priority')):
                raise ValueError(f"{label} generation failed: {error_message}")
            if item_keys and all(key in candidate for key in item_keys):
                return [candidate]
            for value in candidate.values():
                parsed_value = parse_candidate(value)
                if parsed_value is not None:
                    return parsed_value
            return None

        if isinstance(candidate, str):
            stripped = candidate.strip()
            if not stripped:
                return None
            if stripped[0] not in '[{':
                return None
            try:
                return parse_candidate(json.loads(stripped))
            except json.JSONDecodeError:
                return None

        return None

    candidate = content
    if isinstance(candidate, (bytes, bytearray)):
        candidate = candidate.decode('utf-8')

    parsed = parse_candidate(json.loads(candidate) if isinstance(candidate, str) else candidate)
    if parsed is None:
        snippet = content[:500] if isinstance(content, str) else str(content)[:500]
        raise ValueError(f"{label} response was not a JSON array. Received: {snippet}")
    return parsed


def parse_json_object_payload(content, label):
    if content is None:
        raise ValueError(f"{label} response content was empty.")

    candidate = content
    if isinstance(candidate, (bytes, bytearray)):
        candidate = candidate.decode('utf-8')

    if isinstance(candidate, str):
        candidate = candidate.strip()
        if not candidate:
          raise ValueError(f"{label} response content was empty.")
        candidate = json.loads(candidate)

    if isinstance(candidate, dict):
        return candidate

    raise ValueError(f"{label} response was not a JSON object. Received: {str(content)[:500]}")


def first_present(mapping, keys):
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ''):
            return value
    return None


def normalize_scan_recommendation(scan):
    scan_name = first_present(
        scan,
        ('scan_name', 'scan', 'scanName', 'test_name', 'test', 'investigation', 'name'),
    )
    reason = first_present(scan, ('reason', 'rationale', 'clinical_reasoning', 'clinical_reason'))
    priority = str(first_present(scan, ('priority', 'urgency'),) or 'routine').strip().lower()

    if priority not in {'urgent', 'routine'}:
        priority = 'urgent' if priority in {'high', 'stat', 'immediate'} else 'routine'

    if not scan_name or not reason:
        raise ValueError(f"Scan recommendation is missing required fields: {scan}")

    return {
        'scan_name': str(scan_name).strip(),
        'reason': str(reason).strip(),
        'priority': priority,
    }


def step_transcribe(consultation):
    """
    Downloads the audio file and sends it to OpenAI Whisper.
    Automatically compresses if file exceeds 25MB limit.
    Returns the raw transcript text string.
    """
    update_status(consultation, 'transcribing', 'Transcribing audio with Whisper...', 10)
    client = get_openai_client()

    # Download the file from storage (S3/Supabase or local)
    audio_field = consultation.audio_file
    audio_field.open('rb')
    audio_bytes = audio_field.read()
    audio_field.close()

    # Write to a temp file so OpenAI SDK can read it properly
    suffix = os.path.splitext(consultation.audio_file_name)[1] or '.mp3'
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    compression_performed = False
    compressed_paths = []
    chunk_dir = None
    chunk_paths = []
    
    try:
        duration_seconds = get_audio_duration_seconds(tmp_path)
        if duration_seconds > WHISPER_MAX_DURATION_SECONDS:
            raise Exception("Audio files longer than 60 minutes are not accepted for transcription.")
        enforce_daily_transcription_limit(consultation, duration_seconds)

        # Check file size and compress if necessary.
        # We use a smaller safe threshold so multipart upload overhead does not
        # push the request over OpenAI's hard 25MB limit.
        file_size = os.path.getsize(tmp_path)
        logger.info(f"Audio file size: {file_size / (1024*1024):.2f}MB")
        
        if file_size > WHISPER_SAFE_SIZE_BYTES:
            logger.info(
                f"File exceeds safe transcription threshold ({WHISPER_SAFE_SIZE_BYTES / (1024*1024):.0f}MB). Segmenting..."
            )
            compression_performed = True

            chunk_dir, chunk_paths = segment_audio_for_whisper(tmp_path)
            transcript_parts = []

            for idx, chunk_path in enumerate(chunk_paths, 1):
                chunk_progress = 15 + int((idx - 1) / max(len(chunk_paths), 1) * 15)
                update_status(
                    consultation,
                    'transcribing',
                    f'Transcribing audio chunk {idx} of {len(chunk_paths)}...',
                    chunk_progress,
                )
                chunk_size = os.path.getsize(chunk_path)
                logger.info(
                    f"Transcribing chunk {idx}/{len(chunk_paths)} ({chunk_size / (1024 * 1024):.2f}MB)"
                )
                transcript_parts.append(transcribe_audio_path(client, chunk_path))

            raw_transcript = '\n'.join(part.strip() for part in transcript_parts if part.strip())
            consultation.raw_transcript = raw_transcript
            consultation.progress_percent = 35
            consultation.progress_step = 'Transcription complete. Preparing clinical note...'
            consultation.save(update_fields=['raw_transcript', 'progress_percent', 'progress_step', 'updated_at'])

            logger.info(
                f"Transcription complete from {len(chunk_paths)} chunk(s). Length: {len(raw_transcript)} chars"
            )
            return raw_transcript
        else:
            raw_transcript = transcribe_audio_path(client, tmp_path)

        consultation.raw_transcript = raw_transcript
        consultation.progress_percent = 35
        consultation.progress_step = 'Transcription complete. Preparing clinical note...'
        consultation.save(update_fields=['raw_transcript', 'progress_percent', 'progress_step', 'updated_at'])
        
        if compression_performed:
            logger.info(f"Transcription complete (after compression). Length: {len(raw_transcript)} chars")
        else:
            logger.info(f"Whisper transcription complete. Length: {len(raw_transcript)} chars")
        
        return raw_transcript
    
    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        raise Exception(f"Transcription failed: {str(e)}")
    
    finally:
        # Clean up temp files
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        for compressed_path in compressed_paths:
            if os.path.exists(compressed_path):
                os.unlink(compressed_path)
        if chunk_dir and os.path.isdir(chunk_dir):
            for filename in os.listdir(chunk_dir):
                file_path = os.path.join(chunk_dir, filename)
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            os.rmdir(chunk_dir)


# ─────────────────────────────────────────────────────────
# STEP 2 — Generate Doctor's Note from Chunked Transcript
# ─────────────────────────────────────────────────────────

def chunk_transcript(transcript, chunk_size=3000):
    """
    Splits transcript into overlapping chunks to avoid losing context.
    Each chunk is ~3000 chars with 500 char overlap.
    """
    chunks = []
    overlap = 500
    start = 0
    
    while start < len(transcript):
        end = start + chunk_size
        chunks.append(transcript[start:end])
        start = end - overlap
    
    return chunks


def step_generate_doctors_note(consultation, raw_transcript):
    """
    Chunks the transcript and processes each chunk through GPT-4
    to generate a cohesive doctor's note.
    Saves the note to ConsultationReport and returns it.
    """
    update_status(consultation, 'analyzing', 'Writing doctor\'s note from transcript...', 40)
    client = get_openai_client()
    
    # Split transcript into manageable chunks
    chunks = chunk_transcript(raw_transcript, chunk_size=3000)
    logger.info(f"Transcript split into {len(chunks)} chunks for processing")
    
    chunk_notes = []
    
    # Process each chunk
    for idx, chunk in enumerate(chunks, 1):
        chunk_progress = 40 + int((idx - 1) / max(len(chunks), 1) * 15)
        update_status(
            consultation,
            'analyzing',
            f'Writing doctor\'s note from transcript chunk {idx} of {len(chunks)}...',
            chunk_progress,
        )
        prompt = f"""
You are a clinical documentation specialist. Below is a portion of a doctor-patient consultation transcript.
Generate a concise, professional clinical narrative for this segment.

Focus on:
- Patient complaints and symptoms
- Doctor's findings and observations
- Assessment and plan mentioned

Keep the note clinically accurate and professional. Write in narrative form.

TRANSCRIPT SEGMENT:
{chunk}

Return only the clinical note text, no other commentary.
"""
        
        response = client.chat.completions.create(
            model='gpt-4o',
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.2,
        )
        log_openai_usage(response, f"doctor note chunk {idx}")
        
        chunk_note = response.choices[0].message.content
        chunk_notes.append(chunk_note)
        logger.info(f"Processed chunk {idx}/{len(chunks)}")
    
    # Combine chunk notes into a single comprehensive doctor's note
    combined_chunks = "\n\n".join(chunk_notes)
    
    synthesis_prompt = f"""
You are a clinical documentation specialist. Below are clinical notes from different segments of a consultation.
Synthesize these into a single, cohesive doctor's note in narrative form.

Ensure:
- Chronological flow
- No repetition
- Professional medical language
- All relevant findings and assessments are included

CLINICAL SEGMENTS:
{combined_chunks}

Return only the final synthesized doctor's note.
"""
    
    update_status(consultation, 'analyzing', 'Synthesizing doctor\'s note...', 58)
    synthesis_response = client.chat.completions.create(
        model='gpt-4o',
        messages=[{'role': 'user', 'content': synthesis_prompt}],
        temperature=0.2,
    )
    log_openai_usage(synthesis_response, "doctor note synthesis")
    
    doctors_note = synthesis_response.choices[0].message.content
    
    # Save the doctor's note to ConsultationReport
    from apps.diagnosis.models import ConsultationReport
    report, _ = ConsultationReport.objects.get_or_create(consultation=consultation)
    report.doctors_note = doctors_note
    report.save(update_fields=['doctors_note'])
    update_status(consultation, 'analyzing', 'Doctor\'s note complete. Building SOAP note...', 65)
    
    logger.info(f"Doctor's note generated and saved. Length: {len(doctors_note)} chars")
    return doctors_note


# ─────────────────────────────────────────────────────────
# STEP 3 — SOAP Note Generation
# ─────────────────────────────────────────────────────────

def step_generate_soap(consultation, doctors_note):
    """
    Generates a structured SOAP note from the doctor's note.
    Saves to ConsultationReport.
    Returns the SOAP dict.
    """
    update_status(consultation, 'analyzing', 'Generating SOAP note...', 70)
    client = get_openai_client()

    prompt = f"""
You are a clinical documentation AI assistant. Analyze the following doctor's note and extract a structured SOAP note.

Return ONLY a JSON object in exactly this format, no other text:
{{
  "subjective": "Patient-reported symptoms, history, and complaints in narrative form",
  "objective": "Observable or measurable clinical findings",
  "assessment": "Clinical impression and summary of the doctor's evaluation",
  "plan": "Recommended treatments, medications, referrals, and follow-up steps"
}}

DOCTOR'S NOTE:
{doctors_note}
"""

    response = client.chat.completions.create(
        model='gpt-4o',
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.2,
        response_format={'type': 'json_object'},
    )
    log_openai_usage(response, "SOAP generation")

    soap = parse_json_object_payload(response.choices[0].message.content, 'SOAP')

    # Create or update the ConsultationReport
    from apps.diagnosis.models import ConsultationReport
    report, _ = ConsultationReport.objects.get_or_create(consultation=consultation)
    report.soap_subjective = soap.get('subjective', '')
    report.soap_objective = soap.get('objective', '')
    report.soap_assessment = soap.get('assessment', '')
    report.soap_plan = soap.get('plan', '')
    report.save()
    update_status(consultation, 'analyzing', 'SOAP note complete. Generating diagnosis...', 78)

    logger.info("SOAP note generated and saved.")
    return soap


# ─────────────────────────────────────────────────────────
# STEP 4 — Differential Diagnosis Generation
# ─────────────────────────────────────────────────────────

def step_generate_diagnosis(consultation, doctors_note):
    """
    Generates a ranked differential diagnosis list with percentage likelihoods.
    Saves DiagnosisItem records to the ConsultationReport.
    Returns the diagnosis list.
    """
    update_status(consultation, 'analyzing', 'Generating differential diagnosis...', 82)
    client = get_openai_client()

    prompt = f"""
You are a clinical AI diagnostic assistant. Based on the following doctor's note, generate a differential diagnosis.

Rules:
- List between 3 and 6 possible conditions
- Rank them from most to least likely
- Likelihood percentages must sum to 100
- Use real ICD-10 codes
- Include brief clinical reasoning for each
- If clinical information is limited, still return the best plausible differential instead of an error
- Never return an error object or explanatory text outside the JSON structure
- If the consultation does NOT contain enough clinical information, return an empty diagnoses array, set "insufficient_information" to true, and provide a brief human-readable "insufficient_reason"

Return ONLY a JSON object in exactly this format, no other text:
{{
    "diagnoses": [
        {{
            "condition": "Community-acquired Pneumonia",
            "likelihood": 68,
            "icd_code": "J18.9",
            "reasoning": "Productive cough, fever, reduced breath sounds on left lower lobe consistent with pneumonia"
        }},
        {{
            "condition": "Gastroesophageal Reflux Disease",
            "likelihood": 20,
            "icd_code": "K21.0",
            "reasoning": "Chest discomfort and history of heartburn mentioned by patient"
        }}
    ],
        "insufficient_information": false,
    "insufficient_reason": ""
}}

DOCTOR'S NOTE:
{doctors_note}
"""

    response = client.chat.completions.create(
        model='gpt-4o',
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.1,
        response_format={'type': 'json_object'},
    )
    log_openai_usage(response, "diagnosis generation")

    diagnosis_payload = parse_json_object_payload(response.choices[0].message.content, 'Diagnosis')
    diagnosis_list = parse_json_array_payload(
        diagnosis_payload.get('diagnoses', []),
        'Diagnosis',
        item_keys={'condition', 'likelihood', 'icd_code'}
    )
    insufficient_information = bool(diagnosis_payload.get('insufficient_information', False) or not diagnosis_list)
    insufficient_reason = str(diagnosis_payload.get('insufficient_reason', '') or '').strip()
    if insufficient_information and not insufficient_reason:
        insufficient_reason = 'The consultation does not contain enough clinical detail to support a differential diagnosis.'

    from apps.diagnosis.models import ConsultationReport, DiagnosisItem
    report = ConsultationReport.objects.get(consultation=consultation)
    report.diagnosis_insufficient_information = insufficient_information
    report.diagnosis_insufficient_reason = insufficient_reason
    report.save(update_fields=['diagnosis_insufficient_information', 'diagnosis_insufficient_reason'])

    DiagnosisItem.objects.filter(report=report).delete()
    DiagnosisItem.objects.bulk_create([
        DiagnosisItem(
            report=report,
            condition=d['condition'],
            likelihood=d['likelihood'],
            icd_code=d['icd_code'],
            reasoning=d.get('reasoning', ''),
        )
        for d in diagnosis_list
    ])

    if insufficient_information:
        logger.info(
            f"Diagnosis marked insufficient information. {len(diagnosis_list)} placeholder condition(s) saved. Reason: {insufficient_reason}"
        )
    else:
        logger.info(f"Diagnosis generated. {len(diagnosis_list)} conditions saved.")
    update_status(consultation, 'analyzing', 'Diagnosis complete. Recommending investigations...', 90)

    return {
        'diagnoses': diagnosis_list,
        'insufficient_information': insufficient_information,
        'insufficient_reason': insufficient_reason,
    }


# ─────────────────────────────────────────────────────────
# STEP 5 — Scan & Test Recommendations
# ─────────────────────────────────────────────────────────

def step_generate_scans(consultation, diagnosis_list):
    """
    Recommends imaging and lab tests based on the differential diagnosis.
    Saves ScanRecommendation records.
    No longer needs transcript as input.
    """
    update_status(consultation, 'analyzing', 'Generating scan recommendations...', 92)
    client = get_openai_client()

    if not diagnosis_list:
        raise ValueError('No differential diagnosis was generated, so scan recommendations cannot be created.')

    diagnosis_summary = '\n'.join(
        f"- {d['condition']} ({d['likelihood']}%): {d.get('reasoning', '')}"
        for d in diagnosis_list
    )

    prompt = f"""
You are a clinical AI assistant. Based on the differential diagnosis below, recommend appropriate imaging and laboratory investigations.

Rules:
- Recommend between 3 and 6 investigations
- Mark each as "urgent" or "routine"
- Include clear clinical reasoning
- Focus on investigations that will help confirm or rule out the top diagnoses

DIFFERENTIAL DIAGNOSIS:
{diagnosis_summary}

Return ONLY a JSON object in exactly this format, no other text:
{{
    "recommendations": [
        {{
            "scan_name": "Chest X-Ray (PA and Lateral)",
            "reason": "Rule out consolidation, pleural effusion, and cardiomegaly to confirm pneumonia diagnosis",
            "priority": "urgent"
        }},
        {{
            "scan_name": "Full Blood Count with Differential",
            "reason": "Elevated WBC with neutrophilia would support bacterial infection",
            "priority": "urgent"
        }}
    ]
}}
"""

    response = client.chat.completions.create(
        model='gpt-4o',
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.1,
        response_format={'type': 'json_object'},
    )
    log_openai_usage(response, "scan recommendation generation")

    scans_list = parse_json_array_payload(
        response.choices[0].message.content,
        'Scan recommendations',
        item_keys={'scan_name', 'reason', 'priority'}
    )
    scans_list = [normalize_scan_recommendation(scan) for scan in scans_list]

    from apps.diagnosis.models import ConsultationReport, ScanRecommendation
    report = ConsultationReport.objects.get(consultation=consultation)

    ScanRecommendation.objects.filter(report=report).delete()
    ScanRecommendation.objects.bulk_create([
        ScanRecommendation(
            report=report,
            scan_name=s['scan_name'],
            reason=s['reason'],
            priority=s['priority'],
        )
        for s in scans_list
    ])

    logger.info(f"Scan recommendations generated. {len(scans_list)} saved.")
    update_status(consultation, 'analyzing', 'Finalising report...', 98)


# ─────────────────────────────────────────────────────────
# ZOOM + RECALL.AI PIPELINE — Downloads recording then processes
# ─────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=6, default_retry_delay=60)
def process_zoom_consultation(self, consultation_id, bot_id):
    """
    Triggered by Recall.ai webhook after bot.done event.
    
    Flow:
    1. Fetch recording download URL from Recall.ai
    2. Download audio bytes from CDN
    3. Save as a temporary file to Django's file storage
    4. Attach to Consultation.audio_file
    5. Call process_consultation to transcribe + analyze
    
    This keeps Zoom + upload consultations on the same pipeline.
    """
    from apps.consultations.models import Consultation
    from django.core.files.base import ContentFile
    from .utils import get_recall_bot_recording_url, download_audio_bytes

    try:
        consultation = Consultation.objects.get(id=consultation_id)
    except Consultation.DoesNotExist:
        logger.error(f"Consultation {consultation_id} not found")
        return

    try:
        update_status(consultation, 'processing', 'Fetching recording download URL...', 6)

        # Step 1: Get the recording download URL from Recall.ai
        download_url = get_recall_bot_recording_url(bot_id)
        logger.info(f"Recording URL for bot {bot_id}: {download_url}")

        # Step 2: Download audio bytes
        update_status(consultation, 'processing', 'Downloading recording from Recall.ai...', 8)
        audio_bytes = download_audio_bytes(download_url)

        # Step 3: Save to Django's file storage with a unique name
        filename = f"zoom_{consultation_id}_{bot_id}.mp4"
        consultation.audio_file.save(filename, ContentFile(audio_bytes), save=True)
        consultation.audio_file_name = filename
        consultation.save(update_fields=['audio_file', 'audio_file_name', 'updated_at'])

        logger.info(f"Recording saved for consultation {consultation_id}: {filename}")

        # Step 4: Feed to the main transcription + analysis pipeline
        update_status(consultation, 'transcribing', 'Recording saved. Starting transcription...', 10)
        process_consultation(consultation_id)

    except Exception as exc:
        if self.request.retries < self.max_retries:
            logger.warning(
                f"Zoom recording not ready for {consultation_id}; retrying "
                f"({self.request.retries + 1}/{self.max_retries}): {exc}"
            )
            consultation.progress_step = 'Waiting for Recall.ai recording media to finish processing...'
            consultation.progress_percent = 8
            consultation.save(update_fields=['progress_step', 'progress_percent', 'updated_at'])
            raise self.retry(exc=exc)

        logger.error(f"Failed to download/process Zoom recording for {consultation_id}: {exc}", exc_info=True)
        consultation.status = 'failed'
        consultation.error_message = f"Failed to download Zoom recording: {str(exc)}"
        consultation.progress_step = 'Failed to retrieve recording from Recall.ai'
        consultation.save(update_fields=['status', 'error_message', 'progress_step', 'updated_at'])
