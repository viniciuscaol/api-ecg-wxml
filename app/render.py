"""PDF vetorial em milímetros; PNG/JPEG são renderizações desse mesmo PDF."""
from dataclasses import dataclass
from io import BytesIO
import math
import threading
import pypdfium2 as pdfium
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from .parser import Exam, Record, LEADS, WxmlError

LEFT, TOP, WIDTH, HEIGHT, GAP = 15.0, 35.0, 184.0, 40.0, 1.0
PANEL_WIDTH = (WIDTH - 2 * GAP) / 3
PAGE_HEIGHT = 297.0
PDFIUM_LOCK = threading.Lock()  # PDFium não é seguro para chamadas paralelas em threads.


@dataclass(frozen=True)
class PageSpec:
    record: Record
    start_sample: int
    short_samples: int
    rhythm_samples: int


def page_specs(exam: Exam, layout='reference', record=None, offset_seconds=0.0):
    selected = exam.records if record is None else tuple(r for r in exam.records if r.index == record)
    if not selected:
        raise WxmlError('Registro solicitado não existe; o índice começa em 1.')
    pages = []
    for r in selected:
        n = len(r.leads['DI'].samples)
        start = int(round(offset_seconds * exam.sample_rate))
        if not 0 <= start < n:
            raise WxmlError('offset_seconds está fora da duração do registro.')
        short = int(math.floor(PANEL_WIDTH / r.speed_mm_s * exam.sample_rate))
        rhythm = int(math.floor(WIDTH / r.speed_mm_s * exam.sample_rate))
        if short < 1:
            raise WxmlError('Escala temporal incompatível com a largura do quadro.')
        starts = [start] if layout == 'reference' else range(start, n, short)
        for pos in starts:
            pages.append(PageSpec(r, pos, min(short, n-pos), min(rhythm, n-pos)))
            if len(pages) > 50:
                raise WxmlError('Resultado excede 50 páginas; selecione um registro ou o layout reference.')
    return pages


def sample_position(sample_index, sample_value, sample_rate, speed, units, gain):
    """Deslocamento em mm: sem filtros, normalização ou ajuste automático."""
    return sample_index / sample_rate * speed, sample_value / units * gain


def y(top):
    return (PAGE_HEIGHT - top) * mm


def fitted(c, x, top, text, width, font='Helvetica', size=10):
    # WinAnsi possui acentos pt-BR. Substitui explicitamente glifos não suportados.
    text = str(text).encode('cp1252', 'replace').decode('cp1252')
    while c.stringWidth(text, font, size) > width * mm and size > 6:
        size -= 0.25
    if c.stringWidth(text, font, size) > width * mm:
        while text and c.stringWidth(text + '...', font, size) > width * mm:
            text = text[:-1]
        text += '...'
    c.setFont(font, size)
    c.drawString(x * mm, y(top), text)


def grid(c, x, top, width, color):
    bottom = top + HEIGHT
    major, minor = ((0.52, 0.52, 0.52), (0.68, 0.68, 0.68)) if color == 'gray' else ((0.92, 0.65, 0.65), (0.97, 0.84, 0.84))
    for step, rgb, stroke in ((1, minor, 0.25), (5, major, 0.4)):
        c.setStrokeColorRGB(*rgb)
        c.setLineWidth(stroke)
        c.setDash(0.4, 1.0) if color == 'gray' else c.setDash()
        for k in range(0, math.floor(width)+1, step):
            c.line((x+k)*mm, y(top), (x+k)*mm, y(bottom))
        for k in range(0, int(HEIGHT)+1, step):
            c.line(x*mm, y(top+k), (x+width)*mm, y(top+k))
    c.setDash()
    c.setStrokeColorRGB(0.3, 0.3, 0.3)
    c.setLineWidth(0.4)
    c.rect(x*mm, y(bottom), width*mm, HEIGHT*mm)


def trace(c, exam, spec, name, x, top, width, count, color):
    grid(c, x, top, width, color)
    lead = spec.record.leads[name]
    c.setFillColorRGB(0, 0, 0)
    fitted(c, x+2, top+3.7, name, 15, 'Times-Roman', 10)
    # Todas as escalas são declaradas; pulsos de calibração não são inseridos no sinal.
    fitted(c, x+width-25, top+3.5, f'{lead.gain_mm_mv:g} mm/mV', 23, size=6)
    c.saveState()
    clip = c.beginPath()
    clip.rect(x*mm, y(top+HEIGHT), width*mm, HEIGHT*mm)
    c.clipPath(clip, stroke=0, fill=0)
    path = c.beginPath()
    clipped = False
    for i in range(count):
        value = lead.samples[spec.start_sample+i]
        dx, dy = sample_position(i, value, exam.sample_rate, spec.record.speed_mm_s, exam.units_per_mv, lead.gain_mm_mv)
        clipped |= abs(dy) >= HEIGHT/2
        if i == 0:
            path.moveTo((x+dx)*mm, y(top+HEIGHT/2-dy))
        else:
            path.lineTo((x+dx)*mm, y(top+HEIGHT/2-dy))
    c.setStrokeColorRGB(0.03, 0.03, 0.03)
    c.setLineWidth(0.45)
    if hasattr(c, 'set_trace_metadata'):
        c.set_trace_metadata(lead=name, start_sample=spec.start_sample, sample_count=count,
                             sample_rate_hz=exam.sample_rate, units_per_mv=exam.units_per_mv,
                             speed_mm_s=spec.record.speed_mm_s, gain_mm_mv=lead.gain_mm_mv)
    c.drawPath(path)
    c.restoreState()
    if clipped:
        fitted(c, x+2, top+HEIGHT-2, 'Sinal excede altura do quadro', width-4, size=6)
    return clipped


def render_report(exam: Exam, pages, grid_color='gray', rhythm='DII', anonymize=False, canvas_factory=Canvas):
    buffer = BytesIO()
    c = canvas_factory(buffer, pagesize=A4, pageCompression=1, invariant=1)
    c.setTitle('ECG de Repouso')
    c.setAuthor('ECG WXML API')
    for index, spec in enumerate(pages, 1):
        r = spec.record
        p = exam.patient if not anonymize else {k: '' for k in exam.patient} | {'name': 'PACIENTE ANONIMIZADO'}
        c.setFillColorRGB(0, 0, 0)
        c.setFont('Helvetica-Bold', 11)
        c.drawCentredString(105*mm, y(13), 'ECG de Repouso')
        fitted(c, LEFT, 18, f'Exame: {exam.number if not anonymize else "-"}', 55)
        fitted(c, 81, 18, f'Reg.Clín.: {p["clinical_record"]}', 65)
        fitted(c, 152, 18, f'Data: {r.date} {r.time}', 48, size=9)
        fitted(c, LEFT, 23, f'Nome: {p["name"]}', WIDTH)
        fitted(c, LEFT, 28, f'RG: {p["rg"]}', 75)
        fitted(c, 101, 28, f'CPF: {p["cpf"]}', 60)
        fitted(c, 166, 28, f'Nasc.: {p["birth_date"]}', 34, size=9)
        gains = {lead.gain_mm_mv for lead in r.leads.values()}
        scale = f'{next(iter(gains)):g} mm/mV' if len(gains) == 1 else 'ganho por canal'
        filters = ('60 Hz ' if r.filter_60 else '') + ('Muscular' if r.filter_muscle else '')
        fitted(c, LEFT, 33, f'FC: {r.heart_rate or "-"} bpm     {r.speed_mm_s:g} mm/s     {scale}     Filtros no XML: {filters or "não informados"}', WIDTH, size=9)
        clipped = False
        for i, name in enumerate(LEADS):
            row, col = divmod(i, 3)
            clipped |= trace(c, exam, spec, name, LEFT+col*(PANEL_WIDTH+GAP), TOP+row*(HEIGHT+GAP), PANEL_WIDTH, spec.short_samples, grid_color)
        clipped |= trace(c, exam, spec, rhythm, LEFT, TOP+4*(HEIGHT+GAP), WIDTH, spec.rhythm_samples, grid_color)
        box_top = TOP+5*(HEIGHT+GAP)
        c.setStrokeColorRGB(0.3, 0.3, 0.3)
        c.setLineWidth(0.4)
        c.rect(LEFT*mm, y(box_top+21), WIDTH*mm, 21*mm)
        start = spec.start_sample/exam.sample_rate
        end = (spec.start_sample+spec.short_samples)/exam.sample_rate
        rend = (spec.start_sample+spec.rhythm_samples)/exam.sample_rate
        duration = len(r.leads['DI'].samples)/exam.sample_rate
        fitted(c, LEFT+2, box_top+4, f'Registro {r.index} | Quadros: {start:.3f}-{end:.3f} s | Ritmo {rhythm}: {start:.3f}-{rend:.3f} s | Total: {duration:.3f} s', WIDTH-4, size=7)
        fitted(c, LEFT+2, box_top+8, f'{exam.sample_rate:g} Hz | {exam.units_per_mv:g} unidades/mV | Traçado original, sem filtros adicionais', WIDTH-4, size=7)
        fitted(c, LEFT+2, box_top+12, 'Conversão técnica. Validar equivalência com o equipamento antes do uso clínico.', WIDTH-4, size=7)
        if clipped:
            fitted(c, LEFT+2, box_top+16, 'Atenção: amplitude excedeu um ou mais quadros; não houve redução automática do ganho.', WIDTH-4, size=7)
        elif not anonymize and any('?' in v.encode('cp1252', 'replace').decode('cp1252') and '?' not in v for v in p.values()):
            fitted(c, LEFT+2, box_top+16, 'Há caracteres não suportados na fonte; consulte metadados para o texto original.', WIDTH-4, size=7)
        fitted(c, LEFT, box_top+24, f'ECG# {r.serial if not anonymize else "-"}', 75, size=7)
        c.setFont('Helvetica', 7)
        c.drawRightString((LEFT+WIDTH)*mm, y(box_top+24), f'ECG WXML API | {index}/{len(pages)}')
        c.showPage()
    c.save()
    return buffer.getvalue()


def render_pdf(exam: Exam, pages, grid_color='gray', rhythm='DII', anonymize=False):
    return render_report(exam, pages, grid_color, rhythm, anonymize)


def raster_pages(pdf_bytes, dpi=200, image_format='png'):
    if not 72 <= dpi <= 300:
        raise WxmlError('DPI deve estar entre 72 e 300.')
    results = []
    with PDFIUM_LOCK:
        with pdfium.PdfDocument(pdf_bytes) as doc:
            for page in doc:
                bitmap = page.render(scale=dpi/72)
                pil = bitmap.to_pil()
                output = BytesIO()
                if image_format == 'jpeg':
                    converted = pil.convert('RGB')
                    converted.save(output, format='JPEG', quality=95, dpi=(dpi, dpi), subsampling=0)
                    converted.close()
                else:
                    pil.save(output, format='PNG', dpi=(dpi, dpi))
                results.append(output.getvalue())
                pil.close()
                bitmap.close()
                page.close()
    return results
