from fastapi import Request


def envelope(data, request_id: str) -> dict:
    return {"data": data, "request_id": request_id}


def request_id(request: Request) -> str:
    return request.state.request_id
