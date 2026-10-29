"""Write the OpenAPI schema to ``interfaces/openapi.json``."""

import json
import os

from src.api.main import app


# PUBLIC_INTERFACE
def main() -> str:
    """Generate the OpenAPI document and return the output path."""
    schema = app.openapi()
    output_dir = os.path.join(os.getcwd(), "interfaces")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "openapi.json")
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(schema, handle, indent=2)
    return output_path


if __name__ == "__main__":
    print(main())
