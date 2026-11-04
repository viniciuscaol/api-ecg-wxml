"""Leitura estrita do perfil WinCardio observado no arquivo fornecido."""
from dataclasses import dataclass
import math
import re
from xml.etree.ElementTree import ParseError
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

LEADS = ('DI', 'DII', 'DIII', 'aVR', 'aVL', 'aVF', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6')
ALIASES = {name.upper(): name for name in LEADS} | {'I': 'DI', 'II': 'DII', 'III': 'DIII'}
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_SAMPLES = 1_000_000


class WxmlError(ValueError):
    pass


def number(text, field, minimum, maximum):
    try:
        value = float(text.strip().replace(',', '.'))
    except (ValueError, AttributeError):
        raise WxmlError(f'{field}: número ausente ou inválido.') from None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise WxmlError(f'{field}: valor fora do intervalo {minimum} a {maximum}.')
    return value


def txt(node, path):
    value = node.findtext(path, default='') or ''
    # Remove controles, limita metadados; nunca inclui valores do paciente em erros.
    return ''.join(c for c in value if c.isprintable()).strip()[:240]


@dataclass(frozen=True)
class Lead:
    name: str
    gain_mm_mv: float
    samples: tuple[int, ...]


@dataclass(frozen=True)
class Record:
    index: int
    number: str
    date: str
    time: str
    speed_mm_s: float
    heart_rate: str
    serial: str
    filter_60: bool
    filter_muscle: bool
    rhythm_field: str
    leads: dict[str, Lead]


@dataclass(frozen=True)
class Exam:
    version: str
    patient: dict[str, str]
    number: str
    sample_rate: float
    units_per_mv: float
    records: tuple[Record, ...]
    warnings: tuple[str, ...]


def parse_wxml(data: bytes) -> Exam:
    if not data or len(data) > MAX_FILE_BYTES:
        raise WxmlError('Arquivo vazio ou maior que 10 MiB.')
    try:
        root = ElementTree.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (ParseError, DefusedXmlException, ValueError, LookupError):
        raise WxmlError('XML inválido ou contém DTD/entidades não permitidas.') from None
    # Este perfil não promete compatibilidade com XML de outros fabricantes.
    if root.tag != 'WinCardio' or root.get('Tipo') != 'exame':
        raise WxmlError('Formato não suportado: esperado WinCardio Tipo="exame".')
    patient, exam = root.find('Paciente'), root.find('Exame')
    if patient is None or exam is None:
        raise WxmlError('Paciente ou Exame ausente.')
    group = exam.find('Registros')
    if group is None:
        raise WxmlError('Registros ausente.')
    rate_match = re.fullmatch(r'\s*([0-9]+(?:[.,][0-9]+)?)\s+amostras por segundo\s*', group.get('TaxaAmostragem', ''), re.I)
    sens_match = re.fullmatch(r'\s*([0-9]+(?:[.,][0-9]+)?)\s*/\s*([0-9]+(?:[.,][0-9]+)?)\s*mV\s*', group.get('Sensibilidade', ''), re.I)
    if not rate_match or not sens_match:
        raise WxmlError('TaxaAmostragem ou Sensibilidade ausente/fora do perfil suportado.')
    rate = number(rate_match[1], 'TaxaAmostragem', 1, 5000)
    units = number(sens_match[1], 'Sensibilidade', 0.001, 1e9) / number(sens_match[2], 'Sensibilidade mV', 0.001, 1e6)
    records, warnings, total = [], [], 0
    nodes = group.findall('Registro')
    if not 1 <= len(nodes) <= 30:
        raise WxmlError('Esperado de 1 a 30 registros.')
    declared = group.get('Quantidade')
    if declared is not None and declared != str(len(nodes)):
        raise WxmlError('Quantidade declarada não corresponde aos registros.')
    block = group.get('AmostrasPorBloco')
    if block is not None and (not block.isdigit() or not 1 <= int(block) <= MAX_TOTAL_SAMPLES):
        raise WxmlError('AmostrasPorBloco inválido.')
    for i, node in enumerate(nodes, 1):
        leads = {}
        for channel in node.findall('Canais/Canal'):
            name = ALIASES.get(channel.get('Nome', '').strip().upper())
            if name is None or name in leads:
                raise WxmlError('Canal desconhecido ou duplicado.')
            gain = number(txt(channel, 'Ganho'), 'Ganho', 0.1, 100)
            raw = channel.findtext('Amostras', '') or ''
            tokens = raw.strip().split(';')
            if tokens and not tokens[-1].strip():
                tokens.pop()  # Permite somente um delimitador final.
            total += len(tokens)
            if total > MAX_TOTAL_SAMPLES:
                raise WxmlError('Limite de 1.000.000 amostras por arquivo excedido.')
            if len(tokens) < 2 or any(not re.fullmatch(r'[+-]?\d{1,10}', t.strip()) for t in tokens):
                raise WxmlError('Amostras deve conter inteiros separados por ponto e vírgula.')
            values = tuple(int(t) for t in tokens)
            if any(abs(v) > 2_147_483_647 for v in values):
                raise WxmlError('Amostra fora do intervalo de inteiros de 32 bits.')
            leads[name] = Lead(name, gain, values)
        if set(leads) != set(LEADS):
            missing = ', '.join(n for n in LEADS if n not in leads)
            raise WxmlError(f'Registro {i}: derivações ausentes: {missing}.')
        lengths = {len(lead.samples) for lead in leads.values()}
        if len(lengths) != 1:
            raise WxmlError(f'Registro {i}: canais com quantidades diferentes de amostras.')
        count = lengths.pop()
        if block is not None and count != int(block):
            raise WxmlError(f'Registro {i}: amostras não correspondem a AmostrasPorBloco.')
        gains = {lead.gain_mm_mv for lead in leads.values()}
        if len(gains) > 1:
            warnings.append(f'Registro {i}: ganhos diferentes; veja a escala em cada quadro.')
        records.append(Record(i, node.get('Numero', str(i)), txt(node, 'Data') or txt(exam, 'Data'),
                              txt(node, 'Hora') or txt(exam, 'Hora'),
                              number(txt(node, 'Velocidade'), 'Velocidade', 5, 100),
                              txt(node, 'FrequenciaCardiaca'), txt(node, 'NroDeSerieEcg'),
                              node.find('Filtro60Hz') is not None, node.find('FiltroMuscular') is not None,
                              txt(node, 'CanalRitmo'), leads))
    fields = {'name': 'Nome', 'birth_date': 'DataNascimento', 'sex': 'Sexo',
              'clinical_record': 'RegistroClinico', 'rg': 'RG', 'cpf': 'CPF'}
    return Exam(txt(root, 'Versao'), {k: txt(patient, v) for k, v in fields.items()},
                txt(exam, 'NroExame') or txt(exam, 'ID'), rate, units, tuple(records), tuple(warnings))
