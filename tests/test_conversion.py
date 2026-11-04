from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import asyncio
from pathlib import Path
from zipfile import ZipFile
import pytest
from PIL import Image
from pypdf import PdfReader
from fastapi.testclient import TestClient
from app.main import app, BodyLimitMiddleware
from app.parser import parse_wxml, WxmlError, LEADS, MAX_FILE_BYTES
from app.render import page_specs, sample_position, render_pdf, raster_pages

DATA = Path(__file__).resolve().parents[1].joinpath('examples/synthetic.wxml').read_bytes()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv('ECG_API_KEY', raising=False)
    with TestClient(app) as c:
        yield c


def upload(client, path='/convert', data=DATA):
    return client.post(path, files={'file': ('exam.WXML', data, 'application/xml')})


def test_calibration_and_patient():
    exam = parse_wxml(DATA)
    assert exam.sample_rate == 600
    assert exam.units_per_mv == 200
    assert len(exam.records[0].leads['DI'].samples) == 4800
    assert exam.patient['name'] == 'PACIENTE TESTE SINTÉTICO'
    # 200 unidades = 1 mV = 10 mm; 600 amostras = 1 segundo = 25 mm.
    assert sample_position(600, 200, 600, 25, 200, 10) == (25, 10)
    assert sample_position(300, -100, 600, 25, 200, 5) == (12.5, -2.5)


@pytest.mark.parametrize('data', [b'<x/>', b'not xml',
    b'<!DOCTYPE WinCardio [<!ENTITY a "test">]><WinCardio Tipo="exame">&a;</WinCardio>',
    DATA.replace(b'200/1mV', b'0/1mV'),
    DATA.replace(b'600 amostras por segundo', b'NaN'),
    DATA.replace(b'<Ganho>10</Ganho>', b'<Ganho>NaN</Ganho>', 1),
    DATA.replace(b'Nome="DI"', b'Nome="V99"', 1),
    DATA.replace(b'Nome="DI"', b'Nome="DII"', 1),
    DATA.replace(b'AmostrasPorBloco="4800"', b'AmostrasPorBloco="4801"'),
    DATA.replace(b'Quantidade="1"', b'Quantidade="2"'),
    DATA.replace(b'<Amostras>', b'<Amostras>abc;', 1),
])
def test_invalid_profile_is_rejected(data):
    with pytest.raises(WxmlError):
        parse_wxml(data)


def test_complete_keeps_all_samples():
    exam = parse_wxml(DATA)
    pages = page_specs(exam, 'complete')
    positions = [p.start_sample+i for p in pages for i in range(p.short_samples)]
    assert positions == list(range(4800))
    assert len(page_specs(exam)) == 1
    with pytest.raises(WxmlError):
        page_specs(exam, offset_seconds=8)
    with pytest.raises(WxmlError):
        page_specs(exam, record=2)


def test_api_pdf_and_metadata(client):
    response = upload(client)
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/pdf'
    assert response.headers['cache-control'] == 'no-store'
    pdf = PdfReader(BytesIO(response.content))
    assert len(pdf.pages) == 1
    assert tuple(float(x) for x in pdf.pages[0].mediabox[2:]) == pytest.approx((595.2756, 841.8898), abs=0.001)
    text = pdf.pages[0].extract_text()
    assert 'PACIENTE TESTE SINTÉTICO' in text
    assert all(lead in text for lead in LEADS)
    info = upload(client, '/inspect').json()
    assert info['records'][0]['duration_seconds'] == 8
    assert info['sample_rate_hz'] == 600
    assert info['records'][0]['leads'][0]['samples'] == 4800


@pytest.mark.parametrize('format,mime,pil_format', [('png','image/png','PNG'), ('jpeg','image/jpeg','JPEG')])
def test_images(client, format, mime, pil_format):
    r = upload(client, f'/convert?format={format}&dpi=150')
    assert r.status_code == 200
    assert r.headers['content-type'] == mime
    with Image.open(BytesIO(r.content)) as image:
        assert image.format == pil_format
        assert image.size == (1241, 1754)
        assert image.info['dpi'][0] == pytest.approx(150, abs=0.1)


def test_zip_complete_and_anonymization(client):
    r = upload(client, '/convert?format=zip&layout=complete&dpi=72&anonymize=true')
    assert r.status_code == 200
    with ZipFile(BytesIO(r.content)) as z:
        meta = json.loads(z.read('metadata.json'))
        assert meta['patient'] is None
        assert meta['exam_number'] is None
        pages = meta['render']['pages']
        assert sum(p['short_samples'] for p in pages) == 4800
        assert len(z.namelist()) == len(pages)+2
        text = ''.join(p.extract_text() for p in PdfReader(BytesIO(z.read('ecg.pdf'))).pages)
        assert 'PACIENTE TESTE SINTÉTICO' not in text
        assert 'PACIENTE ANONIMIZADO' in text
        assert len(PdfReader(BytesIO(z.read('ecg.pdf'))).pages) == len(pages)


@pytest.mark.parametrize('query', ['format=png&layout=complete','record=2','dpi=301','offset_seconds=8', 'offset_seconds=nan', 'rhythm=unknown'])
def test_invalid_requests(client, query):
    assert upload(client, '/convert?'+query).status_code == 422


def test_api_auth_and_errors(client, monkeypatch):
    assert client.get('/health').json()['status'] == 'ok'
    assert client.get('/').status_code == 200
    assert client.get('/openapi.json').status_code == 200
    assert client.post('/convert', files={'file': ('x.txt', DATA)}).status_code == 415
    assert upload(client, data=b'<x/>').status_code == 422
    assert client.post('/convert').status_code == 422
    monkeypatch.setenv('ECG_API_KEY', 'test-secret')
    assert upload(client).status_code == 401
    assert client.post('/inspect', files={'file': ('x.wxml', DATA)}, headers={'X-API-Key': 'test-secret'}).status_code == 200


def test_oversized_upload(client):
    assert upload(client, data=b'x'*(MAX_FILE_BYTES+1)).status_code == 413


async def check_chunked_body_cap():
    called = False
    async def next_app(scope, receive, send):
        nonlocal called
        called = True
    messages = iter([{'type': 'http.request', 'body': b'x'*1024*1024, 'more_body': True}]*11)
    async def receive():
        return next(messages)
    output = []
    async def send(message):
        output.append(message)
    await BodyLimitMiddleware(next_app)({'type':'http', 'method':'POST', 'headers':[]}, receive, send)
    assert not called
    assert output[0]['status'] == 413


def test_chunked_body_cap():
    asyncio.run(check_chunked_body_cap())


def test_parallel_pdf_rasterization():
    exam = parse_wxml(DATA)
    pdf = render_pdf(exam, page_specs(exam))
    with ThreadPoolExecutor(max_workers=3) as pool:
        images = list(pool.map(lambda _: raster_pages(pdf, 72)[0], range(3)))
    assert images[0] == images[1] == images[2]


def test_amp_clipping_warning():
    high = DATA.replace(b'<Ganho>10</Ganho>', b'<Ganho>100</Ganho>', 1)
    exam = parse_wxml(high)
    pdf = render_pdf(exam, page_specs(exam))
    assert 'Sinal excede altura do quadro' in PdfReader(BytesIO(pdf)).pages[0].extract_text()
