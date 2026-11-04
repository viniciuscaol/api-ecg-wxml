from contextlib import asynccontextmanager
from io import BytesIO
import asyncio
import hmac
import json
import os
from pathlib import Path
from typing import Literal
from zipfile import ZipFile, ZIP_DEFLATED
from fastapi import FastAPI, File, UploadFile, Query, Depends, Header, HTTPException
from fastapi.responses import Response, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from .parser import parse_wxml, WxmlError, MAX_FILE_BYTES, LEADS
from .render import page_specs, render_pdf, raster_pages, PANEL_WIDTH, WIDTH, HEIGHT
from .svg import render_svg, continuous_spec, render_continuous


class BodyLimitMiddleware:
    """Limita bytes recebidos inclusive em transferências chunked, antes do parser multipart."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        limit = MAX_FILE_BYTES + 64 * 1024
        headers = dict(scope.get('headers', []))
        try:
            size = int(headers.get(b'content-length', b'0'))
        except ValueError:
            return await Response('Content-Length inválido', status_code=400)(scope, receive, send)
        if size > limit:
            return await Response('Corpo da requisição excede o limite', status_code=413)(scope, receive, send)
        if scope['method'] not in ('POST', 'PUT', 'PATCH'):
            return await self.app(scope, receive, send)
        total, messages = 0, []
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            total += len(message.get('body', b''))
            if total > limit:
                return await Response('Corpo da requisição excede o limite', status_code=413)(scope, receive, send)
            messages.append(message)
            if not message.get('more_body', False):
                break
        # Corpo de no máximo 10 MiB + margem multipart em memória antes de qualquer escrita temporária.
        cursor = 0

        async def replay_receive():
            nonlocal cursor
            if cursor < len(messages):
                message = messages[cursor]
                cursor += 1
                return message
            return await receive()

        await self.app(scope, replay_receive, send)


@asynccontextmanager
async def lifespan(app):
    app.state.render_slots = asyncio.Semaphore(2)
    yield


app = FastAPI(title='ECG WXML API', version='1.1.0', lifespan=lifespan,
              description='ECG WinCardio em SVG vetorial para sistemas web, PDF, PNG e JPEG.')
app.add_middleware(BodyLimitMiddleware)
cors_origins = [origin.strip() for origin in os.getenv('ECG_CORS_ORIGINS', '').split(',') if origin.strip()]
if cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=['POST'],
                       allow_headers=['Content-Type', 'X-API-Key'],
                       expose_headers=['X-ECG-Pages', 'X-ECG-Layout'])


async def authorize(x_api_key: str | None = Header(default=None)):
    expected = os.getenv('ECG_API_KEY', '')
    if expected and not hmac.compare_digest((x_api_key or '').encode(), expected.encode()):
        raise HTTPException(401, 'Chave da API inválida ou ausente.')


async def read_exam(file):
    try:
        if not file.filename or Path(file.filename).suffix.lower() not in ('.wxml', '.xml'):
            raise HTTPException(415, 'Envie um arquivo .wxml ou .xml.')
        data = await file.read(MAX_FILE_BYTES+1)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, 'Arquivo excede 10 MiB.')
        return await run_in_threadpool(parse_wxml, data)
    except WxmlError as e:
        raise HTTPException(422, str(e)) from None
    finally:
        await file.close()


def metadata(exam, anonymize=False):
    return {
        'profile': 'WinCardio', 'xml_version': exam.version,
        'exam_number': None if anonymize else exam.number,
        'patient': None if anonymize else exam.patient,
        'sample_rate_hz': exam.sample_rate, 'units_per_mv': exam.units_per_mv,
        'warnings': list(exam.warnings),
        'records': [{
            'index': r.index, 'xml_number': r.number, 'date': r.date, 'time': r.time,
            'samples_per_lead': len(r.leads['DI'].samples),
            'duration_seconds': len(r.leads['DI'].samples)/exam.sample_rate,
            'speed_mm_s': r.speed_mm_s, 'heart_rate_from_xml': r.heart_rate,
            'serial': None if anonymize else r.serial,
            'filters_declared': {'60_hz': r.filter_60, 'muscular': r.filter_muscle},
            'rhythm_field_raw': r.rhythm_field,
            'leads': [{'name': n, 'gain_mm_mv': r.leads[n].gain_mm_mv,
                       'samples': len(r.leads[n].samples)} for n in LEADS],
        } for r in exam.records],
    }


@app.get('/health')
def health():
    return {'status': 'ok', 'version': '1.1.0'}


@app.get('/', response_class=HTMLResponse, include_in_schema=False)
def home():
    return HTMLResponse(Path(__file__).with_name('index.html').read_text('utf-8'))


@app.get('/assets/ecg-viewer.js', include_in_schema=False)
def viewer_component():
    return Response(Path(__file__).with_name('ecg-viewer.js').read_text('utf-8'), media_type='text/javascript',
                    headers={'X-Content-Type-Options': 'nosniff'})


@app.post('/inspect', dependencies=[Depends(authorize)])
async def inspect(file: UploadFile = File(...), anonymize: bool = False):
    exam = await read_exam(file)
    return Response(json.dumps(metadata(exam, anonymize), ensure_ascii=False), media_type='application/json',
                    headers={'Cache-Control': 'no-store'})


def convert_bytes(exam, specs, format, dpi, grid, rhythm, anonymize, layout):
    if format == 'svg':
        if layout == 'continuous':
            return render_continuous(exam, specs[0], grid, anonymize)
        return render_svg(exam, specs, grid, rhythm, anonymize)
    pdf = render_pdf(exam, specs, grid, rhythm, anonymize)
    if format == 'pdf':
        return pdf
    images = raster_pages(pdf, dpi, 'jpeg' if format == 'jpeg' else 'png')
    if format in ('png', 'jpeg'):
        return images[0]
    manifest = metadata(exam, anonymize)
    manifest['render'] = {'layout': layout, 'grid': grid, 'dpi': dpi, 'rhythm_lead': rhythm,
                          'panel_width_mm': PANEL_WIDTH, 'rhythm_width_mm': WIDTH,
                          'panel_height_mm': HEIGHT,
                          'signal_processing': 'none', 'pages': [{
                              'page': i, 'record_index': s.record.index,
                              'start_sample': s.start_sample, 'short_samples': s.short_samples,
                              'rhythm_samples': s.rhythm_samples} for i, s in enumerate(specs, 1)]}
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as z:
        z.writestr('ecg.pdf', pdf)
        z.writestr('metadata.json', json.dumps(manifest, indent=2, ensure_ascii=False))
        for i, data in enumerate(images, 1):
            z.writestr(f'ecg-{i:03}.png', data)
    return output.getvalue()


@app.post('/convert', dependencies=[Depends(authorize)], responses={
    200: {'description': 'SVG nativo ou arquivo binário', 'content': {'image/svg+xml': {}, 'application/pdf': {}, 'image/png': {}, 'image/jpeg': {}, 'application/zip': {}}},
    422: {'description': 'XML ou opções incompatíveis'},
})
async def convert(file: UploadFile = File(...),
                  format: Literal['svg', 'pdf', 'png', 'jpeg', 'zip'] = 'pdf',
                  layout: Literal['reference', 'complete', 'continuous'] = 'reference',
                  record: int | None = Query(None, ge=1, le=30),
                  offset_seconds: float = Query(0, ge=0, le=86400, allow_inf_nan=False),
                  duration_seconds: float | None = Query(None, gt=0, le=60, allow_inf_nan=False),
                  dpi: int = Query(200, ge=72, le=300),
                  grid: Literal['gray', 'red'] = 'gray',
                  rhythm: Literal['DI', 'DII', 'DIII', 'aVR', 'aVL', 'aVF', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6'] = 'DII',
                  anonymize: bool = False):
    exam = await read_exam(file)
    try:
        if layout == 'continuous':
            if format != 'svg':
                raise WxmlError('layout=continuous está disponível apenas para format=svg.')
            specs = [continuous_spec(exam, record, offset_seconds, duration_seconds)]
        else:
            if duration_seconds is not None:
                raise WxmlError('duration_seconds é usado apenas com layout=continuous.')
            specs = page_specs(exam, layout, record, offset_seconds)
        if format in ('png', 'jpeg') and len(specs) != 1:
            raise WxmlError('PNG/JPEG exige uma página. Selecione record e layout=reference ou use PDF/ZIP.')
        # Limite conservador por processo para evitar dezenas de rasters de 300 DPI em memória.
        if format == 'zip' and len(specs) * (210/25.4*dpi) * (297/25.4*dpi) > 60_000_000:
            raise WxmlError('ZIP excede orçamento de 60 megapixels; reduza dpi ou use PDF.')
        async with app.state.render_slots:
            data = await run_in_threadpool(convert_bytes, exam, specs, format, dpi, grid, rhythm, anonymize, layout)
    except WxmlError as e:
        raise HTTPException(422, str(e)) from None
    mime = {'svg': 'image/svg+xml', 'pdf': 'application/pdf', 'png': 'image/png', 'jpeg': 'image/jpeg', 'zip': 'application/zip'}[format]
    headers = {
        'Content-Disposition': f'{"inline" if format == "svg" else "attachment"}; filename="ecg.{"jpg" if format == "jpeg" else format}"',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'X-ECG-Pages': str(len(specs)), 'X-ECG-Layout': layout,
    }
    if format == 'svg':
        headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return Response(data, media_type=mime, headers=headers)
