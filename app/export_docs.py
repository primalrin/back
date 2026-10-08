"""Prints the OpenAPI spec: python -m app.export_docs > docs.json"""

import json

from app.main import create_app

print(json.dumps(create_app().openapi(), ensure_ascii=False, indent=2))
