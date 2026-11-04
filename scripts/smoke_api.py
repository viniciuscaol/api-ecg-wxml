"""Smoke HTTP reproduzível com a biblioteca padrão e exame sintético.

Execute com a API já iniciada. ECG_API_KEY deve corresponder à chave do
servidor. ECG_TEST_URL permite mudar o endereço, cujo padrão é localhost.
Não imprime nem grava o conteúdo dos exames ou os arquivos convertidos.
"""
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


def multipart(data: bytes, filename: str = "synthetic.wxml") -> tuple[bytes, str]:
    boundary = "ecg-smoke-" + uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/xml\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def request(base: str, path: str, data: bytes | None = None,
            key: str | None = None) -> tuple[int, object, bytes]:
    headers = {}
    body = None
    if data is not None:
        body, headers["Content-Type"] = multipart(data)
    if key is not None:
        headers["X-API-Key"] = key
    req = Request(base.rstrip("/") + path, data=body, headers=headers)
    try:
        with urlopen(req, timeout=60) as response:
            return response.status, response.headers, response.read()
    except HTTPError as response:
        try:
            return response.code, response.headers, response.read()
        finally:
            response.close()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    base = os.getenv("ECG_TEST_URL", "http://127.0.0.1:8000")
    key = os.getenv("ECG_API_KEY", "")
    require(bool(key), "Configure ECG_API_KEY no servidor e neste teste.")
    data = (ROOT / "examples" / "synthetic.wxml").read_bytes()

    status, _, body = request(base, "/health")
    require(status == 200 and json.loads(body).get("status") == "ok", "Health check falhou.")

    status, _, _ = request(base, "/inspect", data)
    require(status == 401, "API deveria rejeitar requisição sem chave.")
    status, _, _ = request(base, "/inspect", data, key + "-invalida")
    require(status == 401, "API deveria rejeitar chave incorreta.")

    status, headers, body = request(base, "/inspect?anonymize=true", data, key)
    require(status == 200, f"Inspeção falhou: HTTP {status}.")
    meta = json.loads(body)
    require(meta["patient"] is None, "Identificação não foi ocultada.")
    require(meta["profile"] == "WinCardio", "Perfil inesperado.")
    require(bool(meta["records"]) and len(meta["records"][0]["leads"]) == 12,
            "Esperadas 12 derivações no registro sintético.")
    require(headers.get("Cache-Control") == "no-store", "Resposta sem proteção de cache.")

    status, headers, body = request(
        base, "/convert?format=svg&layout=continuous&record=1&anonymize=true", data, key)
    require(status == 200, f"Conversão SVG falhou: HTTP {status}.")
    require(headers.get_content_type() == "image/svg+xml" and b"<svg" in body,
            "Resposta SVG inválida.")
    require(b"<path" in body and b"<image" not in body, "Esperado traçado SVG vetorial.")

    status, headers, body = request(base, "/convert?format=pdf&anonymize=true", data, key)
    require(status == 200 and headers.get_content_type() == "application/pdf"
            and body.startswith(b"%PDF-"), "Conversão PDF falhou.")

    status, _, _ = request(base, "/convert", b"<invalid", key)
    require(status == 422, "API deveria rejeitar XML inválido.")
    print("Smoke HTTP aprovado: saúde, autenticação, metadados, SVG, PDF e XML inválido.")


if __name__ == "__main__":
    main()
