import json
import logging
from io import BytesIO
from xml.sax.saxutils import escape

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
        GET /api/consultations/:id/export/?export_format=pdf|json

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
    export_format = request.query_params.get('export_format') or request.query_params.get('format', 'json')

    if export_format == 'json':
        serializer = ConsultationReportSerializer(report)
        return Response(serializer.data)

    if export_format == 'pdf':
        pdf_bytes = generate_pdf(report)
        buffer = BytesIO(pdf_bytes)
        filename = f"hellodoc_report_{consultation.patient.name.replace(' ', '_')}_{consultation.created_at.strftime('%Y%m%d')}.pdf"
        return FileResponse(buffer, as_attachment=True, filename=filename, content_type='application/pdf')

    return Response({'error': 'Invalid format. Use ?export_format=pdf or ?export_format=json'}, status=400)


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
    content_width = doc.width

    styles = getSampleStyleSheet()
    story = []

    def safe_text(value):
        return escape('' if value is None else str(value))

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
    story.append(Paragraph(
        f"Patient: {safe_text(patient.name)} | Date: {safe_text(report.consultation.created_at.strftime('%B %d, %Y'))} | Source: {safe_text(report.consultation.get_source_display())}",
        info_style,
    ))
    story.append(Spacer(1, 0.5*cm))

    heading_style = ParagraphStyle('Heading', parent=styles['Heading2'],
                                    fontSize=13, textColor=colors.HexColor('#1E6FD9'), spaceAfter=4)
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontSize=10, spaceAfter=4, leading=16)
    table_text_style = ParagraphStyle('TableText', parent=styles['Normal'], fontSize=8.5, leading=10)
    table_header_style = ParagraphStyle('TableHeader', parent=styles['Normal'], fontSize=8.5, leading=10, textColor=colors.white)

    def cell(text, header=False):
        style = table_header_style if header else table_text_style
        return Paragraph(safe_text(text), style)

    # SOAP Note
    story.append(Paragraph("SOAP Note", heading_style))
    for label, text in [
        ('Subjective', report.soap_subjective),
        ('Objective', report.soap_objective),
        ('Assessment', report.soap_assessment),
        ('Plan', report.soap_plan),
    ]:
        story.append(Paragraph(f"<b>{safe_text(label)}:</b> {safe_text(text)}", body_style))
    story.append(Spacer(1, 0.4*cm))

    # Differential Diagnosis Table
    story.append(Paragraph("Differential Diagnosis", heading_style))
    diag_data = [[
        cell('Condition', header=True),
        cell('Likelihood', header=True),
        cell('ICD-10', header=True),
        cell('Reasoning', header=True),
    ]]
    for item in report.diagnosis_items.all():
        diag_data.append([
            cell(item.condition),
            cell(f"{item.likelihood:.0f}%"),
            cell(item.icd_code),
            cell(item.reasoning[:120] + '...' if len(item.reasoning) > 120 else item.reasoning)
        ])
    diag_table = Table(diag_data, colWidths=[0.24 * content_width, 0.12 * content_width, 0.12 * content_width, 0.52 * content_width], repeatRows=1)
    diag_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E6FD9')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(diag_table)
    story.append(Spacer(1, 0.4*cm))

    # Scan Recommendations
    story.append(Paragraph("Recommended Investigations", heading_style))
    scan_data = [[cell('Investigation', header=True), cell('Reason', header=True), cell('Priority', header=True)]]
    for scan in report.scan_recommendations.all():
        scan_data.append([cell(scan.scan_name), cell(scan.reason), cell(scan.priority.capitalize())])
    scan_table = Table(scan_data, colWidths=[0.38 * content_width, 0.48 * content_width, 0.14 * content_width], repeatRows=1)
    scan_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E6FD9')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(scan_table)
    story.append(Spacer(1, 0.5*cm))

    # Disclaimer
    disclaimer_style = ParagraphStyle('Disclaimer', parent=styles['Normal'],
                                       fontSize=8, textColor=colors.grey)
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        safe_text("AI-generated report. Always apply clinical judgment. Not a substitute for professional medical evaluation. HelloDoc - HIPAA Compliant."),
        disclaimer_style
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()
