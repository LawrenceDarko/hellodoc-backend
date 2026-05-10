from rest_framework.throttling import UserRateThrottle


class OpenAIRateThrottle(UserRateThrottle):
    scope = 'openai'
