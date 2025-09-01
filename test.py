import fastapi_poe as fp

message = fp.ProtocolMessage(role="user", content="Hello world")

api_key = "YOUR_POE_API_KEY"  # or os.getenv("POE_API_KEY")

for partial in fp.get_bot_response_sync(
    messages=[message], bot_name="Claude-Sonnet-3.5", api_key=api_key
):
    print(partial)