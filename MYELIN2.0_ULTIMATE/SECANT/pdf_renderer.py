"""Readable A4 portrait report and atomic publication. No database or organ calls."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import os
import tempfile
from threading import RLock
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
                               PageBreak, CondPageBreak, Table as RLTable, TableStyle, Flowable)
from .pdf_model import ReportModel, Text, Table, Flow


PAGE_W,PAGE_H=A4
MARGIN=15*mm
WIDTH=PAGE_W-2*MARGIN
NAVY=colors.HexColor('#122b40')
INK=colors.HexColor('#21384b')
MUTED=colors.HexColor('#526b80')
LINE=colors.HexColor('#ccdce6')
PALE=colors.HexColor('#f3f8fb')
CYAN=colors.HexColor('#12b7cc')
FAMILIES={'study':'#008fa6','secant':'#006cc4','cosecant':'#087f62','quality':'#9a6712'}
TONES={'purple':'#8143ad','blue':'#0073c8','amber':'#a96c00','red':'#c03238',
       'green':'#087f62','yellow':'#a97a08','neutral':'#607182'}
_LOCK=RLock()


@dataclass(frozen=True)
class RenderResult:
    data: bytes
    pages: int
    substitutions: tuple[str, ...]


@dataclass(frozen=True)
class ExportResult:
    path: str
    pages: int
    byte_count: int
    substitutions: tuple[str, ...]


def _fonts():
    if 'MYLStudyBody' not in pdfmetrics.getRegisteredFontNames():
        windows=Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts'
        candidates=[(windows/'segoeui.ttf',windows/'segoeuib.ttf'),
                    (windows/'arial.ttf',windows/'arialbd.ttf'),
                    (Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))]
        for regular,bold in candidates:
            if regular.exists() and bold.exists():
                pdfmetrics.registerFont(TTFont('MYLStudyBody',str(regular)))
                pdfmetrics.registerFont(TTFont('MYLStudyBold',str(bold)))
                pdfmetrics.registerFontFamily('MYLStudyBody',normal='MYLStudyBody',bold='MYLStudyBold',italic='MYLStudyBody',boldItalic='MYLStudyBold')
                break
        else:raise RuntimeError('An embedded Unicode TrueType report font is required.')
    body=pdfmetrics.getFont('MYLStudyBody').face.charToGlyph
    bold=pdfmetrics.getFont('MYLStudyBold').face.charToGlyph
    return set(body) & set(bold)


class Glyphs:
    def __init__(self):
        self.covered=_fonts();self.missing=set()
    def clean(self,text):
        result=[]
        for char in str(text):
            if char in '\n\t':result.append(char)
            elif ord(char) in self.covered and (ord(char)>=32):result.append(char)
            else:
                self.missing.add(f'U+{ord(char):04X}')
                result.append('?')
        return ''.join(result)


class ContinuedTable(RLTable):
    """Repeat entity title and column headers, including split oversized rows."""
    def split(self,availWidth,availHeight):
        parts=super().split(availWidth,availHeight)
        for i,part in enumerate(parts):
            part._report_title=getattr(self,'_report_title',None)
            part._title_style=getattr(self,'_title_style',None)
            if i and part._report_title:
                part._cellvalues[0]=list(part._cellvalues[0])
                part._cellvalues[0][0]=Paragraph(escape(part._report_title)+' / CONTINUED',part._title_style)
        return parts


class Badge(Flowable):
    def __init__(self,number,tone):
        super().__init__();self.width=28;self.height=28;self.number=str(number);self.color=colors.HexColor(TONES.get(tone,TONES['neutral']))
    def draw(self):
        c=self.canv;c.setFillColor(self.color);c.circle(14,14,12,stroke=0,fill=1)
        c.setFillColor(colors.white);c.setFont('MYLStudyBold',9);c.drawCentredString(14,11,self.number)


def render_report(model: ReportModel) -> RenderResult:
    if not isinstance(model,ReportModel) or model.evidence_state!='FINALIZED':
        raise ValueError('Finalized immutable report model required')
    with _LOCK:
        return _render(model)


def _render(model):
    glyphs=Glyphs()
    styles={
        'body':ParagraphStyle('body',fontName='MYLStudyBody',fontSize=9,leading=13,textColor=INK,spaceAfter=7,splitLongWords=1),
        'cell':ParagraphStyle('cell',fontName='MYLStudyBody',fontSize=9,leading=12,textColor=INK,splitLongWords=1),
        'small':ParagraphStyle('small',fontName='MYLStudyBody',fontSize=9,leading=12,textColor=MUTED,spaceAfter=6),
        'head':ParagraphStyle('head',fontName='MYLStudyBold',fontSize=18,leading=23,textColor=NAVY,spaceAfter=13,keepWithNext=True),
        'tabletitle':ParagraphStyle('tabletitle',fontName='MYLStudyBold',fontSize=10,leading=13,textColor=NAVY),
        'th':ParagraphStyle('th',fontName='MYLStudyBold',fontSize=9,leading=12,textColor=NAVY),
        'cover':ParagraphStyle('cover',fontName='MYLStudyBold',fontSize=29,leading=35,textColor=NAVY,spaceAfter=4),
        'cover_sub':ParagraphStyle('cover_sub',fontName='MYLStudyBold',fontSize=17,leading=22,textColor=NAVY,spaceAfter=9),
    }
    def p(text,style='body'):
        return Paragraph(escape(glyphs.clean(text)).replace('\n','<br/>'),styles[style])
    def grid(block):
        count=len(block.columns)
        if not block.rows:return p('No data')
        data=[[p(block.title,'tabletitle')]+['']*(count-1),[p(c,'th') for c in block.columns]]
        data.extend([[p(cell,'cell') for cell in row] for row in block.rows])
        table=ContinuedTable(data,colWidths=[WIDTH*w/sum(block.widths) for w in block.widths],repeatRows=2,
                            splitByRow=1,splitInRow=1,hAlign='LEFT',spaceAfter=14)
        table._report_title=glyphs.clean(block.title);table._title_style=styles['tabletitle']
        table.setStyle(TableStyle([('SPAN',(0,0),(-1,0)),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e9f5f8')),
            ('BACKGROUND',(0,1),(-1,1),PALE),('ROWBACKGROUNDS',(0,2),(-1,-1),[colors.white,colors.HexColor('#f8fafc')]),
            ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
            ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),
            ('LINEBELOW',(0,1),(-1,1),.6,LINE),('LINEBELOW',(0,2),(-1,-1),.25,LINE)]))
        return table
    def flow(block):
        rows=[[p(block.title,'tabletitle'),'',''],[p('Step','th'),p('Event / resource','th'),p('Time / evidence detail','th')]]
        for i,node in enumerate(block.nodes,1):
            family,title,detail,when,tone,connector=node
            details=[p(when,'cell'),p(detail,'cell')]
            if i<len(block.nodes):
                details.append(p('NEXT -> '+(connector or 'Recorded sequence'),'cell'))
            rows.append([Badge(i,tone),[p(family,'small'),p(title,'tabletitle')],details])
        table=ContinuedTable(rows,colWidths=[45,WIDTH*.45,WIDTH*.55-45],repeatRows=2,splitByRow=1,splitInRow=1,hAlign='LEFT',spaceAfter=14)
        table._report_title=glyphs.clean(block.title);table._title_style=styles['tabletitle']
        rules=[('SPAN',(0,0),(-1,0)),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e9f5f8')),
               ('BACKGROUND',(0,1),(-1,1),PALE),('VALIGN',(0,0),(-1,-1),'TOP'),
               ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
               ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]
        for i in range(len(block.nodes)):
            row=2+i;rules.append(('BACKGROUND',(0,row),(-1,row),PALE))
            rules.append(('LINEBELOW',(0,row),(-1,row),3,colors.white))
        table.setStyle(TableStyle(rules));return table
    def cards(family,metrics):
        cells=[]
        for label,value,note in metrics:
            value_style=ParagraphStyle('metric',parent=styles['head'],fontSize=17,leading=20,spaceAfter=3,keepWithNext=False)
            cells.append([p(label,'small'),Paragraph(escape(glyphs.clean(value)),value_style)])
        t=RLTable([cells],colWidths=[WIDTH/len(cells)]*len(cells),hAlign='LEFT',spaceAfter=9)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),PALE),('BOX',(0,0),(-1,-1),.5,LINE),
            ('INNERGRID',(0,0),(-1,-1),.5,LINE),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),
            ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
        return [p(family.upper(),'tabletitle'),Spacer(1,4),t]
    output=BytesIO()
    doc=BaseDocTemplate(output,pagesize=(PAGE_W,PAGE_H),leftMargin=MARGIN,rightMargin=MARGIN,
        topMargin=57,bottomMargin=48,title=f'MYELIN Study Recovery Report - Session {model.session_id}',
        author='MYELIN 2.0',subject='One parent session: Study, SECANT and COSECANT; '+model.evidence_digest)
    def page(canvas,document):
        canvas.saveState();canvas.setFillColor(NAVY);canvas.rect(0,PAGE_H-19,PAGE_W,19,stroke=0,fill=1)
        if document.page==1:
            # Dedicated MINE-style title page; dashboard values start on page 2.
            canvas.rect(0,PAGE_H-25,PAGE_W,25,stroke=0,fill=1)
            canvas.setFont('MYLStudyBold',10);canvas.drawString(MARGIN,PAGE_H-87,'MYELIN 2.0')
            canvas.setStrokeColor(CYAN);canvas.setLineWidth(3.5);canvas.line(MARGIN,PAGE_H-107,MARGIN+50,PAGE_H-107)
            canvas.setFillColor(NAVY);canvas.setFont('MYLStudyBold',30)
            canvas.drawString(MARGIN,PAGE_H-198,'SECANT / COSECANT')
            canvas.setFont('MYLStudyBold',22);canvas.drawString(MARGIN,PAGE_H-231,'STUDY RECOVERY REPORT')
            canvas.setFillColor(CYAN);canvas.setFont('MYLStudyBold',18)
            canvas.drawString(MARGIN,PAGE_H-290,f'PARENT SESSION {model.session_id}')
            canvas.setFillColor(INK);canvas.setFont('MYLStudyBold',12)
            canvas.drawString(MARGIN,PAGE_H-354,'Study Context, Recovery and Approved-Break Return')
            canvas.setFillColor(MUTED);canvas.setFont('MYLStudyBody',9)
            canvas.drawString(MARGIN,PAGE_H-616,glyphs.clean('Generated: '+model.generated_at+' ['+model.timezone_key+']'))
            canvas.drawString(MARGIN,PAGE_H-642,f'Data Scope: Parent MYELIN Session {model.session_id} | Finalized recording')
            canvas.setStrokeColor(LINE);canvas.setLineWidth(.6);canvas.line(MARGIN,120,PAGE_W-MARGIN,120)
            canvas.setFillColor(NAVY);canvas.setFont('MYLStudyBold',10);canvas.drawString(MARGIN,88,'MYELIN')
            canvas.setFillColor(MUTED);canvas.setFont('MYLStudyBody',9);canvas.drawString(MARGIN,65,'GUIDE - RECOVER - FOCUS')
            canvas.restoreState();return
        canvas.setFont('MYLStudyBody',9);canvas.setFillColor(MUTED)
        if document.page>1:
            canvas.drawString(MARGIN,PAGE_H-39,f'DATA SCOPE: PARENT MYELIN SESSION {model.session_id}')
            canvas.drawRightString(PAGE_W-MARGIN,PAGE_H-39,glyphs.clean('GENERATED: '+model.generated_at+' ['+model.timezone_key+']'))
        canvas.setStrokeColor(LINE);canvas.line(MARGIN,35,PAGE_W-MARGIN,35)
        canvas.drawString(MARGIN,20,f'MYELIN 2.0 - STUDY / SECANT / COSECANT - SESSION {model.session_id}')
        canvas.drawRightString(PAGE_W-MARGIN,20,f'PAGE {document.page:02d}')
        canvas.restoreState()
    frame=Frame(MARGIN,48,WIDTH,PAGE_H-105,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
    doc.addPageTemplates(PageTemplate(id='Report',frames=[frame],onPage=page))
    story=[Spacer(1,1),PageBreak(),p('Dashboard summary','head'),
           p(f'Parent MYELIN Session {model.session_id} | FINALIZED','tabletitle'),Spacer(1,18),
           p('Study is the shared context for SECANT recovery and COSECANT approved-break return.','body'),Spacer(1,14)]
    for family,metrics in model.dashboard_metrics:story.extend(cards(family,metrics))
    story.extend([Spacer(1,19),p('Evidence State: FINALIZED | Data Scope: One parent MYELIN session','small'),
                  p('Generated: '+model.generated_at+' ['+model.timezone_key+']','small'),
                  p('Exact scoped dashboard summary. Full context, recorded titles, timelines and flows follow.','small'),
                  p('Read-only behavioral software evidence.','small')])
    for number,section in enumerate(model.sections,1):
        story.append(PageBreak() if number==1 else CondPageBreak(150))
        heading=ParagraphStyle('section',parent=styles['head'],textColor=colors.HexColor(FAMILIES[section.family]))
        story.append(Paragraph(f'{number:02d}  '+escape(glyphs.clean(section.title)),heading))
        for block in section.blocks:
            if isinstance(block,Text):story.append(p(block.value))
            elif isinstance(block,Table):story.append(grid(block))
            elif isinstance(block,Flow):story.append(flow(block) if block.nodes else p('No data'))
            else:raise TypeError('Unknown report content')
    # All dynamic content has been converted through Glyphs before this note.
    if glyphs.missing:
        story.append(p('Rendering substitutions: unsupported characters were shown as ?. Original evidence was not changed. Code points: '+', '.join(sorted(glyphs.missing)), 'small'))
    story.append(p('Evidence snapshot fingerprint: '+model.evidence_digest,'small'))
    doc.build(story)
    data=output.getvalue()
    if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-1024:]:
        raise RuntimeError('PDF verification failed')
    return RenderResult(data,doc.page,tuple(sorted(glyphs.missing)))


def suggested_filename(model):
    return f'MYELIN_STUDY_RECOVERY_SESSION_{model.session_id}.pdf'


def publish_pdf(rendered: RenderResult, output_path, *, overwrite=False):
    """Publish validated bytes in the destination directory or leave the old file intact."""
    target=Path(output_path).expanduser().absolute()
    if target.suffix.lower()!='.pdf' or not target.parent.is_dir() or target.is_dir():
        raise ValueError('Choose an existing directory and a PDF filename.')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.myelin-study-',suffix='.tmp',delete=False) as handle:
            temporary=Path(handle.name);handle.write(rendered.data);handle.flush();os.fsync(handle.fileno())
        if overwrite:os.replace(temporary,target)
        else:os.link(temporary,target)  # Fails atomically if another file appeared.
        return ExportResult(str(target),rendered.pages,len(rendered.data),rendered.substitutions)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def export_report(model,output_path,*,overwrite=False):
    return publish_pdf(render_report(model),output_path,overwrite=overwrite)
