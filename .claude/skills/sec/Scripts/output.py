import json


class SecError(Exception):
    def __init__(self, code, message, fix):
        super().__init__(message)
        self.code, self.message, self.fix = code, message, fix


def render(value, as_json):
    if as_json:
        return json.dumps(value, ensure_ascii=False, indent=2)
    if set(value) == {"error"}:
        error = value["error"]
        return f"Error [{error['code']}]: {error['message']}\nFix: {error['fix']}"
    return "\n".join(f"{key}: {json.dumps(item, ensure_ascii=False)}" for key, item in value.items())


def emit(value, as_json):
    if "returned_chars" in value:
        for _ in range(3):
            value["returned_chars"] = len(render(value, as_json)) + 1
    print(render(value, as_json))
