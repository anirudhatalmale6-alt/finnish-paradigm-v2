from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Preformatted, KeepTogether
from reportlab.pdfbase.pdfmetrics import stringWidth
import sys, os, json
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))
from app.data_seed import COURSES, PRODUCTS, TOOLS, VIDEOS, ESCALATION_PROTOCOLS, AUTONOMY_MATRIX
OUT=os.path.abspath(os.path.join(os.path.dirname(__file__),'..','backend','static','pdfs'))
os.makedirs(OUT, exist_ok=True)
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='Title2', parent=styles['Title'], fontSize=28, textColor=colors.HexColor('#0b6b65'), leading=32, spaceAfter=18))
styles.add(ParagraphStyle(name='H1x', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#0b6b65'), spaceBefore=14, spaceAfter=8))
styles.add(ParagraphStyle(name='H2x', parent=styles['Heading2'], fontSize=14, textColor=colors.HexColor('#14213d'), spaceBefore=10, spaceAfter=6))
styles.add(ParagraphStyle(name='Bodyx', parent=styles['BodyText'], fontSize=9.5, leading=13, spaceAfter=6))
styles.add(ParagraphStyle(name='Small', parent=styles['BodyText'], fontSize=8, leading=10))

def footer(canvas, doc):
    canvas.saveState(); canvas.setFillColor(colors.HexColor('#5f6f7b')); canvas.setFont('Helvetica',8)
    canvas.drawString(1.5*cm,1*cm,'The Finnish Paradigm - Deployment Resource Pack')
    canvas.drawRightString(19.5*cm,1*cm,str(doc.page)); canvas.restoreState()

def _cell(x):
    if isinstance(x, str):
        return Paragraph(x.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;'), styles['Small'])
    return x

def tbl(data, widths=None):
    wrapped = [[_cell(c) for c in row] for row in data]
    t=Table(wrapped, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0b6b65')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),8),('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#dfe4e7')),('BACKGROUND',(0,1),(-1,-1),colors.white),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f6f5ef')]),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)
    ]))
    return t

def P(text, style='Bodyx'):
    return Paragraph(str(text).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('\n','<br/>'), styles[style])

def build_main():
    doc=SimpleDocTemplate(os.path.join(OUT,'Finnish_Paradigm_Full_Resource_Pack.pdf'), pagesize=A4, rightMargin=1.4*cm,leftMargin=1.4*cm,topMargin=1.4*cm,bottomMargin=1.7*cm)
    story=[]
    story.append(P('THE FINNISH PARADIGM™', 'Title2'))
    story.append(P('Professional Teacher Certification, Early Intervention Toolkit, School Management Architecture and Deployment Resource Pack', 'H2x'))
    story.append(P('Commercial note: use evidence-informed and Finnish-inspired language unless formal institutional authorisation is secured. Avoid claiming official Finnish government certification or guaranteed results.', 'Bodyx'))
    story.append(Spacer(1,8))
    story.append(P('1. Operating Promise', 'H1x'))
    story.append(P('Rekindle teacher purpose, protect classroom autonomy, notice struggling students early, deploy targeted retired-teacher support, and build a school system where no child is invisible.', 'Bodyx'))
    story.append(P('2. Product Suites', 'H1x'))
    story.append(tbl([['Product','Price','Includes']]+[[p['name'],p['price'],', '.join(p['includes'])] for p in PRODUCTS],[4.2*cm,2.2*cm,11*cm]))
    story.append(P('3. Course Catalogue', 'H1x'))
    for c in COURSES:
        story.append(P(c['title'], 'H2x'))
        story.append(P(f"Audience: {c['audience']} | Duration: {c['duration']} | Price: {c['price']}", 'Bodyx'))
        story.append(P(c['outcome'], 'Bodyx'))
        story.append(tbl([['Modules','Resources']]+[[m, c['resources'][i] if i < len(c['resources']) else ''] for i,m in enumerate(c['modules'])],[8.5*cm,8.5*cm]))
    story.append(PageBreak())
    story.append(P('4. Operational Architecture Diagram', 'H1x'))
    story.append(Preformatted('''THE FINNISH PARADIGM OPERATIONAL ARCHITECTURE

Independent Teacher                    Retired Teacher Network
(Solo Classroom Optimization)          (Targeted Intervention)
- Tier-1 differentiated instruction    - Tier-2 individualized support
- Purpose-driven lesson flow           - Tier-3 intensive fine-tuning
- Direct peer alliances                - Mobile classroom assistance
             \                         /
              \                       /
               Student Outcome Matrix
               LEAVE NO CHILD BEHIND''', styles['Code']))
    story.append(P('5. Early Intervention Cycle', 'H1x'))
    story.append(Preformatted('''NOTICE -> RECORD -> SUPPORT -> REVIEW -> ADJUST -> REFER

Notice: identify first academic, behaviour or confidence signs.
Record: write observable evidence, not labels.
Support: apply Level 1 classroom scaffolds or micro-intervention.
Review: check student work and confidence after 1-2 weeks.
Adjust: change strategy if evidence shows limited progress.
Refer: escalate to Level 2, Level 3 or specialist support when needed.''', styles['Code']))
    story.append(P('6. Three-Tier Intervention Action Protocol', 'H1x'))
    story.append(tbl([['Tier','Trigger','Action','Owner'],['Tier 1 - Universal Classroom Support','First sign of confusion or yellow/red IVF card','Use alternate analogy, scaffold, visual or sentence frame immediately','Classroom teacher'],['Tier 2 - Targeted Short-Term Support','Three failed IVF checkpoints in one week','Schedule 30-minute target session; retired mentor or support staff may assist','Teacher + Department Lead'],['Tier 3 - Intensive Customised Support','No benchmark improvement after 14 days','Create Individualized Educational Strategy; parent meeting; specialist review if needed','Leadership / Support Team']],[3*cm,4.5*cm,6.5*cm,3*cm]))
    story.append(P('7. Classroom Autonomy Matrix', 'H1x'))
    story.append(tbl([['Domain','Teacher Control','School Support','Escalation','Examples']]+[[x['domain'],x['teacher_control'],x['school_support'],x['escalation'],x['examples']] for x in AUTONOMY_MATRIX],[3.0*cm,2.0*cm,2.0*cm,3.7*cm,6.0*cm]))
    story.append(PageBreak())
    story.append(P('8. Toolkit Library', 'H1x'))
    story.append(tbl([['Toolkit','Category','Use']]+[[t['title'],t['category'],t['summary']] for t in TOOLS],[4.8*cm,3.0*cm,9.4*cm]))
    story.append(P('9. The 45-15 Instructional Flow Daily Log Sheet', 'H1x'))
    story.append(Preformatted('''Date: __________  Class/Subject: __________  Period: ______

STEP 1: FOCUS ACCELERATOR (5 minutes)
Single learning objective: __________________________________________

STEP 2: CORE DIRECT INSTRUCTION (20 minutes)
Start: ______ End: ______ Key concept: ______________________________

STEP 3: GUIDED PRACTICE MATRIX (20 minutes)
Bottom 20% struggling students identified:
1. __________ 2. __________ 3. __________ 4. __________

STEP 4: RESTORATIVE BREAK (15 minutes)
Students move, reflect or discuss. Teacher observes and gives 2-minute micro-interventions.
Evidence notes: _____________________________________________________''', styles['Code']))
    story.append(P('10. Immediate Verification Framework', 'H1x'))
    story.append(tbl([['Marker','Student Meaning','Teacher Action'],['Green','I understand and can continue','Let student progress independently or extend challenge'],['Yellow','I understand partly','Provide quick prompt, visual, or peer check'],['Red','I am stuck','Micro-teach; record if repeated; trigger Tier 2 after pattern emerges']],[3*cm,6*cm,8*cm]))
    story.append(P('11. Escalation Protocols and Procedures', 'H1x'))
    story.append(tbl([['Level','Trigger','Owner','Action']]+[[e['level'],e['trigger'],e['owner'],e['action']] for e in ESCALATION_PROTOCOLS],[3*cm,4.5*cm,3.5*cm,6.5*cm]))
    story.append(PageBreak())
    story.append(P('12. Senior Asset Deployment and Coordination Matrix', 'H1x'))
    story.append(Preformatted('''A. Asset Onboarding Checklist
[ ] Verified credentials and background clearance
[ ] Specialist area matched to student need
[ ] 10-15 hours per week optimal commitment
[ ] Safeguarding and confidentiality briefing completed

B. In-Class Window Protocol
1. Arrival: senior specialist arrives during guided/independent practice.
2. Handover: teacher provides IVF slip with 3-4 target students.
3. Execution: specialist supports at intervention desk or breakout area.
4. Departure: specialist logs two-sentence progress note.

C. Progress Log
Date: ______ Student: ______ Specialist: ______ Concept: _____________
Outcome code: 1 Achieved | 2 Progressing | 3 Critical Deficit''', styles['Code']))
    story.append(P('13. Parent Communication Templates', 'H1x'))
    story.append(P('Early Support Notice: We are providing additional support for your child. This does not mean failure. It means we have noticed an area where extra practice may help. The support will focus on: ________. We will monitor progress and encourage your child step by step.', 'Bodyx'))
    story.append(P('Positive Progress Update: Your child has made progress in ________. They have improved by ________. We will continue supporting them with ________.', 'Bodyx'))
    story.append(P('Meeting Request: I would like to arrange a short meeting to discuss how we can support your child. The purpose is not blame, but cooperation.', 'Bodyx'))
    story.append(P('14. Direct Ministry Petition Framework - Safe Use Version', 'H1x'))
    story.append(P('Use only lawful, professional and evidence-based escalation. First submit proposals through school leadership. If official escalation is necessary, focus on student welfare, documented evidence and policy alignment.', 'Bodyx'))
    story.append(Preformatted('''Subject: Formal request for implementation of early intervention support protocols

We, the undersigned educators, present evidence that current support windows are insufficient for students demonstrating repeated learning difficulty. We request consideration of structured early intervention, including 45-15 observation windows, Tier 2 support sessions, and qualified retired-educator intervention support where legally and operationally appropriate.

Attached evidence: 14-day IVF logs, student support trackers, parent contact records, and progress reviews.''', styles['Code']))
    story.append(P('15. Deployment Roadmap', 'H1x'))
    story.append(tbl([['Phase','Action','Output'],['1. Audit','Review culture, support systems and data gaps','School baseline report'],['2. Train','Enroll staff in FCFP / ASTI / SELD pathways','Certified staff cohort'],['3. Launch','Start IVF, support trackers and Tier 1 routines','Early concern data'],['4. Deploy','Add retired teachers to Tier 2/3 support','Targeted intervention sessions'],['5. Review','Monthly dashboard and student support meeting','Impact report'],['6. Scale','License courses and resources school-wide','Sustainable implementation']],[3*cm,7*cm,7*cm]))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)

def build_video():
    doc=SimpleDocTemplate(os.path.join(OUT,'Video_Scripts_and_AI_Prompts.pdf'), pagesize=A4, rightMargin=1.4*cm,leftMargin=1.4*cm,topMargin=1.4*cm,bottomMargin=1.7*cm)
    story=[P('AI Training Video Production Pack', 'Title2'), P('Scripts and prompts for Synthesia, HeyGen, D-ID, Colossyan or similar AI-avatar tools. This pack provides production-ready scripts; actual avatar rendering must be completed in your chosen video platform.', 'Bodyx')]
    for v in VIDEOS:
        story.append(P(f"{v['title']} ({v['length']})", 'H1x'))
        story.append(P(f"Course: {v['course']} | Presenter: {v['presenter']}", 'Bodyx'))
        story.append(P('Script', 'H2x')); story.append(P(v['script'], 'Bodyx'))
        story.append(P('AI Presenter Prompt', 'H2x')); story.append(P(v['prompt'], 'Bodyx'))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)

if __name__=='__main__':
    build_main(); build_video(); print('PDFs built in', OUT)
