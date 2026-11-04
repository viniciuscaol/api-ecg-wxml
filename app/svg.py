"""Canvas SVG vetorial nativo. Compartilha os mesmos caminhos/geometria com PDF.

Nenhum PDF, PNG, JPEG, canvas bitmap ou ponto interpolado é criado neste caminho.
As unidades internas são pontos (72/in) e o viewBox mantém a proporção física.
"""
from copy import deepcopy
from io import BytesIO
import math
from xml.etree import ElementTree as ET
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.units import mm
from .parser import LEADS, WxmlError
from .render import (PAGE_HEIGHT, LEFT, TOP, HEIGHT, GAP, WIDTH, PageSpec,
                     render_report, trace, fitted)

NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)


def tag(name):
    return f'{{{NS}}}{name}'


def f(value):
    return f'{value:.6f}'.rstrip('0').rstrip('.') or '0'


def rgb(values):
    return 'rgb(' + ','.join(str(round(v*255)) for v in values) + ')'


class SvgPath:
    def __init__(self):
        self.commands = []

    def moveTo(self, x, y):
        self.commands.append(f'M{f(x)} {f(y)}')

    def lineTo(self, x, y):
        self.commands.append(f'L{f(x)} {f(y)}')

    def rect(self, x, y, width, height):
        self.moveTo(x, y)
        self.lineTo(x+width, y)
        self.lineTo(x+width, y+height)
        self.lineTo(x, y+height)
        self.commands.append('Z')


class SvgCanvas:
    def __init__(self, buffer, pagesize, origin_height=None, **_):
        self.buffer, (self.width, self.height) = buffer, pagesize
        self.origin_height = self.height if origin_height is None else origin_height
        self.pages = []
        self.defs = ET.Element(tag('defs'))
        self.title = 'ECG de Repouso'
        self.font = ('Helvetica', 10)
        self.state = {'stroke': '#000', 'fill': '#000', 'stroke-width': '1'}
        self.stack, self.pending_trace = [], {}
        self._new_page()

    def _new_page(self):
        self.base = ET.Element(tag('g'), {'transform': f'translate(0 {f(self.origin_height)}) scale(1 -1)'})
        self.parent = self.base

    def setTitle(self, title):
        self.title = title

    def setAuthor(self, _):
        pass

    def setFont(self, name, size):
        self.font = (name, size)

    def setFillColorRGB(self, *values):
        self.state['fill'] = rgb(values)

    def setStrokeColorRGB(self, *values):
        self.state['stroke'] = rgb(values)

    def setLineWidth(self, width):
        self.state['stroke-width'] = f(width)

    def setDash(self, *values):
        self.state['stroke-dasharray'] = ' '.join(f(v) for v in values) if values else 'none'

    def stringWidth(self, text, font, size):
        return stringWidth(text, font, size)

    def _text(self, x, y, text, anchor):
        name, size = self.font
        family = 'Times New Roman,serif' if name.startswith('Times') else 'Arial,Helvetica,sans-serif'
        node = ET.SubElement(self.parent, tag('text'), {
            'transform': f'translate({f(x)} {f(y)}) scale(1 -1)',
            'font-family': family, 'font-size': f(size), 'text-anchor': anchor,
            'font-weight': '700' if 'Bold' in name else '400',
            'fill': self.state['fill'],
        })
        node.text = str(text)

    def drawString(self, x, y, text):
        self._text(x, y, text, 'start')

    def drawCentredString(self, x, y, text):
        self._text(x, y, text, 'middle')

    def drawRightString(self, x, y, text):
        self._text(x, y, text, 'end')

    def _style(self, stroke=1, fill=0):
        return self.state | {'stroke': self.state['stroke'] if stroke else 'none',
                             'fill': self.state['fill'] if fill else 'none'}

    def line(self, x1, y1, x2, y2):
        ET.SubElement(self.parent, tag('path'), self._style() | {'d': f'M{f(x1)} {f(y1)}L{f(x2)} {f(y2)}'})

    def rect(self, x, y, width, height, stroke=1, fill=0):
        ET.SubElement(self.parent, tag('rect'), self._style(stroke, fill) | {
            'x': f(x), 'y': f(y), 'width': f(width), 'height': f(height)})

    def beginPath(self):
        return SvgPath()

    def saveState(self):
        self.stack.append((deepcopy(self.state), self.font, self.parent))
        self.parent = ET.SubElement(self.parent, tag('g'))

    def restoreState(self):
        self.state, self.font, self.parent = self.stack.pop()

    def clipPath(self, path, **_):
        identity = f'clip-{len(self.defs)}'
        clip = ET.SubElement(self.defs, tag('clipPath'), {'id': identity, 'clipPathUnits': 'userSpaceOnUse'})
        ET.SubElement(clip, tag('path'), {'d': ''.join(path.commands)})
        self.parent.set('clip-path', f'url(#{identity})')

    def set_trace_metadata(self, **values):
        self.pending_trace = {'data-'+k.replace('_', '-'): str(v) for k, v in values.items()}

    def drawPath(self, path, stroke=1, fill=0):
        attrs = self._style(stroke, fill) | {'d': ''.join(path.commands)}
        if self.pending_trace:
            attrs |= self.pending_trace | {'class': 'ecg-trace', 'stroke-linejoin': 'round', 'stroke-linecap': 'round'}
            self.pending_trace = {}
        ET.SubElement(self.parent, tag('path'), attrs)

    def showPage(self):
        self.pages.append(self.base)
        self._new_page()

    def save(self):
        if len(self.base):
            self.showPage()
        gap = 12.0 if len(self.pages) > 1 else 0
        total = len(self.pages)*self.height + max(0, len(self.pages)-1)*gap
        root = ET.Element(tag('svg'), {
            'version': '1.1', 'viewBox': f'0 0 {f(self.width)} {f(total)}',
            'width': f(self.width/mm)+'mm', 'height': f(total/mm)+'mm',
            'role': 'img', 'aria-labelledby': 'ecg-title ecg-description',
            'data-pages': str(len(self.pages)), 'preserveAspectRatio': 'xMinYMin meet',
        })
        ET.SubElement(root, tag('title'), {'id': 'ecg-title'}).text = self.title
        ET.SubElement(root, tag('desc'), {'id': 'ecg-description'}).text = (
            'Traçado ECG vetorial: uma coordenada para cada amostra da janela, sem rasterização nem filtros adicionais. '
            'O zoom amplia a representação; não acrescenta resolução ao sinal adquirido.')
        root.append(self.defs)
        for index, page in enumerate(self.pages):
            viewport = ET.SubElement(root, tag('svg'), {
                'x': '0', 'y': f(index*(self.height+gap)), 'width': f(self.width), 'height': f(self.height),
                'viewBox': f'0 0 {f(self.width)} {f(self.height)}', 'data-page': str(index+1), 'overflow': 'hidden'})
            ET.SubElement(viewport, tag('rect'), {'width': f(self.width), 'height': f(self.height), 'fill': '#fff'})
            viewport.append(page)
        self.buffer.write(ET.tostring(root, encoding='utf-8', xml_declaration=True))


def render_svg(exam, pages, grid_color='gray', rhythm='DII', anonymize=False):
    return render_report(exam, pages, grid_color, rhythm, anonymize, canvas_factory=SvgCanvas)


def continuous_spec(exam, record=None, offset_seconds=0, duration_seconds=None):
    if record is None and len(exam.records) != 1:
        raise WxmlError('Para layout continuous com vários registros, selecione record (índice a partir de 1).')
    selected = next((r for r in exam.records if r.index == (record or 1)), None)
    if selected is None:
        raise WxmlError('Registro solicitado não existe.')
    if not math.isfinite(offset_seconds) or offset_seconds < 0:
        raise WxmlError('offset_seconds deve ser finito e não negativo.')
    start = int(round(offset_seconds*exam.sample_rate))
    n = len(selected.leads['DI'].samples)
    if not 0 <= start < n:
        raise WxmlError('offset_seconds está fora da duração do registro.')
    count = n-start
    if duration_seconds is not None:
        if not math.isfinite(duration_seconds) or not 0 < duration_seconds <= 60:
            raise WxmlError('duration_seconds deve ser maior que zero e no máximo 60.')
        count = min(count, max(1, int(round(duration_seconds*exam.sample_rate))))
    width = count/exam.sample_rate*selected.speed_mm_s
    if width > 1500:
        raise WxmlError('Janela contínua excede 1500 mm; reduza duration_seconds ou navegue com offset_seconds.')
    return PageSpec(selected, start, count, count)


def render_continuous(exam, spec, grid_color='gray', anonymize=False):
    output = BytesIO()
    r = spec.record
    signal_width = spec.short_samples/exam.sample_rate*r.speed_mm_s
    width = max(WIDTH, signal_width)
    height = TOP + 12*(HEIGHT+GAP) + 24
    c = SvgCanvas(output, pagesize=((LEFT+width+11)*mm, height*mm), origin_height=PAGE_HEIGHT*mm)
    c.setTitle('ECG - 12 derivações contínuas')
    name = 'PACIENTE ANONIMIZADO' if anonymize else exam.patient['name']
    fitted(c, LEFT, 13, 'ECG de Repouso - 12 derivações contínuas', width, 'Helvetica-Bold', 11)
    fitted(c, LEFT, 19, f'Nome: {name}', width, size=10)
    start = spec.start_sample/exam.sample_rate
    end = (spec.start_sample+spec.short_samples)/exam.sample_rate
    fitted(c, LEFT, 25, f'Registro {r.index} | Intervalo: {start:.3f}-{end:.3f} s | {exam.sample_rate:g} Hz | {r.speed_mm_s:g} mm/s | Ganho indicado em cada canal', width, size=8)
    fitted(c, LEFT, 30, f'Amostras por canal: {spec.short_samples} | Sem filtros adicionais | Zoom visual não altera os dados', width, size=8)
    for i, lead in enumerate(LEADS):
        trace(c, exam, spec, lead, LEFT, TOP+i*(HEIGHT+GAP), width, spec.short_samples, grid_color)
    fitted(c, LEFT, TOP+12*(HEIGHT+GAP)+5, 'A escala física na tela depende do zoom. Validar equivalência com o equipamento antes do uso clínico.', width, size=7)
    c.showPage()
    c.save()
    return output.getvalue()
