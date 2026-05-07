import logging
from datetime import datetime, timezone
from typing import Optional
import base64

import requests
import jwt
from dateutil import parser
from django.conf import settings

logger = logging.getLogger(__name__)


def _build_jwt() -> Optional[str]:
	"""Build a JWT for Zoom API using API Key/Secret from settings.

	Returns JWT string or None if credentials not configured.
	"""
	api_key = getattr(settings, 'ZOOM_API_KEY', None)
	api_secret = getattr(settings, 'ZOOM_API_SECRET', None)
	if not api_key or not api_secret:
		logger.debug('Zoom API key/secret not configured')
		return None

	payload = {
		'iss': api_key,
		'exp': int((datetime.utcnow()).timestamp()) + 60,
	}
	token = jwt.encode(payload, api_secret, algorithm='HS256')
	return token


def _get_oauth_access_token() -> Optional[str]:
	"""Obtain a Zoom OAuth access token using server-to-server credentials.

	This prefers server-to-server (account_credentials) when `ZOOM_OAUTH_ACCOUNT_ID`
	is set; otherwise attempts a client_credentials style request. Caller must
	provide `ZOOM_OAUTH_CLIENT_ID` and `ZOOM_OAUTH_CLIENT_SECRET` in settings.
	Returns access_token on success or None.
	"""
	client_id = getattr(settings, 'ZOOM_OAUTH_CLIENT_ID', None)
	client_secret = getattr(settings, 'ZOOM_OAUTH_CLIENT_SECRET', None)
	if not client_id or not client_secret:
		logger.debug('Zoom OAuth client id/secret not configured')
		return None

	token_url = 'https://zoom.us/oauth/token'
	basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
	headers = {'Authorization': f'Basic {basic}'}

	account_id = getattr(settings, 'ZOOM_OAUTH_ACCOUNT_ID', None)
	params = {}
	data = {}
	if account_id:
		params['grant_type'] = 'account_credentials'
		data['account_id'] = account_id
	else:
		params['grant_type'] = 'client_credentials'

	try:
		resp = requests.post(token_url, params=params, headers=headers, data=data or None, timeout=10)
		resp.raise_for_status()
		token = resp.json().get('access_token')
		if token:
			logger.debug('Obtained Zoom OAuth access token')
			return token
		logger.debug('Zoom OAuth response missing access_token: %s', resp.text)
	except Exception:
		logger.exception('Failed to fetch Zoom OAuth access token')
	return None


def create_zoom_meeting(topic: str, start_time_iso: str, duration_minutes: int = 30) -> Optional[str]:
	"""Create a Zoom meeting and return the join URL (join_url).

	Attempts OAuth-based token retrieval first (server-to-server). Falls back
	to JWT (API Key/Secret) if OAuth isn't configured.
	"""
	# Prefer OAuth access token when configured
	access_token = _get_oauth_access_token()
	if access_token:
		auth_header = f'Bearer {access_token}'
	else:
		jwt_token = _build_jwt()
		if not jwt_token:
			logger.debug('No Zoom credentials available (OAuth or JWT)')
			return None
		auth_header = f'Bearer {jwt_token}'

	try:
		parsed = parser.isoparse(start_time_iso)
		# Normalize to UTC
		start_time_utc = parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
		start_time_str = start_time_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
	except Exception:
		logger.exception('Failed to parse start_time_iso: %s', start_time_iso)
		start_time_str = start_time_iso

	url = 'https://api.zoom.us/v2/users/me/meetings'
	headers = {
		'Authorization': auth_header,
		'Content-Type': 'application/json',
	}
	body = {
		'topic': topic,
		'type': 2,
		'start_time': start_time_str,
		'duration': duration_minutes,
		'timezone': 'UTC',
		'settings': {
			'join_before_host': False,
			'approval_type': 0,
			'audio': 'both',
			'auto_recording': 'cloud',
		},
	}

	try:
		resp = requests.post(url, json=body, headers=headers, timeout=10)
		resp.raise_for_status()
		data = resp.json()
		join_url = data.get('join_url')
		logger.info('Created Zoom meeting: %s', join_url)
		return join_url
	except Exception:
		logger.exception('Zoom meeting creation failed')
		return None

