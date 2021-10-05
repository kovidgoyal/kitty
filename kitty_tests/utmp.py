from sys import platform

if platform in ('linux', 'linux2'):
    import subprocess
    import re
    from kitty.fast_data_types import num_users
    from . import BaseTest

    class UTMPTest(BaseTest):
        def test_num_users(self):
            # who -q is the control
            expected = subprocess.run(['who'], capture_output=True).stdout.decode('utf-8').count('\n')
            self.ae(num_users(), expected)
