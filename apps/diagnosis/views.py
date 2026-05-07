import json
import logging
from io import BytesIO

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.http import FileResponse

from apps.consultations.models import Consultation
from .models import ConsultationReport
from .serializers import ConsultationReportSerializer

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def consultation_report(request, consultation_id):
    """
    GET /api/consultations/:id/report/

    Returns the full consultation report including:
      - Speaker-labeled transcript
      - SOAP note (S/O/A/P)
      - Differential diagnosis with % likelihoods and ICD-10 codes
      - Scan and lab recommendations

    Only available when consultation.status == 'completed'.
    Returns 202 with status info if still processing.
    """
    consultation = get_object_or_404(
        Consultation, id=consultation_id, doctor=request.user
    )

    if consultation.status == 'failed':
        return Response({
            'error': 'Processing failed.',
            'detail': consultation.error_message
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    if consultation.status != 'completed':
        return Response({
            'status': consultation.status,
            'progress_step': consultation.progress_step,
            'message': 'Report is still being generated. Please poll /status/ and retry when completed.'
        }, status=status.HTTP_202_ACCEPTED)

    report = get_object_or_404(ConsultationReport, consultation=consultation)
    serializer = ConsultationReportSerializer(report)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export_report(request, consultation_id):
    """
    GET /api/consultations/:id/export/?format=pdf|json

    Exports the full report as either:
      - PDF: generated with ReportLab, returned as file download
      - JSON: structured JSON for EHR/EMR system integration
    """
    consultation = get_object_or_404(
        Consultation, id=consultation_id, doctor=request.user
    )

    if consultation.status != 'completed':
        return Response(
            {'error': 'Report is not ready yet.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    report = get_object_or_404(ConsultationReport, consultation=consultation)
    export_format = request.query_params.get('format', 'json')

    if export_format == 'json':
        serializer = ConsultationReportSerializer(report)
        return Response(serializer.data)

    if export_format == 'pdf':
        pdf_bytes = generate_pdf(report)
        buffer = BytesIO(pdf_bytes)
        filename = f"hellodoc_report_{consultation.patient.name.replace(' ', '_')}_{consultation.created_at.strftime('%Y%m%d')}.pdf"
        return FileResponse(buffer, as_attachment=True, filename=filename, content_type='application/pdf')

    return Response({'error': 'Invalid format. Use ?format=pdf or ?format=json'}, status=400)


def generate_pdf(report):
    """
    Generate a professional PDF report using ReportLab.
    Returns bytes.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from io import BytesIO

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            topMargin=2*cm, bottomMargin=2*cm,
                            leftMargin=2.5*cm, rightMargin=2.5*cm)

    styles = getSampleStyleSheet()
    story = []

    # Title
    title_style = ParagraphStyle('Title', parent=styles['Title'],
                                  fontSize=20, textColor=colors.HexColor('#1E6FD9'),
                                  spaceAfter=6)
    story.append(Paragraph("HelloDoc — Consultation Report", title_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#1E6FD9')))
    story.append(Spacer(1, 0.3*cm))

    # Patient info
    patient = report.consultation.patient
    info_style = ParagraphStyle('Info', parent=styles['Normal'], fontSize=10, textColor=colors.grey)
    story.append(Paragraph(f"Patient: {patient.name} | Date: {report.consultation.created_at.strftime('%B %d, %Y')} | Source: {report.consultation.get_source_display()}", info_style))
    story.append(Spacer(1, 0.5*cm))

    heading_style = ParagraphStyle('Heading', parent=styles['Heading2'],
                                    fontSize=13, textColor=colors.HexColor('#1E6FD9'), spaceAfter=4)
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontSize=10, spaceAfter=4, leading=16)

    # SOAP Note
    story.append(Paragraph("SOAP Note", heading_style))
    for label, text in [
        ('Subjective', report.soap_subjective),
        ('Objective', report.soap_objective),
        ('Assessment', report.soap_assessment),
        ('Plan', report.soap_plan),
    ]:
        story.append(Paragraph(f"<b>{label}:</b> {text}", body_style))
    story.append(Spacer(1, 0.4*cm))

    # Differential Diagnosis Table
    story.append(Paragraph("Differential Diagnosis", heading_style))
    diag_data = [['Condition', 'Likelihood', 'ICD-10', 'Reasoning']]
    for item in report.diagnosis_items.all():
        diag_data.append([
            item.condition,
            f"{item.likelihood:.0f}%",
            item.icd_code,
            item.reasoning[:80] + '...' if len(item.reasoning) > 80 else item.reasoning
        ])
    diag_table = Table(diag_data, colWidths=[5*cm, 2.5*cm, 2.5*cm, 6.5*cm])
    diag_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E6FD9')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(diag_table)
    story.append(Spacer(1, 0.4*cm))

    # Scan Recommendations
    story.append(Paragraph("Recommended Investigations", heading_style))
    scan_data = [['Investigation', 'Reason', 'Priority']]
    for scan in report.scan_recommendations.all():
        scan_data.append([scan.scan_name, scan.reason, scan.priority.capitalize()])
    scan_table = Table(scan_data, colWidths=[4.5*cm, 9*cm, 3*cm])
    scan_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E6FD9')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(scan_table)
    story.append(Spacer(1, 0.5*cm))

    # Disclaimer
    disclaimer_style = ParagraphStyle('Disclaimer', parent=styles['Normal'],
                                       fontSize=8, textColor=colors.grey)
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        "AI-generated report. Always apply clinical judgment. Not a substitute for professional medical evaluation. HelloDoc — HIPAA Compliant.",
        disclaimer_style
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()
