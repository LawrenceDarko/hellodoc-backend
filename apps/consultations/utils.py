import base64
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ZOOM_TOKEN_URL = 'https://zoom.us/oauth/token'
ZOOM_API_BASE = 'https://api.zoom.us/v2'
RECALL_API_BASE = 'https://api.recall.ai/api/v1'


# ─────────────────────────────────────────────────────────
# ZOOM — Server-to-Server OAuth token
# ─────────────────────────────────────────────────────────

def get_zoom_access_token():
    """
    Gets a short-lived Zoom access token using Server-to-Server OAuth
    (account_credentials grant).
    Reads ZOOM_OAUTH_ACCOUNT_ID, ZOOM_OAUTH_CLIENT_ID, ZOOM_OAUTH_CLIENT_SECRET
    from settings — matching the existing .env.example keys.
    """
    account_id = getattr(settings, 'ZOOM_OAUTH_ACCOUNT_ID', '')
    client_id = getattr(settings, 'ZOOM_OAUTH_CLIENT_ID', '')
    client_secret = getattr(settings, 'ZOOM_OAUTH_CLIENT_SECRET', '')

    if not all([account_id, client_id, client_secret]):
        raise ValueError(
            "Zoom credentials not configured. Set ZOOM_OAUTH_ACCOUNT_ID, "
            "ZOOM_OAUTH_CLIENT_ID, ZOOM_OAUTH_CLIENT_SECRET in your .env file."
        )

    credentials = f"{client_id}:{client_secret}"
    encoded = base64.b64encode(credentials.encode()).decode()

    response = requests.post(
        ZOOM_TOKEN_URL,
        params={
            'grant_type': 'account_credentials',
            'account_id': account_id,
        },
        headers={
            'Authorization': f'Basic {encoded}',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        timeout=10,
    )
    response.raise_for_status()
    token = response.json().get('access_token')
    logger.info("Zoom access token obtained.")
    return token


# ─────────────────────────────────────────────────────────
# ZOOM — Create a meeting
# ─────────────────────────────────────────────────────────

def create_zoom_meeting(topic, start_time_iso, duration_minutes=60):
    """
    Creates a Zoom meeting using Server-to-Server OAuth.
    Kept compatible with existing import in views.py.

    Args:
        topic: Meeting title string
        start_time_iso: ISO 8601 datetime string e.g. "2026-05-10T14:00:00Z"
        duration_minutes: Expected duration (default 60)

    Returns dict:
        {
            "meeting_id": "123456789",
            "join_url": "https://zoom.us/j/...",
            "start_url": "https://zoom.us/s/...",
            "password": "abc123"
        }
    """
    token = get_zoom_access_token()

    payload = {
        'topic': topic,
        'type': 2,  # Scheduled meeting
        'start_time': start_time_iso,
        'duration': duration_minutes,
        'timezone': 'UTC',
        'settings': {
            'join_before_host': True,    # Patient can join before doctor
            'waiting_room': False,        # Bot must join freely
            'auto_recording': 'none',     # Recall.ai handles recording
            'participant_video': True,
            'host_video': True,
        }
    }

    response = requests.post(
        f'{ZOOM_API_BASE}/users/me/meetings',
        json=payload,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        },
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    return {
        'meeting_id': str(data['id']),
        'join_url': data['join_url'],
        'start_url': data['start_url'],
        'password': data.get('password', ''),
    }


# ─────────────────────────────────────────────────────────
# RECALL.AI — Create a bot to join the Zoom call
# ─────────────────────────────────────────────────────────

def create_recall_bot(join_url, bot_name='HelloDoc AI', join_at_iso=None):
    """
    Creates a Recall.ai bot that joins the Zoom meeting and records it.
    The bot records audio only — HelloDoc handles transcription via Whisper.

    Args:
        join_url: Zoom meeting join URL
        bot_name: Display name shown in the meeting to participants
        join_at_iso: ISO 8601 string for scheduled join time. 
                     If None, bot joins immediately.

    Returns dict:
        {
            "bot_id": "recall-bot-uuid",
        }
    """
    api_key = getattr(settings, 'RECALL_AI_API_KEY', '')
    if not api_key:
        raise ValueError("RECALL_AI_API_KEY is not configured in settings.")

    headers = {
        'Authorization': f'Token {api_key}',
        'Content-Type': 'application/json',
    }

    payload = {
        'meeting_url': join_url,
        'bot_name': bot_name,
        'recording_config': {
            'video_mixed_mp4': {},
        },
    }

    if join_at_iso:
        payload['scheduled_start'] = join_at_iso

    response = requests.post(
        f'{RECALL_API_BASE}/bot/',
        json=payload,
        headers=headers,
        timeout=15,
    )
    
    # Log the actual response for debugging
    if response.status_code != 201:
        try:
            error_detail = response.json()
        except ValueError:
            error_detail = response.text
        logger.error(
            f"Recall.ai bot creation failed ({response.status_code}): {error_detail}. "
            f"Payload: {payload}"
        )
    
    response.raise_for_status()
    data = response.json()

    logger.info(f"Recall.ai bot created: {data['id']}")
    return {'bot_id': data['id']}


# ─────────────────────────────────────────────────────────
# RECALL.AI — Get recording download URL after call ends
# ─────────────────────────────────────────────────────────

def get_recall_bot_recording_url(bot_id):
    """
    Fetches the Recall.ai bot details and extracts the audio download URL.
    Call this from the webhook handler after receiving bot.done event.

    Returns the audio download URL string.
    Raises ValueError if no recording is found.
    """
    api_key = getattr(settings, 'RECALL_AI_API_KEY', '')
    headers = {'Authorization': f'Token {api_key}'}

    response = requests.get(
        f'{RECALL_API_BASE}/bot/{bot_id}/',
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    recordings = data.get('recordings') or []
    if not recordings:
        raise ValueError(f"No recordings found for Recall.ai bot {bot_id}")

    # Walk through recordings to find a usable audio URL.
    # Recall can return null for media_shortcuts or individual shortcuts.
    inspected = []
    for recording in recordings:
        media = recording.get('media_shortcuts') or {}
        audio_mixed = media.get('audio_mixed') or {}
        video_mixed = media.get('video_mixed') or {}
        video = media.get('video') or {}
        audio_url = (
            (audio_mixed.get('data') or {}).get('download_url') or
            (video_mixed.get('data') or {}).get('download_url') or
            (video.get('data') or {}).get('download_url')
        )
        if audio_url:
            logger.info(f"Recording URL found for bot {bot_id}")
            return audio_url
        inspected.append({
            'recording_id': recording.get('id'),
            'recording_status': (recording.get('status') or {}).get('code'),
            'media_shortcut_keys': sorted(media.keys()),
            'audio_mixed_status': (audio_mixed.get('status') or {}).get('code'),
            'video_mixed_status': (video_mixed.get('status') or {}).get('code'),
            'video_status': (video.get('status') or {}).get('code'),
        })

    raise ValueError(
        f"No audio/video download URL found in recordings for bot {bot_id}. "
        f"Inspected recordings: {inspected}"
    )


def download_audio_bytes(download_url):
    """
    Streams and downloads audio bytes from a Recall.ai CDN URL.
    Returns raw bytes.
    """
    response = requests.get(download_url, timeout=120, stream=True)
    response.raise_for_status()

    chunks = []
    for chunk in response.iter_content(chunk_size=8192):
        if chunk:
            chunks.append(chunk)

    audio_bytes = b''.join(chunks)
    logger.info(f"Downloaded {len(audio_bytes) / (1024*1024):.2f}MB from Recall.ai CDN")
    return audio_bytes


# ─────────────────────────────────────────────────────────
# WEBHOOK SIGNATURE VERIFICATION
# ─────────────────────────────────────────────────────────

def verify_recall_signature(request_body_bytes, headers):
    """
    Verifies the Recall.ai webhook HMAC-SHA256 signature.
    Protects the webhook endpoint from spoofed requests.

    Args:
        request_body_bytes: raw request.body bytes
        headers: incoming request headers

    Returns True if valid, False otherwise.
    """
    import binascii
    import hashlib
    import hmac

    msg_id = headers.get('webhook-id') or headers.get('svix-id')
    msg_timestamp = headers.get('webhook-timestamp') or headers.get('svix-timestamp')
    msg_signature = headers.get('webhook-signature') or headers.get('svix-signature')

    if headers.get('svix-signature') and getattr(settings, 'RECALL_SVIX_WEBHOOK_SECRET', ''):
        secret = getattr(settings, 'RECALL_SVIX_WEBHOOK_SECRET', '')
    else:
        secret = getattr(settings, 'RECALL_AI_WEBHOOK_SECRET', '')

    if not secret:
        logger.warning("RECALL_AI_WEBHOOK_SECRET not set in Django settings")
        return False

    if not secret.startswith('whsec_'):
        logger.warning("RECALL_AI_WEBHOOK_SECRET must start with 'whsec_'")
        return False

    if not msg_id or not msg_timestamp or not msg_signature:
        logger.warning("Recall webhook signature headers are missing")
        return False

    try:
        secret_part = secret[len('whsec_'):]
        secret_part += '=' * (-len(secret_part) % 4)
        signing_key = base64.b64decode(secret_part, validate=True)
    except (binascii.Error, ValueError):
        logger.warning("RECALL_AI_WEBHOOK_SECRET is not valid base64")
        return False

    try:
        payload = request_body_bytes.decode('utf-8')
    except UnicodeDecodeError:
        logger.warning("Recall webhook payload is not valid UTF-8")
        return False

    signed_payload = f'{msg_id}.{msg_timestamp}.{payload}'.encode('utf-8')
    expected = hmac.new(
        key=signing_key,
        msg=signed_payload,
        digestmod=hashlib.sha256,
    ).digest()

    for versioned_signature in msg_signature.split():
        try:
            version, signature = versioned_signature.split(',', 1)
        except ValueError:
            continue

        if version != 'v1':
            continue

        try:
            signature += '=' * (-len(signature) % 4)
            received = base64.b64decode(signature, validate=True)
        except (binascii.Error, ValueError):
            continue

        if hmac.compare_digest(expected, received):
            logger.info("Recall webhook signature verified successfully")
            return True

    logger.warning("Recall webhook signature mismatch")
    return False
