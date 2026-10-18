import unittest
from unittest import mock
from nara import presence
from nara.config import initial_state, validate


def varint(value):
    encoded = bytearray()
    while value > 127:
        encoded.append((value & 127) | 128)
        value >>= 7
    return bytes(encoded) + bytes([value])


def integer(number, value):
    return varint(number << 3) + varint(value)


def string(number, value):
    if isinstance(value, str):value = value.encode()
    return varint((number << 3) | 2) + varint(len(value)) + value


class PresenceTests(unittest.TestCase):
    def test_only_open_managed_identities_are_counted(self):
        def entry(user, closed=0):
            return string(1, string(3, string(10, user) + integer(13, closed)))
        snapshot = entry('client-one') + entry('client-one') + entry('client-two', 100) + entry('external')
        self.assertEqual(presence.decode_connections(snapshot), {'one': 2})

    def test_palette_and_appearance_values_are_allowlisted(self):
        for key, invalid in [('skin', 'unexpected'), ('color_mode', 'unexpected')]:
            state = initial_state();state['settings'][key] = invalid
            with self.assertRaises(ValueError):validate(state)
        for skin in ('ember', 'volt', 'lagoon'):
            for mode in ('light', 'dark', 'system'):
                state = initial_state();state['settings'].update(skin=skin,color_mode=mode)
                validate(state)
