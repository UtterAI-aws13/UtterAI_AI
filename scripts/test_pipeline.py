import asyncio
import json

from dotenv import load_dotenv
load_dotenv()

from app.pipelines.report_pipeline import run_report_pipeline

result = asyncio.run(run_report_pipeline("test_job_001"))
print(json.dumps(result, ensure_ascii=False, indent=2))
