"""Config de pytest para pazguard-rrhh.

- Agrega el root del repo al sys.path (para `import app.*`).
- Setea env vars necesarias (secret CSRF, DEBUG).
- Stubbea pazguard_core.config si la lib no esta instalada localmente
  (en CI/local sin Postgres), para poder testear el middleware CSRF y la
  config sin depender del core real.
"""
import os
import sys
import types

# Root del repo (carpeta que contiene app/)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault('PAZGUARD_CORE_SECRET', 'test-secret-for-pytest')
os.environ.setdefault('DEBUG', '1')

# Stub minimo de pazguard_core.config si no esta instalado
try:
    import pazguard_core.config  # noqa: F401
except Exception:
    pc = types.ModuleType('pazguard_core')
    pc_config = types.ModuleType('pazguard_core.config')
    pc_config.SESSION_COOKIE_NAME = 'pazguard_session'
    pc_config.SESSION_TTL_HOURS = 12
    pc.config = pc_config
    sys.modules['pazguard_core'] = pc
    sys.modules['pazguard_core.config'] = pc_config
