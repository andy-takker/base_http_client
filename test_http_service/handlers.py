from aiohttp.web_request import Request

from test_http_service.models import MockService, RequestHistory


def get_default_handler(handler_name: str):
    async def _handler(request: Request):
        history = RequestHistory(
            request=request,
            body=await request.read(),
        )
        context: MockService = request.app["service"]
        context.history.append(history)
        context.history_map[handler_name].append(history)
        handler = context.handlers[handler_name]
        return await handler.response(request)

    return _handler
