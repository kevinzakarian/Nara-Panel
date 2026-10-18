"""Read authenticated live connection identities from the private 1.14 API.

Wire fields: upstream daemon/started_service.proto. Only aggregate counts leave
this module; peer addresses, destinations and connection IDs are discarded.
"""
from .stats import fields


def decode_connections(data):
    counts = {}
    for number, event in fields(data):
        if number != 1:
            continue
        record = dict(fields(event))
        connection = record.get(3)
        if not isinstance(connection, bytes) or record.get(1, 0) == 2:
            continue
        row = dict(fields(connection))
        user = row.get(10, b'').decode('utf-8')
        if row.get(13, 0) or not user.startswith('client-'):
            continue
        identity = user[7:]
        counts[identity] = counts.get(identity, 0) + 1
    return counts


def query(port, secret):
    import grpc
    with grpc.insecure_channel('127.0.0.1:' + str(port), options=[('grpc.max_receive_message_length', 4 * 1024 * 1024)]) as channel:
        request = channel.unary_stream('/daemon.StartedService/SubscribeConnections', request_serializer=lambda value: value, response_deserializer=decode_connections)
        stream = request(b'', timeout=1.5, metadata=(('authorization', 'Bearer ' + secret),))
        try:
            return next(stream)
        finally:
            stream.cancel()
