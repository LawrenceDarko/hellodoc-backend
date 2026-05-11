from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from .serializers import RegisterSerializer, UserSerializer
from .models import DoctorProfile
from .serializers import DoctorProfileSerializer

User = get_user_model()


class LoginView(TokenObtainPairView):
    """Issue JWTs and include the authenticated user in the response."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            user = User.objects.get(email=request.data.get('email'))
            response.data['user'] = UserSerializer(user).data
        return response


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """Register a new doctor account."""
    serializer = RegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    user = serializer.save()
    refresh = RefreshToken.for_user(user)
    return Response({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user': UserSerializer(user).data
    }, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def me(request):
    """Return or update the currently authenticated doctor's profile.

    GET: returns user data
    PUT/PATCH: updates `name` and `email` (partial updates allowed)
    """
    if request.method == 'GET':
        return Response(UserSerializer(request.user).data)

    # Update
    serializer = UserSerializer(request.user, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    serializer.save()
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    """Change password for the authenticated user.

    Body: { old_password?: string, new_password: string }
    If `old_password` is provided it must match; otherwise, the requestor must
    be the authenticated user (we assume that is the case).
    """
    old_password = request.data.get('old_password')
    new_password = request.data.get('new_password')

    if not new_password or len(new_password) < 8:
        return Response({'error': 'new_password must be at least 8 characters.'}, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    if old_password:
        if not user.check_password(old_password):
            return Response({'error': 'old_password is incorrect.'}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(new_password)
    user.save()
    return Response({'success': True}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    """Blacklist the refresh token to log out."""
    try:
        refresh_token = request.data.get('refresh')
        token = RefreshToken(refresh_token)
        token.blacklist()
    except Exception:
        pass
    return Response({'success': True}, status=status.HTTP_200_OK)


@api_view(['GET', 'POST', 'PATCH'])
@permission_classes([IsAuthenticated])
def doctor_profile(request):
    """
    GET   /api/auth/profile/  — get the doctor's profile
    POST  /api/auth/profile/  — create profile (first time)
    PATCH /api/auth/profile/  — update existing profile
    """
    if request.method == 'GET':
        try:
            profile = DoctorProfile.objects.get(doctor=request.user)
            return Response(DoctorProfileSerializer(profile).data)
        except DoctorProfile.DoesNotExist:
            return Response(
                {'detail': 'Profile not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

    if request.method == 'POST':
        profile, created = DoctorProfile.objects.get_or_create(doctor=request.user)
        serializer = DoctorProfileSerializer(profile, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )

    if request.method == 'PATCH':
        try:
            profile = DoctorProfile.objects.get(doctor=request.user)
        except DoctorProfile.DoesNotExist:
            profile = DoctorProfile.objects.create(doctor=request.user)
        serializer = DoctorProfileSerializer(profile, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data)
