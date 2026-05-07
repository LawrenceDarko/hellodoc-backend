from rest_framework import serializers
from .models import ConsultationReport, DiagnosisItem, ScanRecommendation


class DiagnosisItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiagnosisItem
        fields = ['id', 'condition', 'likelihood', 'icd_code', 'reasoning']


class ScanRecommendationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScanRecommendation
        fields = ['id', 'scan_name', 'reason', 'priority']


class ConsultationReportSerializer(serializers.ModelSerializer):
    """
    Full nested report returned to the frontend after processing completes.
    Includes SOAP note, diagnosis, and scan recommendations.
    """
    diagnosis_items = DiagnosisItemSerializer(many=True, read_only=True)
    scan_recommendations = ScanRecommendationSerializer(many=True, read_only=True)
    consultation_id = serializers.UUIDField(source='consultation.id', read_only=True)
    patient_name = serializers.CharField(source='consultation.patient.name', read_only=True)
    consultation_date = serializers.DateTimeField(source='consultation.created_at', read_only=True)
    source = serializers.CharField(source='consultation.source', read_only=True)

    class Meta:
        model = ConsultationReport
        fields = [
            'consultation_id', 'patient_name', 'consultation_date', 'source',
            'doctors_note',
            'soap_subjective', 'soap_objective', 'soap_assessment', 'soap_plan',
            'diagnosis_insufficient_information', 'diagnosis_insufficient_reason',
            'generated_at', 'diagnosis_items', 'scan_recommendations'
        ]
