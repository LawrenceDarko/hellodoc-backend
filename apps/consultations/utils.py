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
    account_id = getattr(settings, 'ZOOM_OAUTH_ACCOUNT_ID', '') or getattr(settings, 'ZOOM_ACCOUNT_ID', '')
    client_id = getattr(settings, 'ZOOM_OAUTH_CLIENT_ID', '') or getattr(settings, 'ZOOM_CLIENT_ID', '')
    client_secret = getattr(settings, 'ZOOM_OAUTH_CLIENT_SECRET', '') or getattr(settings, 'ZOOM_CLIENT_SECRET', '')

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
        except:
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

    recordings = data.get('recordings', [])
    if not recordings:
        raise ValueError(f"No recordings found for Recall.ai bot {bot_id}")

    # Walk through recordings to find a usable audio URL
    for recording in recordings:
        media = recording.get('media_shortcuts', {})
        audio_url = (
            media.get('audio_mixed', {}).get('data', {}).get('download_url') or
            media.get('video', {}).get('data', {}).get('download_url')
        )
        if audio_url:
            logger.info(f"Recording URL found for bot {bot_id}")
            return audio_url

    raise ValueError(f"No audio download URL found in recordings for bot {bot_id}")


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

def verify_recall_signature(request_body_bytes, signature_header):
    """
    Verifies the Recall.ai webhook HMAC-SHA256 signature.
    Protects the webhook endpoint from spoofed requests.

    Args:
        request_body_bytes: raw request.body bytes
        signature_header: value of X-Recall-Signature header

    Returns True if valid, False otherwise.
    """
    import hashlib
    import hmac

    secret = getattr(settings, 'RECALL_AI_WEBHOOK_SECRET', '')
    if not secret:
        logger.warning("RECALL_AI_WEBHOOK_SECRET not set — skipping signature verification")
        return True  # Fail open during development; tighten in production

    expected = hmac.new(
        secret.encode(),
        request_body_bytes,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header)
