"""CPU Worker 실행 스크립트.

사용법:
  python scripts/run_cpu_worker.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.workers.cpu_worker import start_worker

start_worker()
