# pazguard-rrhh

Sistema RRHH/SUCAMEC de PAZGUARD Security S.A.C.

Servicio satelite de la suite PAZGUARD. Maneja:
- Autorizaciones SUCAMEC (modalidades de servicio)
- Carta fianza (5 UIT minimo, renovacion)
- (proximamente) Personal vigilante con multi-vigencia
- (proximamente) Armeria SUCAMEC con libro de armas
- (proximamente) Planilla DL 728 + SCTR Riesgo III
- (proximamente) Reportes SUCAMEC pre-formateados

## Arquitectura

- FastAPI + Jinja2 + Postgres (compartido con `pazguard-core`)
- SSO via handover tokens efimeros desde `pazguard-hub`
- Alertas Telegram via bot Facturas existente
- Job APScheduler diario 9am Peru para vencimientos

## Variables de entorno

```
CORE_DATABASE_URL        # Postgres del core (compartido con hub)
PAZGUARD_CORE_SECRET     # secret para SSO + CSRF
CSRF_SECRET              # opcional (fallback al core secret)
TELEGRAM_BOT_TOKEN       # token del bot de Facturas (para alertas)
TELEGRAM_CHAT_IDS        # CSV de chat_ids destinatarios de alertas
LOG_FORMAT=json          # opcional, para Railway logs
LOG_LEVEL=INFO
RUN_MIGRATIONS_ON_BOOT=1 # solo primera vez o cuando cambien migrations
```

## Deploy local

```bash
pip install -r requirements.txt
export DATABASE_URL=postgresql://...   # del core
export PAZGUARD_CORE_SECRET=...
uvicorn app.main:app --reload --port 8080
```

## Deploy Railway

Servicio dentro del project "PAZGUARD Suite".
Mismas vars que el hub + las propias de RRHH.

## Endpoints

| Path | Descripcion |
|---|---|
| `/health` | Health check (Railway) |
| `/` | Dashboard compliance |
| `/modalidades` | CRUD modalidades SUCAMEC |
| `/cartas-fianza` | CRUD cartas fianza |
| `/login` | Login local (fallback si no hay SSO) |
| `/logout` | Cerrar sesion |

## Roadmap

Ver `C:/BOT LOG/Bot-Facturas-Pazguard/docs/PLAN_RRHH_SUCAMEC.md`.

Fase 4.1 (este servicio inicial): Modalidades + Carta Fianza + dashboard +
alertas Telegram.

Fase 4.2: Personal vigilante + vigencias multiples.

Fase 4.3: Armeria + libro de armas.

(...)
