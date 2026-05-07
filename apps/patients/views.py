from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from .models import Patient
from .serializers import PatientSerializer


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def patient_list(request):
    """
    GET  /api/patients/  — list all patients for this doctor
    POST /api/patients/  — create a new patient
    """
    if request.method == 'GET':
        patients = Patient.objects.filter(doctor=request.user)
        serializer = PatientSerializer(patients, many=True)
        return Response(serializer.data)

    if request.method == 'POST':
        serializer = PatientSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save(doctor=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def patient_detail(request, patient_id):
    """
    GET    /api/patients/:id/  — get a single patient
    PATCH  /api/patients/:id/  — update patient details
    DELETE /api/patients/:id/  — delete patient
    """
    patient = get_object_or_404(Patient, id=patient_id, doctor=request.user)

    if request.method == 'GET':
        return Response(PatientSerializer(patient).data)

    if request.method == 'PATCH':
        serializer = PatientSerializer(patient, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data)

    if request.method == 'DELETE':
        patient.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
