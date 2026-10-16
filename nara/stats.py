"""Minimal protobuf codec for sing-box's documented V2Ray StatsService.

Wire schema: experimental/v2rayapi/stats.proto in sing-box v1.14.3.
grpcio supplies HTTP/2; no generated code or protoc is needed at runtime.
"""


def varint(data, offset):
    value = shift = 0
    while offset < len(data) and shift < 70:
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
        shift += 7
    raise ValueError("Malformed protobuf varint")


def fields(data):
    offset = 0
    while offset < len(data):
        key, offset = varint(data, offset)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, offset = varint(data, offset)
        elif wire == 2:
            length, offset = varint(data, offset)
            if offset + length > len(data):
                raise ValueError("Truncated protobuf")
            value = data[offset:offset + length]
            offset += length
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            value = data[offset:offset + size]
            offset += size
        else:
            raise ValueError("Unsupported protobuf wire type")
        yield number, value


def decode_stats(data):
    result = {}
    for number, value in fields(data):
        if number == 1:
            row = dict(fields(value))
            name = row.get(1, b"").decode()
            counter = row.get(2, 0)
            if not isinstance(counter, int) or counter > 2**63 - 1:
                raise ValueError("Invalid traffic counter")
            result[name] = counter
    return result


def query(port):
    try:
        import grpc
    except ImportError:
        raise RuntimeError("grpcio is missing; install requirements.txt")
    with grpc.insecure_channel("127.0.0.1:" + str(port)) as channel:
        # sing-box overrides the proto package with the V2Ray-compatible name
        # in experimental/v2rayapi/stats.go during registration.
        request = channel.unary_unary("/v2ray.core.app.stats.command.StatsService/QueryStats",
                                     request_serializer=lambda x: x, response_deserializer=decode_stats)
        # Query all counters without resetting. Durable deltas avoid losing usage
        # if a request succeeds at the core but the response is lost.
        return request(b"", timeout=2)
