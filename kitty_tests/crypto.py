#!/usr/bin/env python
# License: GPLv3 Copyright: 2022, Kovid Goyal <kovid at kovidgoyal.net>


from . import BaseTest


class TestCrypto(BaseTest):

    def test_elliptic_curve_data_exchange(self):
        from kitty.fast_data_types import EllipticCurveKey
        alice = EllipticCurveKey()
        bob = EllipticCurveKey()
        alice_secret = alice.derive_secret(bob.public)
        bob_secret = bob.derive_secret(alice.public)
        self.assertEqual(len(alice_secret), 32)
        self.assertEqual(len(bob_secret), 32)
        self.assertEqual(alice_secret, bob_secret)
