"""Cliente Telegram via urllib stdlib (sin threading issues).

Reusa el bot existente (token compartido), envia a chat_ids configurados.
Usado solo desde el job de alertas; sin handlers ni polling.
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, telegram_listo

logger = logging.getLogger(__name__)


def enviar_mensaje(texto: str, chat_id: str = None, parse_mode: str = 'HTML') -> bool:
    """Envia mensaje a un chat o a todos los TELEGRAM_CHAT_IDS configurados.

    Retorna True si AL MENOS un envio fue exitoso.
    """
    if not telegram_listo():
        logger.info("Telegram no configurado (sin TOKEN o CHAT_IDS), skip envio")
        return False

    chats = [chat_id] if chat_id else TELEGRAM_CHAT_IDS
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    exito_total = False

    for cid in chats:
        try:
            data = urllib.parse.urlencode({
                'chat_id': cid,
                'text': texto,
                'parse_mode': parse_mode,
                'disable_web_page_preview': 'true',
            }).encode('utf-8')
            req = urllib.request.Request(url, data=data, method='POST')
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
                try:
                    rj = json.loads(body)
                except Exception:
                    rj = {'ok': False, 'raw': body[:200].decode('utf-8', 'replace')}
                if rj.get('ok'):
                    exito_total = True
                else:
                    logger.warning(f"Telegram envio fallo chat={cid}: {rj}")
        except urllib.error.HTTPError as e:
            err_body = ''
            try:
                err_body = e.read().decode('utf-8', 'replace')[:200]
            except Exception:
                pass
            logger.warning(f"Telegram HTTP {e.code} chat={cid}: {err_body}")
        except Exception as e:
            logger.warning(f"Telegram envio excepcion chat={cid}: {e}")
    return exito_total
